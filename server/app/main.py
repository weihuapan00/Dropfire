import asyncio
from collections.abc import MutableMapping, MutableSequence
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from math import atan2, hypot, isfinite
from random import uniform
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
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

rooms: dict[str, dict[str, Any]] = {}
room_context: ContextVar[dict[str, Any] | None] = ContextVar("room_context", default=None)


def current_room() -> dict[str, Any]:
    """Return the room state bound to this WebSocket handler or game-loop iteration."""
    room = room_context.get()
    if room is None:
        raise RuntimeError("Room state was accessed outside a room context.")
    return room


class RoomMapping(MutableMapping[str, Any]):
    """Expose a room-owned dictionary to the existing authoritative game rules."""

    def __init__(self, key: str) -> None:
        self.key = key

    def value(self) -> dict[str, Any]:
        return current_room()[self.key]

    def __getitem__(self, key: str) -> Any:
        return self.value()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.value()[key] = value

    def __delitem__(self, key: str) -> None:
        del self.value()[key]

    def __iter__(self):
        return iter(self.value())

    def __len__(self) -> int:
        return len(self.value())

    def copy(self) -> dict[str, Any]:
        return self.value().copy()


class RoomList(MutableSequence[Any]):
    """Expose a room-owned list to the existing authoritative game rules."""

    def __init__(self, key: str) -> None:
        self.key = key

    def value(self) -> list[Any]:
        return current_room()[self.key]

    def __getitem__(self, index: Any) -> Any:
        return self.value()[index]

    def __setitem__(self, index: Any, value: Any) -> None:
        self.value()[index] = value

    def __delitem__(self, index: Any) -> None:
        del self.value()[index]

    def __len__(self) -> int:
        return len(self.value())

    def insert(self, index: int, value: Any) -> None:
        self.value().insert(index, value)

    def copy(self) -> list[Any]:
        return self.value().copy()


active_connections: MutableSequence[WebSocket] = RoomList("active_connections")
players: MutableMapping[str, dict[str, Any]] = RoomMapping("players")
bullets: MutableSequence[dict[str, Any]] = RoomList("bullets")
weapon_pickups: MutableSequence[dict[str, Any]]
round_state: MutableMapping[str, Any] = RoomMapping("round_state")
MAX_PLAYERS = 8
BOT_PREFERRED_RANGES = {"knife": 70.0, "pistol": 330.0, "rifle": 500.0}
BOT_FIRE_RANGES = {"pistol": 500.0, "rifle": 1100.0}
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
COVER_WALLS = (
    {"id": "cover-center", "x": 1600.0, "y": 720.0, "width": 84.0, "height": 340.0},
    {"id": "cover-west", "x": 720.0, "y": 920.0, "width": 320.0, "height": 64.0},
    {"id": "cover-east", "x": 1840.0, "y": 840.0, "width": 320.0, "height": 64.0},
)


def create_initial_weapon_pickups() -> list[dict[str, Any]]:
    """Create new pickup dictionaries so testing resets cannot mutate the blueprint."""
    return [
        {"id": pickup_id, "weapon": weapon, "x": x, "y": y}
        for pickup_id, weapon, x, y in INITIAL_WEAPON_PICKUPS
    ]


weapon_pickups = RoomList("weapon_pickups")
PLAYER_SPEED = 280.0
PLAYER_RADIUS = 20.0
PLAYER_MAX_HP = 100
PICKUP_RADIUS = 24.0
BULLET_RADIUS = 4.0
TEST_BOT_MOVE_DISTANCE = 48.0
ARENA_MIN_X = 72.0
ARENA_MAX_X = 2488.0
ARENA_MIN_Y = 72.0
ARENA_MAX_Y = 1368.0
TICK_RATE_HZ = 30
TICK_INTERVAL_SECONDS = 1 / TICK_RATE_HZ
MAX_TICK_SECONDS = 0.1
MIN_PLAYERS_TO_START_ROUND = 2
ROUND_END_DELAY_SECONDS = 4.0
RECONNECT_GRACE_SECONDS = 15.0
MATCH_DURATION_SECONDS = 180.0
RESPAWN_DELAY_SECONDS = 3.0
SPAWN_PROTECTION_SECONDS = 1.5
MIN_SPAWN_DISTANCE_FROM_ENEMY = 450.0
ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def create_room() -> str:
    """Create an empty room with fully isolated authoritative game state."""
    while True:
        code = "".join(ROOM_CODE_ALPHABET[uuid4().int % len(ROOM_CODE_ALPHABET)] for _ in range(6))
        if code not in rooms:
            break
    rooms[code] = {
        "active_connections": [],
        "players": {},
        "bullets": [],
        "weapon_pickups": create_initial_weapon_pickups(),
        "host_player_id": None,
        "round_state": {
            "phase": "waiting",
            "number": 0,
            "winner_id": None,
            "ends_at": None,
            "start_requested": False,
        },
    }
    return code


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
    }
    for connection in active_connections.copy():
        try:
            await connection.send_json(message)
        except (WebSocketDisconnect, WebSocketDisconnected):
            if connection in active_connections:
                active_connections.remove(connection)


def apply_move_intent(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Store one validated direction for the authoritative game loop to use."""
    if not player["alive"] or not player["connected"] or not round_is_active():
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
    candidate_x = max(ARENA_MIN_X, min(ARENA_MAX_X, player["x"] + player["move_x"] * distance))
    if not position_hits_cover(candidate_x, player["y"], PLAYER_RADIUS):
        player["x"] = candidate_x

    candidate_y = max(ARENA_MIN_Y, min(ARENA_MAX_Y, player["y"] + player["move_y"] * distance))
    if not position_hits_cover(player["x"], candidate_y, PLAYER_RADIUS):
        player["y"] = candidate_y
    return previous_position != (player["x"], player["y"])


def fire_weapon(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Create one server-validated projectile for a ranged weapon."""
    if not player["alive"] or not player["connected"] or not round_is_active() or player["reload_ends_at"] is not None:
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
    if not player["alive"] or not player["connected"] or not round_is_active():
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
    if not player["alive"] or not player["connected"] or not round_is_active() or player["weapon"] != "knife":
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
        if target_id == player["id"] or not target["alive"] or not target["connected"]:
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
        apply_damage(closest_target, KNIFE_DAMAGE, player["id"])
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


def get_respawn_ends_in_seconds(player: dict[str, Any], now: float) -> float:
    """Return the remaining server-authoritative respawn delay for one player."""
    respawn_at = player["respawn_at"]
    return max(0.0, respawn_at - now) if isinstance(respawn_at, float) else 0.0


def get_spawn_protection_ends_in_seconds(player: dict[str, Any], now: float) -> float:
    """Return remaining server-controlled spawn protection for the HUD."""
    invulnerable_until = player["invulnerable_until"]
    return max(0.0, invulnerable_until - now) if isinstance(invulnerable_until, float) else 0.0


def apply_damage(player: dict[str, Any], damage: float, attacker_id: str) -> bool:
    """Apply damage, then award damage and a kill using authoritative server state."""
    if not player["alive"] or not player["connected"]:
        return False
    if get_spawn_protection_ends_in_seconds(player, monotonic()) > 0:
        return False

    hp_before = player["hp"]
    player["hp"] = max(0, hp_before - damage)
    attacker = players.get(attacker_id)
    if attacker is not None and attacker_id != player["id"]:
        attacker["damage_dealt"] += hp_before - player["hp"]
    if player["hp"] == 0:
        player["alive"] = False
        player["move_x"] = 0.0
        player["move_y"] = 0.0
        player["reload_ends_at"] = None
        player["melee_ends_at"] = None
        player["respawn_at"] = monotonic() + RESPAWN_DELAY_SECONDS
        if attacker is not None and attacker_id != player["id"]:
            attacker["kills"] += 1
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

        if bullet_hits_cover(bullet):
            bullets.remove(bullet)
            continue

        for target_id, target in players.items():
            if target_id == bullet["owner_id"] or not target["alive"] or not target["connected"]:
                continue

            if hypot(bullet["x"] - target["x"], bullet["y"] - target["y"]) <= BULLET_RADIUS + PLAYER_RADIUS:
                apply_damage(target, bullet["damage"], bullet["owner_id"])
                bullets.remove(bullet)
                break


def bullet_hits_cover(bullet: dict[str, Any]) -> bool:
    """Return whether a bullet center has reached any static rectangular cover wall."""
    for cover in COVER_WALLS:
        half_width = cover["width"] / 2
        half_height = cover["height"] / 2
        if (
            cover["x"] - half_width <= bullet["x"] <= cover["x"] + half_width
            and cover["y"] - half_height <= bullet["y"] <= cover["y"] + half_height
        ):
            return True
    return False


def position_hits_cover(x: float, y: float, radius: float) -> bool:
    """Return whether a player's collision circle overlaps any rectangular cover wall."""
    for cover in COVER_WALLS:
        half_width = cover["width"] / 2
        half_height = cover["height"] / 2
        if (
            cover["x"] - half_width - radius <= x <= cover["x"] + half_width + radius
            and cover["y"] - half_height - radius <= y <= cover["y"] + half_height + radius
        ):
            return True
    return False


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
                advance_fill_bot_ai()
                for player in players.values():
                    advance_player_movement(player, elapsed)
                advance_bullets(elapsed)

                if active_connections:
                    await broadcast_world_state()
            finally:
                room_context.reset(token)


def collect_weapon_pickup(player: dict[str, Any]) -> bool:
    """Equip a nearby weapon after a server-validated pickup request."""
    if not player["alive"] or not player["connected"] or not round_is_active():
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


def reset_round_world() -> None:
    """Restore the battlefield for a fresh three-minute scoring period."""
    bullets.clear()
    reset_weapon_pickups()
    for player_number, player in enumerate(players.values()):
        respawn_player(player, player_number)
        player["damage_dealt"] = 0.0
        player["kills"] = 0


def find_spawn_position(excluded_player_id: str, fallback_number: int) -> tuple[float, float]:
    """Choose the safest random spawn: clear of walls and far from enemies."""
    safest_position: tuple[float, float] | None = None
    safest_distance = -1.0
    for _ in range(40):
        x = uniform(ARENA_MIN_X + PLAYER_RADIUS, ARENA_MAX_X - PLAYER_RADIUS)
        y = uniform(ARENA_MIN_Y + PLAYER_RADIUS, ARENA_MAX_Y - PLAYER_RADIUS)
        if position_hits_cover(x, y, PLAYER_RADIUS):
            continue
        enemy_distances = [
            hypot(x - player["x"], y - player["y"])
            for player_id, player in players.items()
            if player_id != excluded_player_id and player["alive"] and player["connected"]
        ]
        nearest_enemy_distance = min(enemy_distances, default=float("inf"))
        if nearest_enemy_distance > safest_distance:
            safest_position = (x, y)
            safest_distance = nearest_enemy_distance
    if safest_position is not None and safest_distance >= MIN_SPAWN_DISTANCE_FROM_ENEMY:
        return safest_position
    # A crowded map may have no ideal location; the farthest valid candidate is still safest.
    if safest_position is not None:
        return safest_position
    return 1120.0 + fallback_number * 75.0, 720.0


def respawn_player(player: dict[str, Any], player_number: int) -> None:
    """Restore one player at a random safe spawn for continuous deathmatch."""
    player["x"], player["y"] = find_spawn_position(player["id"], player_number)
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
    player["respawn_at"] = None
    player["invulnerable_until"] = monotonic() + SPAWN_PROTECTION_SECONDS


def advance_respawns(now: float) -> None:
    """Respawn eliminated, connected players after their short server timer."""
    for player_number, player in enumerate(players.values()):
        if (
            not player["alive"]
            and player["connected"]
            and isinstance(player["respawn_at"], float)
            and now >= player["respawn_at"]
        ):
            respawn_player(player, player_number)


def start_round(now: float) -> None:
    """Start a fresh three-minute, server-authoritative scoring period."""
    reset_round_world()
    round_state["phase"] = "active"
    round_state["number"] += 1
    round_state["winner_id"] = None
    round_state["ends_at"] = now + MATCH_DURATION_SECONDS


def reset_test_round() -> None:
    """Restart the current local-development scoring period immediately."""
    start_round(monotonic())


def round_is_active() -> bool:
    """Return whether game actions are currently permitted."""
    return round_state["phase"] == "active"


def get_round_snapshot(now: float) -> dict[str, Any]:
    """Build the client-visible round status from server-owned state."""
    ends_at = round_state["ends_at"]
    remaining_seconds = max(0.0, ends_at - now) if isinstance(ends_at, float) else 0.0
    return {
        "phase": round_state["phase"],
        "number": round_state["number"],
        "winner_id": round_state["winner_id"],
        "ends_in_seconds": remaining_seconds,
    }


def advance_round(now: float) -> None:
    """Advance a manually started three-minute deathmatch clock."""
    if round_state["phase"] == "waiting":
        if round_state["start_requested"] and len(players) >= MIN_PLAYERS_TO_START_ROUND:
            start_round(now)
        return

    if round_state["phase"] == "active":
        ends_at = round_state["ends_at"]
        if isinstance(ends_at, float) and now >= ends_at:
            start_round(now)


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
        "respawn_at": None,
        "invulnerable_until": monotonic() + SPAWN_PROTECTION_SECONDS,
        "damage_dealt": 0.0,
        "kills": 0,
        "connected": True,
        "connection": None,
        "session_token": None,
        "disconnect_deadline": None,
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
    bot["respawn_at"] = None
    bot["invulnerable_until"] = monotonic() + SPAWN_PROTECTION_SECONDS
    bot["connected"] = True
    return True


def create_fill_bot() -> None:
    """Add one server-owned AI opponent at a random valid spawn position."""
    bot_id = f"fill-bot-{uuid4().hex[:6]}"
    x, y = find_spawn_position(bot_id, len(players))
    players[bot_id] = {
        "id": bot_id,
        "x": x,
        "y": y,
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
        "respawn_at": None,
        "invulnerable_until": monotonic() + SPAWN_PROTECTION_SECONDS,
        "damage_dealt": 0.0,
        "kills": 0,
        "connected": True,
        "connection": None,
        "session_token": None,
        "disconnect_deadline": None,
        "is_bot": True,
        "owner_id": None,
        "patrol_x": x,
        "patrol_y": y,
        "strafe_sign": 1.0 if uuid4().int % 2 else -1.0,
    }


def remove_one_fill_bot() -> bool:
    """Free one bot-filled slot so a real player can join the room."""
    fill_bot_id = next(
        (
            player_id
            for player_id, player in players.items()
            if player["is_bot"] and player["owner_id"] is None
        ),
        None,
    )
    if fill_bot_id is None:
        return False
    players.pop(fill_bot_id)
    return True


def rebalance_fill_bots() -> None:
    """Remove AI bots only after the final human leaves a room."""
    human_players = [player for player in players.values() if not player["is_bot"]]
    if not human_players:
        for player_id, player in players.copy().items():
            if player["is_bot"]:
                players.pop(player_id)
        current_room()["host_player_id"] = None
        round_state["phase"] = "waiting"
        round_state["winner_id"] = None
        round_state["ends_at"] = None
        round_state["start_requested"] = False
        return



def add_fill_bot(requester_id: str) -> bool:
    """Add one explicit lobby-selected AI opponent to a room with space."""
    requester = players.get(requester_id)
    if (
        requester is None
        or requester["is_bot"]
        or not requester["connected"]
        or requester_id != current_room()["host_player_id"]
        or len(players) >= MAX_PLAYERS
    ):
        return False
    create_fill_bot()
    return True


def request_match_start(requester_id: str) -> bool:
    """Allow a connected human to begin a lobby once it has two participants."""
    requester = players.get(requester_id)
    if (
        requester is None
        or requester["is_bot"]
        or not requester["connected"]
        or requester_id != current_room()["host_player_id"]
        or len(players) < MIN_PLAYERS_TO_START_ROUND
        or round_state["phase"] != "waiting"
    ):
        return False
    round_state["start_requested"] = True
    return True


def set_bot_move_direction(bot: dict[str, Any], destination_x: float, destination_y: float) -> float:
    """Point a bot at a destination and return the remaining distance."""
    direction_x = destination_x - bot["x"]
    direction_y = destination_y - bot["y"]
    distance = hypot(direction_x, direction_y)
    if distance == 0:
        bot["move_x"] = 0.0
        bot["move_y"] = 0.0
        return 0.0
    bot["move_x"] = direction_x / distance
    bot["move_y"] = direction_y / distance
    look_ahead_x = bot["x"] + bot["move_x"] * PLAYER_RADIUS * 2
    look_ahead_y = bot["y"] + bot["move_y"] * PLAYER_RADIUS * 2
    if position_hits_cover(look_ahead_x, look_ahead_y, PLAYER_RADIUS):
        strafe_sign = float(bot.get("strafe_sign", 1.0))
        bot["move_x"] = -direction_y / distance * strafe_sign
        bot["move_y"] = direction_x / distance * strafe_sign
    return distance


def choose_bot_patrol_destination(bot: dict[str, Any]) -> None:
    """Pick a valid idle destination so bots keep moving between engagements."""
    for _ in range(20):
        x = uniform(ARENA_MIN_X + PLAYER_RADIUS, ARENA_MAX_X - PLAYER_RADIUS)
        y = uniform(ARENA_MIN_Y + PLAYER_RADIUS, ARENA_MAX_Y - PLAYER_RADIUS)
        if not position_hits_cover(x, y, PLAYER_RADIUS):
            bot["patrol_x"] = x
            bot["patrol_y"] = y
            return


def spread_bot_from_nearby_bots(bot: dict[str, Any]) -> None:
    """Add a small separation force so AI opponents do not form one stack."""
    separation_x = 0.0
    separation_y = 0.0
    for other in players.values():
        if other is bot or not other["is_bot"] or not other["alive"]:
            continue
        offset_x = bot["x"] - other["x"]
        offset_y = bot["y"] - other["y"]
        distance = hypot(offset_x, offset_y)
        if 0 < distance < 170:
            separation_x += offset_x / distance * (1 - distance / 170)
            separation_y += offset_y / distance * (1 - distance / 170)
    combined_x = bot["move_x"] + separation_x * 1.3
    combined_y = bot["move_y"] + separation_y * 1.3
    combined_length = hypot(combined_x, combined_y)
    if combined_length > 0:
        bot["move_x"] = combined_x / combined_length
        bot["move_y"] = combined_y / combined_length


def advance_fill_bot_ai() -> None:
    """Run a small server-authoritative combat loop for automatic practice bots."""
    if not round_is_active():
        for bot in players.values():
            if bot["is_bot"] and bot["owner_id"] is None:
                bot["move_x"] = 0.0
                bot["move_y"] = 0.0
        return

    for bot in players.values():
        if not bot["is_bot"] or bot["owner_id"] is not None or not bot["alive"]:
            continue

        targets = [
            player
            for player in players.values()
            if not player["is_bot"] and player["alive"] and player["connected"]
        ]
        if not targets:
            patrol_x = float(bot.get("patrol_x", bot["x"]))
            patrol_y = float(bot.get("patrol_y", bot["y"]))
            if set_bot_move_direction(bot, patrol_x, patrol_y) < 60:
                choose_bot_patrol_destination(bot)
            continue

        target = min(targets, key=lambda player: hypot(player["x"] - bot["x"], player["y"] - bot["y"]))

        if bot["weapon"] == "fists":
            ranged_pickups = [pickup for pickup in weapon_pickups if pickup["weapon"] in RANGED_WEAPON_SETTINGS]
            pickup_choices = ranged_pickups or list(weapon_pickups)
            if pickup_choices:
                pickup = min(
                    pickup_choices,
                    key=lambda item: hypot(item["x"] - bot["x"], item["y"] - bot["y"]),
                )
                pickup_distance = set_bot_move_direction(bot, pickup["x"], pickup["y"])
                if pickup_distance <= PLAYER_RADIUS + PICKUP_RADIUS:
                    collect_weapon_pickup(bot)
                continue

        distance_to_target = set_bot_move_direction(bot, target["x"], target["y"])
        direction_x = target["x"] - bot["x"]
        direction_y = target["y"] - bot["y"]
        preferred_range = BOT_PREFERRED_RANGES.get(bot["weapon"], 240.0)

        if distance_to_target <= preferred_range:
            # Strafe instead of walking directly into the target once close enough.
            strafe_sign = float(bot.get("strafe_sign", 1.0))
            bot["move_x"] = -direction_y / max(distance_to_target, 1.0) * strafe_sign
            bot["move_y"] = direction_x / max(distance_to_target, 1.0) * strafe_sign

        spread_bot_from_nearby_bots(bot)

        if bot["weapon"] == "knife" and distance_to_target <= KNIFE_REACH:
            attack_with_knife(bot, {"direction_x": direction_x, "direction_y": direction_y})
        elif bot["weapon"] in BOT_FIRE_RANGES:
            if bot["ammo_in_mag"] <= 0:
                reload_weapon(bot)
            elif distance_to_target <= BOT_FIRE_RANGES[bot["weapon"]]:
                fire_weapon(bot, {"direction_x": direction_x, "direction_y": direction_y})


def remove_expired_disconnections(now: float) -> None:
    """Remove human players only after their reconnect grace period expires."""
    expired_player_ids = [
        player_id
        for player_id, player in players.items()
        if not player["is_bot"]
        and not player["connected"]
        and isinstance(player["disconnect_deadline"], float)
        and now >= player["disconnect_deadline"]
    ]
    for player_id in expired_player_ids:
        players.pop(player_id)
    if expired_player_ids:
        if current_room()["host_player_id"] in expired_player_ids:
            current_room()["host_player_id"] = next(
                (player_id for player_id, player in players.items() if not player["is_bot"]),
                None,
            )
        rebalance_fill_bots()
        advance_round(now)


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
        "weapon": "fists",
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
                attack_with_knife(players[player_id], message)
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

