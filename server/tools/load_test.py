"""Load-test Dropfire rooms over WebSocket.

This script creates rooms, connects simulated players, optionally fills each
room with bots, starts the match, and measures ping RTT plus health-endpoint
latency. It refuses to run against a server that already has human players
unless ``--force`` is passed, so a live match is not disturbed by accident.

Examples:
    python tools/load_test.py --rooms 4 --players 8 --bots 2
    python tools/load_test.py --http-base https://dropfire.wpdatasoft.com \
        --ws-base wss://dropfire.wpdatasoft.com --rooms 12 --players 8 --force
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import urllib.error
import urllib.request
from typing import Any
from uuid import uuid4

import websockets


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(len(ordered) * fraction) - 1))
    return ordered[index]


def fetch_health(http_base: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{http_base}/api/health", timeout=10) as response:
        return json.load(response)


def create_room(http_base: str) -> str | None:
    request = urllib.request.Request(f"{http_base}/api/rooms", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)["code"]
    except urllib.error.HTTPError as error:
        if error.code == 503:
            return None
        raise


async def run_client(
    ws_base: str,
    room_code: str,
    player_index: int,
    is_host: bool,
    bots: int,
    pings: int,
    interval: float,
    rtt_samples: list[float],
    errors: list[str],
) -> None:
    url = (
        f"{ws_base}/ws/{room_code}"
        f"?session=load-{uuid4().hex}&name=L{player_index}"
    )
    try:
        async with websockets.connect(
            url,
            open_timeout=10,
            close_timeout=5,
            max_queue=None,
        ) as socket:
            while True:
                raw = await asyncio.wait_for(socket.recv(), timeout=10)
                text = raw.decode() if isinstance(raw, bytes) else raw
                if '"server_connected"' in text:
                    break

            if is_host:
                for _ in range(bots):
                    await socket.send(json.dumps({"type": "add_ai_bot"}))
                    await asyncio.sleep(0.03)
                await socket.send(json.dumps({"type": "start_match"}))

            for _ in range(pings):
                sent_at = time.perf_counter()
                await socket.send(
                    json.dumps({"type": "ping", "client_sent_at": sent_at})
                )
                while True:
                    raw = await asyncio.wait_for(socket.recv(), timeout=10)
                    text = raw.decode() if isinstance(raw, bytes) else raw
                    if '"pong"' in text:
                        break
                rtt_samples.append((time.perf_counter() - sent_at) * 1000)
                await asyncio.sleep(interval)
    except Exception as error:  # noqa: BLE001 - report per-client failures
        errors.append(f"{room_code}#{player_index}: {error!r}")


async def monitor_health(
    http_base: str,
    stop_event: asyncio.Event,
    samples: list[tuple[float, dict[str, Any]]],
    errors: list[str],
) -> None:
    while not stop_event.is_set():
        started_at = time.perf_counter()
        try:
            health = await asyncio.to_thread(fetch_health, http_base)
            samples.append(((time.perf_counter() - started_at) * 1000, health))
        except Exception as error:  # noqa: BLE001 - keep the monitor alive
            errors.append(f"health: {error!r}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def run(args: argparse.Namespace) -> int:
    before = await asyncio.to_thread(fetch_health, args.http_base)
    if before.get("players", 0) > 0 and not args.force:
        print(
            "Refusing to load-test while players are online "
            f"(rooms={before.get('rooms')}, players={before.get('players')}). "
            "Use --force only during a maintenance window."
        )
        return 2

    room_codes: list[str] = []
    for _ in range(args.rooms):
        code = await asyncio.to_thread(create_room, args.http_base)
        if code is None:
            print("Server reported room capacity; stopping room creation.")
            break
        room_codes.append(code)

    rtt_samples: list[float] = []
    health_samples: list[tuple[float, dict[str, Any]]] = []
    errors: list[str] = []
    stop_event = asyncio.Event()
    monitor = asyncio.create_task(
        monitor_health(args.http_base, stop_event, health_samples, errors)
    )

    started_at = time.perf_counter()
    tasks: list[asyncio.Task[None]] = []
    for code in room_codes:
        for player_index in range(args.players):
            tasks.append(
                asyncio.create_task(
                    run_client(
                        args.ws_base,
                        code,
                        player_index,
                        is_host=player_index == 0,
                        bots=args.bots,
                        pings=args.pings,
                        interval=args.interval,
                        rtt_samples=rtt_samples,
                        errors=errors,
                    )
                )
            )
        await asyncio.sleep(args.ramp)

    await asyncio.gather(*tasks)
    stop_event.set()
    await monitor
    wall_seconds = time.perf_counter() - started_at

    if args.cleanup_wait > 0:
        await asyncio.sleep(args.cleanup_wait)

    print("\n=== Dropfire load test ===")
    print(f"target: {args.http_base}")
    print(f"rooms created: {len(room_codes)} (requested {args.rooms})")
    print(f"players per room: {args.players}, bots per room: {args.bots}")
    print(f"pings per player: {args.pings}, wall time: {wall_seconds:.1f}s")
    print(f"errors: {len(errors)}")
    for error in errors[:10]:
        print(f"  - {error}")

    if rtt_samples:
        print(
            "ws rtt ms  min/avg/p95/max: "
            f"{min(rtt_samples):.1f} / {statistics.mean(rtt_samples):.1f} / "
            f"{percentile(rtt_samples, 0.95):.1f} / {max(rtt_samples):.1f}"
        )
    else:
        print("ws rtt: no samples")

    if health_samples:
        health_latency = [latency for latency, _ in health_samples]
        peak_rooms = max(health["rooms"] for _, health in health_samples)
        peak_players = max(health["players"] for _, health in health_samples)
        print(
            "health latency ms  min/avg/p95/max: "
            f"{min(health_latency):.1f} / {statistics.mean(health_latency):.1f} / "
            f"{percentile(health_latency, 0.95):.1f} / {max(health_latency):.1f}"
        )
        print(f"server peak: rooms={peak_rooms}, players={peak_players}")

    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-base", default="http://127.0.0.1:8000")
    parser.add_argument("--ws-base", default="ws://127.0.0.1:8000")
    parser.add_argument("--rooms", type=int, default=4)
    parser.add_argument("--players", type=int, default=8)
    parser.add_argument("--bots", type=int, default=0)
    parser.add_argument("--pings", type=int, default=20)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--ramp", type=float, default=0.2)
    parser.add_argument("--cleanup-wait", type=float, default=0.0)
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow the test even when human players are online",
    )
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
