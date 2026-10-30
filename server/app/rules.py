"""Authoritative game rules: movement, weapons, bullets, damage, and rounds.

These functions read and mutate the room-scoped proxies from ``state``, so they
must run inside a room context (set by the game loop or a WebSocket handler).
"""

from math import atan2, cos, hypot, isfinite, sin
from random import shuffle
from time import monotonic
from typing import Any
from uuid import uuid4

from .config import (
    ARENA_MAX_X,
    ARENA_MAX_Y,
    ARENA_MIN_X,
    ARENA_MIN_Y,
    BULLET_RADIUS,
    COVER_WALLS,
    DEFAULT_WEAPON,
    KNIFE_BLOCK_MINIMUM_DOT_PRODUCT,
    KNIFE_BLOCK_REACH,
    KNIFE_SPEED_MULTIPLIER,
    MAGAZINE_CAPACITIES,
    MATCH_DURATION_SECONDS,
    MELEE_WEAPON_SETTINGS,
    MIN_PLAYERS_TO_START_ROUND,
    MIN_SPAWN_DISTANCE_FROM_ENEMY,
    PICKUP_RADIUS,
    PLAYER_MAX_HP,
    PLAYER_RADIUS,
    PLAYER_SPEED,
    RANGED_WEAPON_SETTINGS,
    RELOAD_DURATION_SECONDS,
    RESPAWN_DELAY_SECONDS,
    ROUND_END_DELAY_SECONDS,
    SPAWN_POINTS,
    SPAWN_PROTECTION_SECONDS,
)
from .state import (
    bullets,
    create_initial_weapon_pickups,
    current_room,
    hit_events,
    players,
    round_state,
    weapon_pickups,
)


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

    speed = PLAYER_SPEED * (KNIFE_SPEED_MULTIPLIER if player["weapon"] == "knife" else 1.0)
    distance = speed * elapsed
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


def attack_with_melee(player: dict[str, Any], message: dict[str, Any]) -> bool:
    """Perform one server-validated melee swing and damage the closest target in its arc."""
    melee_settings = MELEE_WEAPON_SETTINGS.get(player["weapon"])
    if (
        melee_settings is None
        or not player["alive"]
        or not player["connected"]
        or not round_is_active()
    ):
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
    if now - player["last_melee_at"] < melee_settings["cooldown_seconds"]:
        return False

    normalized_x = direction_x / direction_length
    normalized_y = direction_y / direction_length
    player["last_melee_at"] = now
    player["melee_started_at"] = now
    player["melee_ends_at"] = now + melee_settings["attack_duration_seconds"]
    player["melee_angle"] = atan2(normalized_y, normalized_x)

    closest_target: dict[str, Any] | None = None
    closest_distance = melee_settings["reach"]
    for target_id, target in players.items():
        if target_id == player["id"] or not target["alive"] or not target["connected"]:
            continue

        offset_x = target["x"] - player["x"]
        offset_y = target["y"] - player["y"]
        distance = hypot(offset_x, offset_y)
        if distance == 0 or distance > closest_distance:
            continue

        dot_product = normalized_x * offset_x / distance + normalized_y * offset_y / distance
        if dot_product >= melee_settings["minimum_dot_product"]:
            closest_target = target
            closest_distance = distance

    if closest_target:
        apply_damage(closest_target, melee_settings["damage"], player["id"], player["weapon"])
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
    attack_duration = MELEE_WEAPON_SETTINGS.get(player["weapon"], {}).get("attack_duration_seconds", 0.18)
    return max(0.0, min(1.0, 1 - (melee_ends_at - now) / attack_duration))


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


def apply_damage(player: dict[str, Any], damage: float, attacker_id: str, weapon: str | None = None) -> bool:
    """Apply damage, then award damage and a kill using authoritative server state."""
    if not player["alive"] or not player["connected"]:
        return False
    if get_spawn_protection_ends_in_seconds(player, monotonic()) > 0:
        return False

    hp_before = player["hp"]
    player["hp"] = max(0, hp_before - damage)
    damage_dealt = hp_before - player["hp"]
    attacker = players.get(attacker_id)
    if attacker is not None and attacker_id != player["id"]:
        attacker["damage_dealt"] += damage_dealt
        if damage_dealt > 0:
            hit_events.append(
                {
                    "attacker_id": attacker_id,
                    "target_id": player["id"],
                    "damage": damage_dealt,
                    "weapon": weapon or "fists",
                    "x": player["x"],
                    "y": player["y"],
                    "killed": player["hp"] == 0,
                    "blocked": False,
                }
            )
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


def melee_blocks_bullet(blocker: dict[str, Any], bullet: dict[str, Any]) -> bool:
    """Return whether an active knife swing swats this bullet out of the air."""
    if (
        blocker["weapon"] != "knife"
        or not blocker["alive"]
        or not blocker["connected"]
        or not round_is_active()
    ):
        return False

    melee_ends_at = blocker["melee_ends_at"]
    if melee_ends_at is None or monotonic() > melee_ends_at:
        return False
    if bullet["owner_id"] == blocker["id"]:
        return False

    offset_x = bullet["x"] - blocker["x"]
    offset_y = bullet["y"] - blocker["y"]
    distance = hypot(offset_x, offset_y)
    if distance == 0 or distance > KNIFE_BLOCK_REACH:
        return False

    facing = blocker["melee_angle"]
    dot_product = (offset_x * cos(facing) + offset_y * sin(facing)) / distance
    return dot_product >= KNIFE_BLOCK_MINIMUM_DOT_PRODUCT


def bullet_is_blocked(bullet: dict[str, Any]) -> bool:
    """Return True when an enemy knife swing deflects the bullet."""
    for blocker_id, blocker in players.items():
        if blocker_id == bullet["owner_id"] or not melee_blocks_bullet(blocker, bullet):
            continue
        hit_events.append(
            {
                "attacker_id": bullet["owner_id"],
                "target_id": blocker_id,
                "damage": 0.0,
                "weapon": "knife",
                "x": bullet["x"],
                "y": bullet["y"],
                "killed": False,
                "blocked": True,
            }
        )
        return True
    return False


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

        if bullet_is_blocked(bullet):
            bullets.remove(bullet)
            continue

        for target_id, target in players.items():
            if target_id == bullet["owner_id"] or not target["alive"] or not target["connected"]:
                continue

            if hypot(bullet["x"] - target["x"], bullet["y"] - target["y"]) <= BULLET_RADIUS + PLAYER_RADIUS:
                apply_damage(target, bullet["damage"], bullet["owner_id"], bullet["weapon"])
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


def collect_weapon_pickup(player: dict[str, Any]) -> bool:
    """Equip a nearby weapon after a server-validated pickup request."""
    if not player["alive"] or not player["connected"] or not round_is_active():
        return False

    for pickup in weapon_pickups.copy():
        distance_to_pickup = hypot(player["x"] - pickup["x"], player["y"] - pickup["y"])
        if distance_to_pickup <= PLAYER_RADIUS + PICKUP_RADIUS:
            if pickup["weapon"] in MELEE_WEAPON_SETTINGS:
                player["melee_weapon"] = pickup["weapon"]
                player["weapon"] = pickup["weapon"]
            else:
                player["gun_weapon"] = pickup["weapon"]
                player["magazine_capacity"] = MAGAZINE_CAPACITIES.get(pickup["weapon"], 0)
                player["ammo_in_mag"] = player["magazine_capacity"]
                player["reload_ends_at"] = None
                player["weapon"] = pickup["weapon"]
            weapon_pickups.remove(pickup)
            return True

    return False


def switch_weapon(player: dict[str, Any]) -> bool:
    """Toggle the active weapon between the ranged and melee slots."""
    if not player["alive"] or not player["connected"]:
        return False

    if player["weapon"] in RANGED_WEAPON_SETTINGS:
        player["weapon"] = player.get("melee_weapon", DEFAULT_WEAPON)
        return True

    if player.get("gun_weapon") is not None:
        player["weapon"] = player["gun_weapon"]
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
    """Choose the safest of eight symmetric map spawn points."""
    safest_position: tuple[float, float] | None = None
    safest_distance = -1.0
    candidate_spawns = list(SPAWN_POINTS)
    shuffle(candidate_spawns)
    for x, y in candidate_spawns:
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
    return SPAWN_POINTS[fallback_number % len(SPAWN_POINTS)]


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
    player["weapon"] = DEFAULT_WEAPON
    player["melee_weapon"] = DEFAULT_WEAPON
    player["gun_weapon"] = None
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
    for player in players.values():
        if player["is_bot"] and player["owner_id"] is None:
            player["engage_after"] = now + 3.0


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


def end_round(now: float) -> None:
    """Freeze the battlefield, crown a winner, and pause before the next round."""
    round_state["phase"] = "ending"
    round_state["ends_at"] = now + ROUND_END_DELAY_SECONDS
    bullets.clear()
    for player in players.values():
        player["move_x"] = 0.0
        player["move_y"] = 0.0

    ranked = sorted(
        players.values(),
        key=lambda player: (player["kills"], player["damage_dealt"]),
        reverse=True,
    )
    leader = ranked[0] if ranked else None
    if leader and (leader["kills"] > 0 or leader["damage_dealt"] > 0):
        round_state["winner_id"] = leader["id"]
    else:
        round_state["winner_id"] = None


def advance_round(now: float) -> None:
    """Advance the deathmatch through waiting, active, and ending phases."""
    phase = round_state["phase"]
    if phase == "waiting":
        if round_state["start_requested"] and len(players) >= MIN_PLAYERS_TO_START_ROUND:
            start_round(now)
        return

    if phase == "active":
        ends_at = round_state["ends_at"]
        if isinstance(ends_at, float) and now >= ends_at:
            end_round(now)
        return

    if phase == "ending":
        ends_at = round_state["ends_at"]
        if isinstance(ends_at, float) and now >= ends_at:
            start_round(now)


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
