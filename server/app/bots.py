"""AI opponents, test bots, and disconnected-player lifecycle helpers."""

from math import hypot
from random import uniform
from time import monotonic
from typing import Any
from uuid import uuid4

from .config import (
    ARENA_MAX_X,
    ARENA_MAX_Y,
    ARENA_MIN_X,
    ARENA_MIN_Y,
    BOT_FIRE_RANGES,
    BOT_PREFERRED_RANGES,
    DEFAULT_WEAPON,
    MAX_PLAYERS,
    MELEE_WEAPON_SETTINGS,
    PLAYER_MAX_HP,
    PLAYER_RADIUS,
    SPAWN_PROTECTION_SECONDS,
    TEST_BOT_MOVE_DISTANCE,
)
from .rules import (
    advance_round,
    equip_progression_weapon,
    attack_with_melee,
    collect_weapon_pickup,
    fire_weapon,
    find_spawn_position,
    position_hits_cover,
    reload_weapon,
    round_is_active,
)
from .state import current_room, players, round_state, weapon_pickups


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
        "connection": None,
        "session_token": None,
        "disconnect_deadline": None,
        "is_bot": True,
        "owner_id": owner_id,
    }
    equip_progression_weapon(players[bot_id])
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
    bot["weapon"] = DEFAULT_WEAPON
    bot["melee_weapon"] = DEFAULT_WEAPON
    bot["gun_weapon"] = None
    bot["ammo_in_mag"] = 0
    bot["magazine_capacity"] = 0
    bot["reload_ends_at"] = None
    bot["hp"] = PLAYER_MAX_HP
    bot["alive"] = True
    bot["respawn_at"] = None
    bot["invulnerable_until"] = monotonic() + SPAWN_PROTECTION_SECONDS
    bot["connected"] = True
    equip_progression_weapon(bot)
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
        "connection": None,
        "session_token": None,
        "disconnect_deadline": None,
        "is_bot": True,
        "owner_id": None,
        "patrol_x": x,
        "patrol_y": y,
        "strafe_sign": 1.0 if uuid4().int % 2 else -1.0,
    }
    equip_progression_weapon(players[bot_id])


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


def advance_fill_bot_ai(now: float) -> None:
    """Run a small server-authoritative combat loop for automatic practice bots."""
    if not round_is_active():
        for bot in players.values():
            if bot["is_bot"] and bot["owner_id"] is None:
                bot["move_x"] = 0.0
                bot["move_y"] = 0.0
        return

    for bot in players.values():
        if not round_is_active():
            break
        if not bot["is_bot"] or bot["owner_id"] is not None or not bot["alive"]:
            continue

        if now < float(bot.get("engage_after", 0.0)):
            patrol_x = float(bot.get("patrol_x", bot["x"]))
            patrol_y = float(bot.get("patrol_y", bot["y"]))
            if set_bot_move_direction(bot, patrol_x, patrol_y) < 60:
                choose_bot_patrol_destination(bot)
            continue

        targets = [
            player
            for player in players.values()
            if player["id"] != bot["id"] and player["alive"] and player["connected"]
        ]
        if not targets:
            patrol_x = float(bot.get("patrol_x", bot["x"]))
            patrol_y = float(bot.get("patrol_y", bot["y"]))
            if set_bot_move_direction(bot, patrol_x, patrol_y) < 60:
                choose_bot_patrol_destination(bot)
            continue

        target = min(targets, key=lambda player: hypot(player["x"] - bot["x"], player["y"] - bot["y"]))

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

        melee_settings = MELEE_WEAPON_SETTINGS.get(bot["weapon"])
        if melee_settings is not None and distance_to_target <= melee_settings["reach"]:
            attack_with_melee(bot, {"direction_x": direction_x, "direction_y": direction_y})
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
        if not any(not player["is_bot"] for player in players.values()):
            current_room()["should_close"] = True


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
