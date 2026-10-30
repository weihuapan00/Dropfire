"""FastAPI application wiring for Dropfire.

Game rules live in ``rules``, AI and bot lifecycle live in ``bots``, room
storage lives in ``state``, and static tuning values live in ``config``. This
module only assembles the web app, the authoritative game loop, and the
WebSocket endpoint.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnected

from .bots import (
    add_fill_bot,
    advance_fill_bot_ai,
    move_test_bot,
    move_test_bot_to_pickup,
    rebalance_fill_bots,
    remove_expired_disconnections,
    remove_one_fill_bot,
    respawn_test_bot,
    spawn_test_bot,
)
from .config import (
    COVER_WALLS,
    DEFAULT_WEAPON,
    MAX_PLAYERS,
    MAX_TICK_SECONDS,
    PLAYER_MAX_HP,
    RECONNECT_GRACE_SECONDS,
    SPAWN_PROTECTION_SECONDS,
    TICK_INTERVAL_SECONDS,
)
from .rules import (
    advance_bullets,
    advance_melee_attacks,
    advance_player_movement,
    advance_reloads,
    advance_respawns,
    advance_round,
    apply_move_intent,
    attack_with_melee,
    collect_weapon_pickup,
    fire_weapon,
    get_melee_progress,
    get_reload_progress,
    get_respawn_ends_in_seconds,
    get_round_snapshot,
    get_spawn_protection_ends_in_seconds,
    reload_weapon,
    request_match_start,
    reset_test_round,
    reset_weapon_pickups,
    switch_weapon,
)
from .state import (
    active_connections,
    bullets,
    create_room,
    current_room,
    hit_events,
    players,
    room_context,
    rooms,
    weapon_pickups,
)


game_loop_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run one authoritative game loop for the lifetime of the server."""
    global game_loop_task
    game_loop_task = asyncio.create_task(game_loop())
    try:
        yield
    finally:
        game_loop_task.cancel()
        with suppress(asyncio.CancelledError):
            await game_loop_task


app = FastAPI(title="Dropfire Server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def sanitize_player_name(raw_name: str | None) -> str | None:
    """Return a trimmed, bounded player name or None when no name was provided."""
    if not isinstance(raw_name, str):
        return None
    name = " ".join(raw_name.split())[:16]
    return name or None


@app.get("/api/rooms")
async def list_rooms() -> list[dict[str, Any]]:
    """List in-memory rooms that a browser can join from the lobby."""
    return [
        {
            "code": code,
            "players": len(room["players"]),
            "human_players": sum(not player["is_bot"] for player in room["players"].values()),
            "max_players": MAX_PLAYERS,
            "phase": room["round_state"]["phase"],
        }
        for code, room in rooms.items()
    ]


@app.post("/api/rooms")
async def create_room_endpoint() -> dict[str, str]:
    """Create a room and return its six-character invite code."""
    return {"code": create_room()}


async def broadcast_world_state() -> None:
    """Send the complete current player list to every connected browser."""
    now = monotonic()
    message = {
        "type": "world_state",
        "round": get_round_snapshot(now),
        "players": [
            {
                "id": player_id,
                "x": player["x"],
                "y": player["y"],
                "weapon": player["weapon"],
                "melee_weapon": player["melee_weapon"],
                "gun_weapon": player["gun_weapon"],
                "ammo_in_mag": player["ammo_in_mag"],
                "magazine_capacity": player["magazine_capacity"],
                "reload_progress": get_reload_progress(player, now),
                "melee_progress": get_melee_progress(player, now),
                "melee_angle": player["melee_angle"],
                "hp": player["hp"],
                "alive": player["alive"],
                "connected": player["connected"],
                "damage_dealt": player["damage_dealt"],
                "kills": player["kills"],
                "respawn_ends_in_seconds": get_respawn_ends_in_seconds(player, now),
                "spawn_protection_ends_in_seconds": get_spawn_protection_ends_in_seconds(player, now),
                "is_bot": player["is_bot"],
                "name": player.get("name"),
                "owner_id": player["owner_id"],
                "is_host": player_id == current_room()["host_player_id"],
            }
            for player_id, player in players.items()
        ],
        "covers": COVER_WALLS,
        "pickups": list(weapon_pickups),
        "bullets": [
            {
                "id": bullet["id"],
                "x": bullet["x"],
                "y": bullet["y"],
                "weapon": bullet["weapon"],
            }
            for bullet in bullets
        ],
        "hits": list(hit_events),
    }
    hit_events.clear()
    for connection in active_connections.copy():
        try:
            await connection.send_json(message)
        except (WebSocketDisconnect, WebSocketDisconnected):
            if connection in active_connections:
                active_connections.remove(connection)


async def game_loop() -> None:
    """Advance the shared world and publish one snapshot at a fixed rate."""
    previous_tick_at = monotonic()
    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
        now = monotonic()
        elapsed = min(now - previous_tick_at, MAX_TICK_SECONDS)
        previous_tick_at = now

        for room in rooms.values():
            token = room_context.set(room)
            try:
                advance_round(now)
                remove_expired_disconnections(now)
                advance_respawns(now)
                advance_reloads(now)
                advance_melee_attacks(now)
                advance_fill_bot_ai(now)
                for player in players.values():
                    advance_player_movement(player, elapsed)
                advance_bullets(elapsed)

                if active_connections:
                    await broadcast_world_state()
                else:
                    hit_events.clear()
            finally:
                room_context.reset(token)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws/{room_code}")
async def game_socket(websocket: WebSocket, room_code: str) -> None:
    room = rooms.get(room_code.upper())
    if room is None:
        await websocket.accept()
        await websocket.send_json({"type": "room_not_found"})
        await websocket.close(code=1008)
        return

    token = room_context.set(room)
    player_id: str | None = None
    try:
        await websocket.accept()
        session_token = websocket.query_params.get("session")
        requested_name = sanitize_player_name(websocket.query_params.get("name"))
        existing_player = next(
            (
                player
                for player in players.values()
                if not player["is_bot"] and session_token and player["session_token"] == session_token
            ),
            None,
        )
        if existing_player:
            player_id = existing_player["id"]
            existing_player["connected"] = True
            existing_player["connection"] = websocket
            existing_player["disconnect_deadline"] = None
            if requested_name:
                existing_player["name"] = requested_name
        else:
            if not session_token or existing_player:
                session_token = uuid4().hex
            if len(players) >= MAX_PLAYERS:
                remove_one_fill_bot()
                if len(players) >= MAX_PLAYERS:
                    await websocket.send_json({"type": "room_full", "max_players": MAX_PLAYERS})
                    await websocket.close(code=1013)
                    return

            player_id = uuid4().hex
            player_number = len(players)
            players[player_id] = {
                "id": player_id,
                "x": 1280 + player_number * 60,
                "y": 720,
                "move_x": 0.0,
                "move_y": 0.0,
                "last_fire_at": float("-inf"),
                "last_melee_at": float("-inf"),
                "melee_started_at": None,
                "melee_ends_at": None,
                "melee_angle": 0.0,
                "weapon": DEFAULT_WEAPON,
                "melee_weapon": DEFAULT_WEAPON,
                "gun_weapon": None,
                "ammo_in_mag": 0,
                "magazine_capacity": 0,
                "reload_ends_at": None,
                "hp": PLAYER_MAX_HP,
                "alive": True,
                "respawn_at": None,
                "invulnerable_until": monotonic() + SPAWN_PROTECTION_SECONDS,
                "damage_dealt": 0.0,
                "kills": 0,
                "connected": True,
                "connection": websocket,
                "session_token": session_token,
                "disconnect_deadline": None,
                "is_bot": False,
                "owner_id": None,
                "name": requested_name,
            }

            if current_room()["host_player_id"] is None:
                current_room()["host_player_id"] = player_id

            rebalance_fill_bots()

        active_connections.append(websocket)

        await websocket.send_json(
            {
                "type": "server_connected",
                "player_id": player_id,
                "session_token": session_token,
                "server_time": monotonic(),
            }
        )
        advance_round(monotonic())
        await broadcast_world_state()

        while True:
            message: dict[str, Any] = await websocket.receive_json()
            if message.get("type") == "ping":
                await websocket.send_json(
                    {
                        "type": "pong",
                        "client_sent_at": message.get("client_sent_at"),
                    }
                )
                continue

            if message.get("type") == "move_intent":
                apply_move_intent(players[player_id], message)
                continue

            if message.get("type") == "fire_intent":
                fire_weapon(players[player_id], message)
                continue

            if message.get("type") == "melee_intent":
                attack_with_melee(players[player_id], message)
                continue

            if message.get("type") == "switch_weapon":
                if switch_weapon(players[player_id]):
                    await broadcast_world_state()
                continue

            if message.get("type") == "reload_intent":
                reload_weapon(players[player_id])
                continue

            if message.get("type") == "pickup_intent":
                collect_weapon_pickup(players[player_id])
                continue

            if message.get("type") == "add_ai_bot":
                if add_fill_bot(player_id):
                    await broadcast_world_state()
                continue

            if message.get("type") == "start_match":
                if request_match_start(player_id):
                    advance_round(monotonic())
                    await broadcast_world_state()
                continue

            if message.get("type") == "spawn_test_bot":
                if spawn_test_bot(player_id):
                    advance_round(monotonic())
                    await broadcast_world_state()
                continue

            if message.get("type") == "debug_respawn_bot":
                if respawn_test_bot(player_id, message):
                    await broadcast_world_state()
                continue

            if message.get("type") == "debug_reset_weapon_pickups":
                reset_weapon_pickups()
                await broadcast_world_state()
                continue

            if message.get("type") == "debug_reset_test_round":
                reset_test_round()
                await broadcast_world_state()
                continue

            if message.get("type") == "debug_collect_pickup":
                if move_test_bot_to_pickup(player_id, message):
                    await broadcast_world_state()
                continue

            if message.get("type") == "debug_move_bot":
                if move_test_bot(player_id, message):
                    await broadcast_world_state()
                continue

            await websocket.send_json(
                {
                    "type": "message_received",
                    "original_type": message.get("type", "unknown"),
                    "server_time": monotonic(),
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in active_connections:
            active_connections.remove(websocket)
        player = players.get(player_id) if player_id else None
        if player and player["connection"] is websocket:
            player["connected"] = False
            player["connection"] = None
            player["disconnect_deadline"] = monotonic() + RECONNECT_GRACE_SECONDS
            await broadcast_world_state()
        room_context.reset(token)
