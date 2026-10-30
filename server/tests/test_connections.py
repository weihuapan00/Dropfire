"""Tests for per-connection outbound snapshot queues."""

import asyncio

from app.connections import ConnectionSender


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def send_text(self, payload: str) -> None:
        self.started.set()
        await self.release.wait()
        self.sent.append(payload)


def test_sender_drops_stale_snapshot_while_blocked():
    async def scenario() -> tuple[list[str], list[bool]]:
        closed: list[bool] = []
        websocket = FakeWebSocket()
        sender = ConnectionSender(websocket, lambda _: closed.append(True))

        sender.enqueue("first")
        await asyncio.wait_for(websocket.started.wait(), timeout=1)
        sender.enqueue("stale")
        sender.enqueue("latest")
        websocket.release.set()

        for _ in range(20):
            await asyncio.sleep(0.01)
            if len(websocket.sent) >= 2:
                break

        await sender.close()
        return websocket.sent, closed

    sent, closed = asyncio.run(scenario())

    assert sent == ["first", "latest"]
    assert closed == []
