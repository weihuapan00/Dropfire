"""Per-connection outbound queues decouple the game tick from slow clients."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import TypeAlias

from fastapi import WebSocket


Snapshot: TypeAlias = tuple[str, Callable[[], None] | None]


class ConnectionSender:
    """Keep only the newest snapshot queued while a send is in flight."""

    def __init__(
        self,
        websocket: WebSocket,
        on_close: Callable[[WebSocket], None],
    ) -> None:
        self.websocket = websocket
        self.on_close = on_close
        self.queue: asyncio.Queue[Snapshot] = asyncio.Queue(maxsize=1)
        self.lock = asyncio.Lock()
        self.closed = False
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            while True:
                payload, on_sent = await self.queue.get()
                async with self.lock:
                    await self.websocket.send_text(payload)
                if on_sent is not None:
                    on_sent()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.closed = True
            self.on_close(self.websocket)

    def enqueue(self, payload: str, on_sent: Callable[[], None] | None = None) -> None:
        """Replace any queued snapshot with the newest one, without blocking."""
        if self.closed:
            return
        if self.queue.full():
            with suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
        with suppress(asyncio.QueueFull):
            self.queue.put_nowait((payload, on_sent))

    async def send_control(self, payload: str) -> bool:
        """Send a control frame in order with any in-flight snapshot."""
        if self.closed:
            return False
        try:
            async with self.lock:
                await self.websocket.send_text(payload)
            return True
        except Exception:
            self.closed = True
            self.on_close(self.websocket)
            return False

    async def close(self) -> None:
        self.closed = True
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task
