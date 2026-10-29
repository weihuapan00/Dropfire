import asyncio
from contextlib import asynccontextmanager, suppress
from math import atan2, hypot, isfinite
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketDisconnected


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
bullets: list[dict[str, Any]] = []
MAX_PLAYERS = 4
WEAPON_TYPES = {"fists", "knife", "pistol", "rifle"}
RANGED_WEAPON_SETTINGS: dict[str, dict[str, float]] = {
    "pistol": {
        "damage": 25.0,
        "bullet_speed": 720.0,
        "bullet_lifetime_seconds": 0.75,
        "cooldown_seconds": 0.35,
    },
    "rifle": {
        "damage": 15.0,
        "bullet_speed": 1080.0,
        "bullet_lifetime_seconds": 1.75,
        "cooldown_seconds": 0.12,
    },
}
MAGAZINE_CAPACITIES = {"pistol": 12, "rifle": 30}
RELOAD_DURATION_SECONDS = 1.2
KNIFE_DAMAGE = 100.0
KNIFE_REACH = 88.0
KNIFE_MINIMUM_DOT_PRODUCT = 0.45
KNIFE_COOLDOWN_SECONDS = 0.65
MELEE_ATTACK_DURATION_SECONDS = 0.18
INITIAL_WEAPON_PICKUPS = (
    ("knife-1", "knife", 760.0, 400.0),
    ("pistol-1", "pistol", 1850.0, 460.0),
    ("rifle-1", "rifle", 1350.0, 1060.0),
)


def create_initial_weapon_pickups() -> list[dict[str, Any]]:
    """Create new pickup dictionaries so testing resets cannot mutate the blueprint."""
    return [
        {"id": pickup_id, "weapon": weapon, "x": x, "y": y}
        for pickup_id, weapon, x, y in INITIAL_WEAPON_PICKUPS
    ]


weapon_pickups = create_initial_weapon_pickups()
PLAYER_SPEED = 280.0
PLAYER_RADIUS = 20.0
PLAYER_MAX_HP = 100
PICKUP_RADIUS = 24.0
BULLET_RADIUS = 6.0
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
    now = monotonic()
    message = {
        "type": "world_state",
        "players": [
            {
                "id": player_id,
                "x": player["x"],
                "y": player["y"],
                "weapon": player["weapon"],
                "ammo_in_mag": player["ammo_in_mag"],
                "magazine_capacity": player["magazine_capacity"],
                "reload_progress": get_reload_progress(player, now),
                "melee_progress": get_melee_progress(player, now),
                "melee_angle": player["melee_angle"],
                "hp": player["hp"],
                "alive": player["alive"],
                "is_bot": player["is_bot"],
                "owner_id": player["owner_id"],
            }
            for player_id, player in players.items()
        ],
        "pickups": weapon_pickups,
        "bullets": [
            {
                "id": bullet["id"],
                "x": bullet["x"],
                "y": bullet["y"],
                "weapon": bullet["weapon"],
            }
            for bullet in bullets
        ],
    }
    for connection in active_connections.copy():
        try:
            await connection.send_json(message)
        except (WebSocketDisconnect, WebSocketDisconnected):
            if connection in active_connections:
                active_connections.remove(connection)


def apply_move_intent(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Store one validated direction for the authoritative game loop to use."""
    if not player["alive"]:
        return False

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
    if not player["alive"] or (player["move_x"] == 0 and player["move_y"] == 0):
        return False

    distance = PLAYER_SPEED * elapsed
    previous_position = (player["x"], player["y"])
    player["x"] = max(ARENA_MIN_X, min(ARENA_MAX_X, player["x"] + player["move_x"] * distance))
    player["y"] = max(ARENA_MIN_Y, min(ARENA_MAX_Y, player["y"] + player["move_y"] * distance))
    return previous_position != (player["x"], player["y"])


def fire_weapon(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Create one server-validated projectile for a ranged weapon."""
    if not player["alive"] or player["reload_ends_at"] is not None:
        return False

    direction_x = message.get("direction_x")
    direction_y = message.get("direction_y")
    if (
        not isinstance(direction_x, (int, float))
        or not isinstance(direction_y, (int, float))
        or not isfinite(direction_x)
        or not isfinite(direction_y)
    ):
        return False

    settings = RANGED_WEAPON_SETTINGS.get(player["weapon"])
    direction_length = hypot(direction_x, direction_y)
    if not settings or direction_length == 0 or player["ammo_in_mag"] <= 0:
        return False

    now = monotonic()
    if now - player["last_fire_at"] < settings["cooldown_seconds"]:
        return False

    normalized_x = direction_x / direction_length
    normalized_y = direction_y / direction_length
    start_distance = PLAYER_RADIUS + BULLET_RADIUS
    bullets.append(
        {
            "id": f"bullet-{uuid4().hex[:8]}",
            "owner_id": player["id"],
            "weapon": player["weapon"],
            "damage": settings["damage"],
            "x": player["x"] + normalized_x * start_distance,
            "y": player["y"] + normalized_y * start_distance,
            "velocity_x": normalized_x * settings["bullet_speed"],
            "velocity_y": normalized_y * settings["bullet_speed"],
            "remaining_seconds": settings["bullet_lifetime_seconds"],
        }
    )
    player["last_fire_at"] = now
    player["ammo_in_mag"] -= 1
    return True


def reload_weapon(player: dict[str, Any]) -> bool:
    """Start a delayed reload for a living player with a partly empty gun."""
    if not player["alive"]:
        return False

    magazine_capacity = MAGAZINE_CAPACITIES.get(player["weapon"])
    if (
        magazine_capacity is None
        or player["ammo_in_mag"] >= magazine_capacity
        or player["reload_ends_at"] is not None
    ):
        return False

    player["reload_ends_at"] = monotonic() + RELOAD_DURATION_SECONDS
    return True


def attack_with_knife(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Perform one server-validated knife swing and damage the closest target in its arc."""
    if not player["alive"] or player["weapon"] != "knife":
        return False

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
        return False

    now = monotonic()
    if now - player["last_melee_at"] < KNIFE_COOLDOWN_SECONDS:
        return False

    normalized_x = direction_x / direction_length
    normalized_y = direction_y / direction_length
    player["last_melee_at"] = now
    player["melee_started_at"] = now
    player["melee_ends_at"] = now + MELEE_ATTACK_DURATION_SECONDS
    player["melee_angle"] = atan2(normalized_y, normalized_x)

    closest_target: dict[str, Any] | None = None
    closest_distance = KNIFE_REACH
    for target_id, target in players.items():
        if target_id == player["id"] or not target["alive"]:
            continue

        offset_x = target["x"] - player["x"]
        offset_y = target["y"] - player["y"]
        distance = hypot(offset_x, offset_y)
        if distance == 0 or distance > closest_distance:
            continue

        dot_product = normalized_x * offset_x / distance + normalized_y * offset_y / distance
        if dot_product >= KNIFE_MINIMUM_DOT_PRODUCT:
            closest_target = target
            closest_distance = distance

    if closest_target:
        apply_damage(closest_target, KNIFE_DAMAGE)
    return True


def get_reload_progress(player: dict[str, Any], now: float) -> float:
    """Return a normalized 0-to-1 reload progress for the client animation."""
    reload_ends_at = player["reload_ends_at"]
    if reload_ends_at is None:
        return 0.0
    return max(0.0, min(1.0, 1 - (reload_ends_at - now) / RELOAD_DURATION_SECONDS))


def get_melee_progress(player: dict[str, Any], now: float) -> float:
    """Return a normalized animation progress while the current melee swing is active."""
    melee_ends_at = player["melee_ends_at"]
    if melee_ends_at is None:
        return 0.0
    return max(0.0, min(1.0, 1 - (melee_ends_at - now) / MELEE_ATTACK_DURATION_SECONDS))


def advance_reloads(now: float) -> None:
    """Complete every reload whose server-controlled finish time has arrived."""
    for player in players.values():
        reload_ends_at = player["reload_ends_at"]
        if reload_ends_at is None or now < reload_ends_at:
            continue

        magazine_capacity = MAGAZINE_CAPACITIES.get(player["weapon"])
        if player["alive"] and magazine_capacity is not None:
            player["magazine_capacity"] = magazine_capacity
            player["ammo_in_mag"] = magazine_capacity
        player["reload_ends_at"] = None


def advance_melee_attacks(now: float) -> None:
    """Clear finished melee animation state after the server has published it."""
    for player in players.values():
        melee_ends_at = player["melee_ends_at"]
        if melee_ends_at is not None and now >= melee_ends_at:
            player["melee_ends_at"] = None


def apply_damage(player: dict[str, Any], damage: float) -> bool:
    """Apply server-authoritative damage and eliminate a player at zero HP."""
    if not player["alive"]:
        return False

    player["hp"] = max(0, player["hp"] - damage)
    if player["hp"] == 0:
        player["alive"] = False
        player["move_x"] = 0.0
        player["move_y"] = 0.0
        player["reload_ends_at"] = None
        player["melee_ends_at"] = None
    return True


def advance_bullets(elapsed: float) -> None:
    """Advance every projectile and remove bullets that leave the playable world."""
    for bullet in bullets.copy():
        bullet["x"] += bullet["velocity_x"] * elapsed
        bullet["y"] += bullet["velocity_y"] * elapsed
        bullet["remaining_seconds"] -= elapsed
        outside_arena = (
            bullet["x"] < ARENA_MIN_X
            or bullet["x"] > ARENA_MAX_X
            or bullet["y"] < ARENA_MIN_Y
            or bullet["y"] > ARENA_MAX_Y
        )
        if bullet["remaining_seconds"] <= 0 or outside_arena:
            bullets.remove(bullet)
            continue

        for target_id, target in players.items():
            if target_id == bullet["owner_id"] or not target["alive"]:
                continue

            if hypot(bullet["x"] - target["x"], bullet["y"] - target["y"]) <= BULLET_RADIUS + PLAYER_RADIUS:
                apply_damage(target, bullet["damage"])
                bullets.remove(bullet)
                break


async def game_loop() -> None:
    """Advance the shared world and publish one snapshot at a fixed rate."""
    previous_tick_at = monotonic()
    while True:
        await asyncio.sleep(TICK_INTERVAL_SECONDS)
        now = monotonic()
        elapsed = min(now - previous_tick_at, MAX_TICK_SECONDS)
        previous_tick_at = now

        advance_reloads(now)
        advance_melee_attacks(now)
        for player in players.values():
            advance_player_movement(player, elapsed)
        advance_bullets(elapsed)

        if active_connections:
            await broadcast_world_state()


def collect_weapon_pickup(player: dict[str, Any]) -> bool:
    """Equip a nearby weapon after a server-validated pickup request."""
    if not player["alive"]:
        return False

    for pickup in weapon_pickups.copy():
        distance_to_pickup = hypot(player["x"] - pickup["x"], player["y"] - pickup["y"])
        if distance_to_pickup <= PLAYER_RADIUS + PICKUP_RADIUS:
            player["weapon"] = pickup["weapon"]
            player["magazine_capacity"] = MAGAZINE_CAPACITIES.get(pickup["weapon"], 0)
            player["ammo_in_mag"] = player["magazine_capacity"]
            player["reload_ends_at"] = None
            weapon_pickups.remove(pickup)
            return True

    return False


def reset_weapon_pickups() -> None:
    """Restore every map weapon for the local development test panel."""
    weapon_pickups.clear()
    weapon_pickups.extend(create_initial_weapon_pickups())


def reset_test_round() -> None:
    """Restore the shared local-development world to a fresh round state."""
    bullets.clear()
    reset_weapon_pickups()
    for player_number, player in enumerate(players.values()):
        player["x"] = 1180.0 + player_number * 75.0
        player["y"] = 720.0
        player["move_x"] = 0.0
        player["move_y"] = 0.0
        player["last_fire_at"] = float("-inf")
        player["last_melee_at"] = float("-inf")
        player["melee_started_at"] = None
        player["melee_ends_at"] = None
        player["melee_angle"] = 0.0
        player["weapon"] = "fists"
        player["ammo_in_mag"] = 0
        player["magazine_capacity"] = 0
        player["reload_ends_at"] = None
        player["hp"] = PLAYER_MAX_HP
        player["alive"] = True


def spawn_test_bot(owner_id: str) -> bool:
    """Create a server-owned test player that only its creator can control."""
    if len(players) >= MAX_PLAYERS:
        return False

    bot_number = sum(player["is_bot"] for player in players.values()) + 1
    bot_id = f"test-bot-{uuid4().hex[:6]}"
    players[bot_id] = {
        "id": bot_id,
        "x": 1180.0 + bot_number * 45,
        "y": 720.0,
        "move_x": 0.0,
        "move_y": 0.0,
        "last_fire_at": float("-inf"),
        "last_melee_at": float("-inf"),
        "melee_started_at": None,
        "melee_ends_at": None,
        "melee_angle": 0.0,
        "weapon": "fists",
        "ammo_in_mag": 0,
        "magazine_capacity": 0,
        "reload_ends_at": None,
        "hp": PLAYER_MAX_HP,
        "alive": True,
        "is_bot": True,
        "owner_id": owner_id,
    }
    return True


def respawn_test_bot(owner_id: str, message: dict[str, Any]) -> bool:
    """Reset one owned test bot so local development can continue after elimination."""
    bot_id = message.get("player_id")
    if not isinstance(bot_id, str):
        return False

    bot = players.get(bot_id)
    if not bot or not bot["is_bot"] or bot["owner_id"] != owner_id:
        return False

    bot["x"] = 1225.0
    bot["y"] = 720.0
    bot["move_x"] = 0.0
    bot["move_y"] = 0.0
    bot["last_fire_at"] = float("-inf")
    bot["last_melee_at"] = float("-inf")
    bot["melee_started_at"] = None
    bot["melee_ends_at"] = None
    bot["melee_angle"] = 0.0
    bot["weapon"] = "fists"
    bot["ammo_in_mag"] = 0
    bot["magazine_capacity"] = 0
    bot["reload_ends_at"] = None
    bot["hp"] = PLAYER_MAX_HP
    bot["alive"] = True
    return True


def move_test_bot_to_pickup(owner_id: str, message: dict[str, Any]) -> bool:
    """Teleport one owned test bot to an available pickup for fast integration tests."""
    bot_id = message.get("player_id")
    pickup_id = message.get("pickup_id")
    if not isinstance(bot_id, str) or not isinstance(pickup_id, str):
        return False

    bot = players.get(bot_id)
    pickup = next((item for item in weapon_pickups if item["id"] == pickup_id), None)
    if not bot or not bot["alive"] or not bot["is_bot"] or bot["owner_id"] != owner_id or not pickup:
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
    if not bot or not bot["alive"] or not bot["is_bot"] or bot["owner_id"] != owner_id or direction_length == 0:
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
        "weapon": "fists",
        "ammo_in_mag": 0,
        "magazine_capacity": 0,
        "reload_ends_at": None,
        "hp": PLAYER_MAX_HP,
        "alive": True,
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

            if message.get("type") == "fire_intent":
                fire_weapon(players[player_id], message)
                continue

            if message.get("type") == "melee_intent":
                attack_with_knife(players[player_id], message)
                continue

            if message.get("type") == "reload_intent":
                reload_weapon(players[player_id])
                continue

            if message.get("type") == "pickup_intent":
                collect_weapon_pickup(players[player_id])
                continue

            if message.get("type") == "spawn_test_bot":
                if spawn_test_bot(player_id):
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
        players.pop(player_id, None)
        await broadcast_world_state()

