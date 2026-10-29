import asyncio
from contextlib import asynccontextmanager, suppress
from math import hypot, isfinite
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


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

active_connections: list[WebSocket] = []
players: dict[str, dict[str, Any]] = {}
MAX_PLAYERS = 4
WEAPON_TYPES = {"fists", "knife", "pistol", "rifle"}
weapon_pickups: list[dict[str, Any]] = [
    {"id": "knife-1", "weapon": "knife", "x": 760.0, "y": 400.0},
    {"id": "pistol-1", "weapon": "pistol", "x": 1850.0, "y": 460.0},
    {"id": "rifle-1", "weapon": "rifle", "x": 1350.0, "y": 1060.0},
]
PLAYER_SPEED = 280.0
PLAYER_RADIUS = 20.0
PICKUP_RADIUS = 24.0
TEST_BOT_MOVE_DISTANCE = 48.0
ARENA_MIN_X = 72.0
ARENA_MAX_X = 2488.0
ARENA_MIN_Y = 72.0
ARENA_MAX_Y = 1368.0
TICK_RATE_HZ = 30
TICK_INTERVAL_SECONDS = 1 / TICK_RATE_HZ
MAX_TICK_SECONDS = 0.1


async def broadcast_world_state() -> None:
    """Send the complete current player list to every connected browser."""
    message = {
        "type": "world_state",
        "players": [
            {
                "id": player_id,
                "x": player["x"],
                "y": player["y"],
                "weapon": player["weapon"],
                "is_bot": player["is_bot"],
                "owner_id": player["owner_id"],
            }
            for player_id, player in players.items()
        ],
        "pickups": weapon_pickups,
    }
    for connection in active_connections.copy():
        await connection.send_json(message)


def apply_move_intent(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Store one validated direction for the authoritative game loop to use."""
    direction_x = message.get("direction_x")
    direction_y = message.get("direction_y")
    if (
        not isinstance(direction_x, (int, float))
        or not isinstance(direction_y, (int, float))
        or not isfinite(direction_x)
        or not isfinite(direction_y)
    ):
        return False

    direction_length = hypot(direction_x, direction_y)
    if direction_length == 0:
        player["move_x"] = 0.0
        player["move_y"] = 0.0
        return True

    player["move_x"] = direction_x / direction_length
    player["move_y"] = direction_y / direction_length
    return True


def advance_player_movement(player: dict[str, Any], elapsed: float) -> bool:
    """Move one player for one server tick using its last valid input direction."""
    if player["move_x"] == 0 and player["move_y"] == 0:
        return False

    distance = PLAYER_SPEED * elapsed
    previous_position = (player["x"], player["y"])
    player["x"] = max(ARENA_MIN_X, min(ARENA_MAX_X, player["x"] + player["move_x"] * distance))
    player["y"] = max(ARENA_MIN_Y, min(ARENA_MAX_Y, player["y"] + player["move_y"] * distance))
    return previous_position != (player["x"], player["y"])


async def game_loop() -> None:
    """Advance the shared world and publish one snapshot at a fixed rate."""
    previous_tick_at = monotonic()
    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
        now = monotonic()
        elapsed = min(now - previous_tick_at, MAX_TICK_SECONDS)
        previous_tick_at = now

        for player in players.values():
            if advance_player_movement(player, elapsed):
                collect_weapon_pickup(player)

        if active_connections:
            await broadcast_world_state()


def collect_weapon_pickup(player: dict[str, Any]) -> bool:
    """Equip the first weapon pickup the player touches and remove it from the arena."""
    for pickup in weapon_pickups.copy():
        distance_to_pickup = hypot(player["x"] - pickup["x"], player["y"] - pickup["y"])
        if distance_to_pickup <= PLAYER_RADIUS + PICKUP_RADIUS:
            player["weapon"] = pickup["weapon"]
            weapon_pickups.remove(pickup)
            return True

    return False


def spawn_test_bot(owner_id: str) -> bool:
    """Create a server-owned test player that only its creator can control."""
    if len(players) >= MAX_PLAYERS:
        return False

    bot_number = sum(player["is_bot"] for player in players.values()) + 1
    bot_id = f"test-bot-{uuid4().hex[:6]}"
    players[bot_id] = {
        "x": 1180.0 + bot_number * 45,
        "y": 720.0,
        "move_x": 0.0,
        "move_y": 0.0,
        "weapon": "fists",
        "is_bot": True,
        "owner_id": owner_id,
    }
    return True


def move_test_bot_to_pickup(owner_id: str, message: dict[str, Any]) -> bool:
    """Teleport one owned test bot to an available pickup for fast integration tests."""
    bot_id = message.get("player_id")
    pickup_id = message.get("pickup_id")
    if not isinstance(bot_id, str) or not isinstance(pickup_id, str):
        return False

    bot = players.get(bot_id)
    pickup = next((item for item in weapon_pickups if item["id"] == pickup_id), None)
    if not bot or not bot["is_bot"] or bot["owner_id"] != owner_id or not pickup:
        return False

    bot["x"] = pickup["x"]
    bot["y"] = pickup["y"]
    return collect_weapon_pickup(bot)


def move_test_bot(owner_id: str, message: dict[str, Any]) -> bool:
    """Move one owned test bot by a fixed server-validated step."""
    bot_id = message.get("player_id")
    direction_x = message.get("direction_x")
    direction_y = message.get("direction_y")
    if (
        not isinstance(bot_id, str)
        or not isinstance(direction_x, (int, float))
        or not isinstance(direction_y, (int, float))
    ):
        return False

    bot = players.get(bot_id)
    direction_length = hypot(direction_x, direction_y)
    if not bot or not bot["is_bot"] or bot["owner_id"] != owner_id or direction_length == 0:
        return False

    bot["x"] = max(
        ARENA_MIN_X,
        min(ARENA_MAX_X, bot["x"] + direction_x / direction_length * TEST_BOT_MOVE_DISTANCE),
    )
    bot["y"] = max(
        ARENA_MIN_Y,
        min(ARENA_MAX_Y, bot["y"] + direction_y / direction_length * TEST_BOT_MOVE_DISTANCE),
    )
    collect_weapon_pickup(bot)
    return True


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def game_socket(websocket: WebSocket) -> None:
    player_id = uuid4().hex
    await websocket.accept()
    if len(players) >= MAX_PLAYERS:
        await websocket.send_json({"type": "room_full", "max_players": MAX_PLAYERS})
        await websocket.close(code=1013)
        return

    active_connections.append(websocket)
    player_number = len(players)
    players[player_id] = {
        "x": 1280 + player_number * 60,
        "y": 720,
        "move_x": 0.0,
        "move_y": 0.0,
        "weapon": "fists",
        "is_bot": False,
        "owner_id": None,
    }

    await websocket.send_json(
        {
            "type": "server_connected",
            "player_id": player_id,
            "server_time": monotonic(),
        }
    )
    await broadcast_world_state()

    try:
        while True:
            message: dict[str, Any] = await websocket.receive_json()
            if message.get("type") == "move_intent":
                apply_move_intent(players[player_id], message)
                continue

            if message.get("type") == "spawn_test_bot":
                if spawn_test_bot(player_id):
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
        active_connections.remove(websocket)
        players.pop(player_id, None)
        await broadcast_world_state()

