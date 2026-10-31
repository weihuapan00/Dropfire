"""Unit tests for the server-authoritative combat and round rules."""

import random
from math import cos, radians, sin
from time import monotonic

import pytest

from app.config import MAX_HEALTH_PICKUPS, MAX_KNIFE_PICKUPS, MAX_RIFLE_PICKUPS, MAX_WEAPON_PICKUPS
from app.rules import (
    advance_bullets,
    advance_pickup_spawner,
    advance_player_movement,
    advance_round,
    apply_damage,
    apply_move_intent,
    attack_with_melee,
    collect_pickup,
    collect_weapon_pickup,
    fire_weapon,
    equip_progression_weapon,
    respawn_player,
    start_round,
    request_match_start,
    switch_weapon,
)
from app.state import bullets, health_pickups, hit_events, weapon_pickups


def make_player(player_id: str, **overrides):
    """Build a fully populated player record with sensible defaults."""
    player = {
        "id": player_id,
        "x": 1280.0,
        "y": 720.0,
        "move_x": 0.0,
        "move_y": 0.0,
        "last_fire_at": float("-inf"),
        "last_melee_at": float("-inf"),
        "melee_started_at": None,
        "melee_ends_at": None,
        "melee_angle": 0.0,
        "weapon": "fists",
        "melee_weapon": "fists",
        "gun_weapon": None,
        "ammo_in_mag": 0,
        "magazine_capacity": 0,
        "reload_ends_at": None,
        "hp": 100,
        "alive": True,
        "respawn_at": None,
        "invulnerable_until": 0.0,
        "damage_dealt": 0.0,
        "kills": 0,
        "connected": True,
        "connection": None,
        "session_token": None,
        "disconnect_deadline": None,
        "is_bot": False,
        "owner_id": None,
    }
    player.update(overrides)
    return player


def activate_round(room: dict) -> None:
    room["round_state"]["phase"] = "active"
    room["round_state"]["ends_at"] = monotonic() + 180.0


def test_move_intent_normalizes_direction(room):
    activate_round(room)
    player = make_player("p1")
    room["players"]["p1"] = player

    accepted = apply_move_intent(player, {"direction_x": 3.0, "direction_y": 4.0})

    assert accepted is True
    assert player["move_x"] == pytest.approx(0.6)
    assert player["move_y"] == pytest.approx(0.8)


def test_move_intent_rejected_while_round_is_waiting(room):
    player = make_player("p1")
    room["players"]["p1"] = player

    accepted = apply_move_intent(player, {"direction_x": 1.0, "direction_y": 0.0})

    assert accepted is False


def test_apply_damage_accumulates_damage_dealt(room):
    activate_round(room)
    attacker = make_player("attacker")
    target = make_player("target")
    room["players"]["attacker"] = attacker
    room["players"]["target"] = target

    applied = apply_damage(target, 25.0, "attacker")

    assert applied is True
    assert target["hp"] == 75
    assert target["alive"] is True
    assert attacker["damage_dealt"] == pytest.approx(25.0)
    assert attacker["kills"] == 0
    assert len(hit_events) == 1
    assert hit_events[0]["damage"] == pytest.approx(25.0)
    assert hit_events[0]["killed"] is False


def test_apply_damage_kill_awards_kill_and_schedules_respawn(room):
    activate_round(room)
    attacker = make_player("attacker")
    target = make_player("target")
    room["players"]["attacker"] = attacker
    room["players"]["target"] = target

    applied = apply_damage(target, 100.0, "attacker")

    assert applied is True
    assert target["hp"] == 0
    assert target["alive"] is False
    assert isinstance(target["respawn_at"], float)
    assert attacker["kills"] == 1
    assert len(hit_events) == 1
    assert hit_events[0]["killed"] is True


def test_fire_weapon_spawns_bullet_and_consumes_ammo(room):
    activate_round(room)
    player = make_player(
        "p1",
        weapon="pistol",
        ammo_in_mag=12,
        magazine_capacity=12,
    )
    room["players"]["p1"] = player

    fired = fire_weapon(player, {"direction_x": 1.0, "direction_y": 0.0})

    assert fired is True
    assert len(bullets) == 1
    assert bullets[0]["weapon"] == "pistol"
    assert bullets[0]["owner_id"] == "p1"
    assert player["ammo_in_mag"] == 11


def test_fire_weapon_respects_cooldown(room):
    activate_round(room)
    player = make_player(
        "p1",
        weapon="pistol",
        ammo_in_mag=12,
        magazine_capacity=12,
    )
    room["players"]["p1"] = player
    direction = {"direction_x": 1.0, "direction_y": 0.0}

    assert fire_weapon(player, direction) is True
    assert fire_weapon(player, direction) is False
    assert len(bullets) == 1
    assert player["ammo_in_mag"] == 11


def test_ground_weapon_cannot_skip_stage(room):
    activate_round(room)
    player = make_player("p1")
    equip_progression_weapon(player)
    weapon_pickups.append({"id": "cheat", "weapon": "knife", "x": player["x"], "y": player["y"]})
    assert collect_weapon_pickup(player) is False
    assert player["weapon"] == "pistol"
    assert player["weapon_level"] == 0


@pytest.mark.parametrize("is_bot", [False, True])
def test_gun_game_progression_respawn_and_victory(room, is_bot):
    activate_round(room)
    attacker = make_player("attacker", is_bot=is_bot)
    target = make_player("target")
    room["players"].update(attacker=attacker, target=target)
    equip_progression_weapon(attacker)
    assert attacker["weapon"] == "pistol"
    for weapon, next_weapon in [("pistol", "shotgun"), ("shotgun", "rifle"), ("rifle", "sniper"), ("sniper", "knife")]:
        target.update(alive=True, hp=100, invulnerable_until=0.0)
        assert apply_damage(target, 100, "attacker", weapon)
        assert attacker["weapon"] == next_weapon
        level = attacker["weapon_level"]
        attacker.update(alive=False, hp=0)
        respawn_player(attacker, 0)
        assert attacker["weapon_level"] == level
        assert attacker["weapon"] == next_weapon
        assert attacker["ammo_in_mag"] == attacker["magazine_capacity"]
        assert room["round_state"]["phase"] == "active"
    target.update(alive=True, hp=100, invulnerable_until=0.0)
    apply_damage(target, 100, "attacker", "knife")
    assert room["round_state"]["winner_id"] == "attacker"
    assert room["round_state"]["phase"] == "ending"
    target.update(alive=True, hp=100)
    assert not apply_damage(target, 100, "attacker", "knife")
    assert attacker["kills"] == 5
    room["round_state"]["ends_at"] = monotonic() - 1
    advance_round(monotonic())
    assert room["round_state"]["phase"] == "active"
    assert attacker["weapon"] == "pistol"
    assert attacker["weapon_level"] == attacker["kills"] == 0


def test_switch_cannot_bypass_progression(room):
    activate_round(room)
    player = make_player("p1")
    equip_progression_weapon(player)
    assert not switch_weapon(player)
    assert player["weapon"] == "pistol"


def test_old_stage_projectile_cannot_skip_level_or_win(room):
    activate_round(room)
    attacker = make_player("attacker", weapon_level=1)
    target = make_player("target")
    room["players"].update(attacker=attacker, target=target)
    equip_progression_weapon(attacker)
    apply_damage(target, 100, "attacker", "pistol")
    assert attacker["kills"] == 1
    assert attacker["weapon_level"] == 1
    attacker["weapon_level"] = 2
    equip_progression_weapon(attacker)
    target.update(hp=100, alive=True)
    apply_damage(target, 100, "attacker", "rifle")
    assert room["round_state"]["phase"] == "active"
    assert room["round_state"]["winner_id"] is None


def test_melee_damage_differs_by_weapon(room):
    activate_round(room)
    attacker = make_player("attacker", x=1280.0, y=720.0, melee_weapon="knife", weapon="knife")
    target = make_player("target", x=1280.0 + 40.0, y=720.0)
    room["players"]["attacker"] = attacker
    room["players"]["target"] = target

    hit = attack_with_melee(attacker, {"direction_x": 1.0, "direction_y": 0.0})

    assert hit is True
    assert target["hp"] == 0
    assert target["alive"] is False

    fists_attacker = make_player("fists", x=1280.0, y=720.0, weapon="fists", melee_weapon="fists")
    fists_target = make_player("fists-target", x=1280.0 + 40.0, y=720.0)
    room["players"]["fists"] = fists_attacker
    room["players"]["fists-target"] = fists_target

    hit = attack_with_melee(fists_attacker, {"direction_x": 1.0, "direction_y": 0.0})

    assert hit is True
    assert fists_target["hp"] == 90
    assert fists_target["alive"] is True


@pytest.mark.parametrize(
    "attacker_x,target_x,y,expected_x",
    [
        (500.0, 540.0, 300.0, 604.0),  # Open floor: push away by 64px.
        (2420.0, 2460.0, 300.0, 2488.0),  # Stop at the arena edge.
        (520.0, 560.0, 500.0, 596.0),  # Stop before west cover (edge at x=620).
    ],
)
def test_fists_deal_ten_damage_and_push_without_crossing_walls(room, attacker_x, target_x, y, expected_x):
    activate_round(room)
    attacker = make_player("attacker", x=attacker_x, y=y)
    target = make_player("target", x=target_x, y=y)
    room["players"].update(attacker=attacker, target=target)

    assert attack_with_melee(attacker, {"direction_x": 1, "direction_y": 0})
    assert target["hp"] == 90
    assert target["x"] == pytest.approx(expected_x)
    assert target["y"] == y
    assert attacker["damage_dealt"] == 10
    # The existing cooldown also prevents a second displacement.
    assert not attack_with_melee(attacker, {"direction_x": 1, "direction_y": 0})
    assert target["x"] == pytest.approx(expected_x)


def test_spawn_protection_prevents_punch_damage_and_knockback(room):
    activate_round(room)
    attacker = make_player("attacker", x=500.0, y=300.0)
    target = make_player("target", x=540.0, y=300.0, invulnerable_until=monotonic() + 10)
    room["players"].update(attacker=attacker, target=target)

    assert attack_with_melee(attacker, {"direction_x": 1, "direction_y": 0})
    assert target["hp"] == 100
    assert target["x"] == 540.0


def test_advance_round_starts_when_requested(room):
    room["round_state"]["start_requested"] = True
    room["players"]["p1"] = make_player("p1")
    room["players"]["p2"] = make_player("p2")

    advance_round(monotonic())

    assert room["round_state"]["phase"] == "active"
    assert room["round_state"]["number"] == 1
    assert room["round_state"]["ends_at"] is None


def test_round_does_not_end_by_timer_or_kill_count(room):
    activate_round(room)
    room["round_state"]["ends_at"] = monotonic() - 1.0
    room["players"]["leader"] = make_player("leader", kills=99)
    advance_round(monotonic())
    assert room["round_state"]["phase"] == "active"
    assert room["round_state"]["winner_id"] is None


def test_request_match_start_requires_host(room):
    room["players"]["host"] = make_player("host")
    room["players"]["guest"] = make_player("guest")
    room["host_player_id"] = "host"

    assert request_match_start("host") is True
    assert room["round_state"]["start_requested"] is True

    room["round_state"]["start_requested"] = False
    assert request_match_start("guest") is False


def test_knife_grants_faster_movement(room):
    activate_round(room)
    knife_player = make_player("knife", weapon="knife", move_x=1.0, move_y=0.0)
    fists_player = make_player("fists", weapon="fists", move_x=1.0, move_y=0.0)
    room["players"]["knife"] = knife_player
    room["players"]["fists"] = fists_player

    advance_player_movement(knife_player, 1.0)
    advance_player_movement(fists_player, 1.0)

    assert knife_player["x"] - fists_player["x"] == pytest.approx(280.0 * 0.15)


def test_knife_swing_blocks_enemy_bullet(room):
    activate_round(room)
    blocker = make_player(
        "blocker",
        weapon="knife",
        melee_weapon="knife",
        melee_ends_at=monotonic() + 0.18,
        melee_angle=0.0,
    )
    target = make_player("target", x=1340.0)
    room["players"]["blocker"] = blocker
    room["players"]["target"] = target
    bullets.append(
        {
            "id": "bullet-1",
            "owner_id": "shooter",
            "weapon": "pistol",
            "damage": 25.0,
            "x": 1320.0,
            "y": 720.0,
            "velocity_x": 0.0,
            "velocity_y": 0.0,
            "remaining_seconds": 1.0,
        }
    )

    advance_bullets(0.0)

    assert len(bullets) == 0
    assert target["hp"] == 100
    assert any(event["blocked"] for event in hit_events)


def test_knife_swing_does_not_block_bullet_behind(room):
    activate_round(room)
    blocker = make_player(
        "blocker",
        weapon="knife",
        melee_weapon="knife",
        melee_ends_at=monotonic() + 0.18,
        melee_angle=0.0,
    )
    target = make_player("target", x=1220.0)
    room["players"]["blocker"] = blocker
    room["players"]["target"] = target
    bullets.append(
        {
            "id": "bullet-2",
            "owner_id": "shooter",
            "weapon": "pistol",
            "damage": 25.0,
            "x": 1240.0,
            "y": 720.0,
            "velocity_x": 0.0,
            "velocity_y": 0.0,
            "remaining_seconds": 1.0,
        }
    )

    advance_bullets(0.0)

    assert len(bullets) == 0
    assert target["hp"] == 75
    assert not any(event["blocked"] for event in hit_events)


def test_knife_block_cone_accepts_wide_front_angle(room):
    activate_round(room)
    blocker = make_player(
        "blocker",
        x=1000.0,
        weapon="knife",
        melee_weapon="knife",
        melee_ends_at=monotonic() + 0.18,
        melee_angle=0.0,
    )
    room["players"]["blocker"] = blocker
    angle = radians(85)
    bullets.append(
        {
            "id": "bullet-wide",
            "owner_id": "shooter",
            "weapon": "pistol",
            "damage": 25.0,
            "x": 1000.0 + 60.0 * cos(angle),
            "y": 720.0 + 60.0 * sin(angle),
            "velocity_x": 0.0,
            "velocity_y": 0.0,
            "remaining_seconds": 1.0,
        }
    )

    advance_bullets(0.0)

    assert len(bullets) == 0
    assert any(event["blocked"] for event in hit_events)


def test_collect_medkit_heals_and_removes_pickup(room):
    activate_round(room)
    player = make_player("p1", x=900.0, y=720.0, hp=50)
    room["players"]["p1"] = player

    collected = collect_pickup(player)

    assert collected is True
    assert player["hp"] == 85
    assert "health-1" not in {pickup["id"] for pickup in health_pickups}


def test_medkit_healing_caps_at_max_hp(room):
    activate_round(room)
    player = make_player("p1", x=900.0, y=720.0, hp=90)
    room["players"]["p1"] = player

    assert collect_pickup(player) is True
    assert player["hp"] == 100


def test_medkit_stays_when_player_is_full_hp(room):
    activate_round(room)
    player = make_player("p1", x=900.0, y=720.0, hp=100)
    room["players"]["p1"] = player

    assert collect_pickup(player) is False
    assert "health-1" in {pickup["id"] for pickup in health_pickups}


def test_gun_game_only_spawns_medkits(room):
    start_round(monotonic())
    assert not weapon_pickups
    for _ in range(20):
        room["next_pickup_spawn_at"] = 0
        advance_pickup_spawner(monotonic())
    assert not weapon_pickups
    assert len(health_pickups) <= MAX_HEALTH_PICKUPS


def test_pickup_spawner_adds_a_pickup_when_due(room):
    random.seed(7)
    activate_round(room)
    room["next_pickup_spawn_at"] = monotonic() - 1.0
    before = len(weapon_pickups) + len(health_pickups)

    spawned = advance_pickup_spawner(monotonic())

    assert spawned is True
    assert len(weapon_pickups) + len(health_pickups) == before + 1


def test_pickup_spawner_waits_for_interval(room):
    activate_round(room)
    room["next_pickup_spawn_at"] = monotonic() + 100.0
    before = len(weapon_pickups) + len(health_pickups)

    assert advance_pickup_spawner(monotonic()) is False
    assert len(weapon_pickups) + len(health_pickups) == before


def test_pickup_spawner_respects_caps(room):
    random.seed(3)
    activate_round(room)
    for _ in range(60):
        room["next_pickup_spawn_at"] = monotonic() - 1.0
        advance_pickup_spawner(monotonic())

    assert len(weapon_pickups) <= MAX_WEAPON_PICKUPS
    assert len(health_pickups) <= MAX_HEALTH_PICKUPS
    assert sum(pickup["weapon"] == "rifle" for pickup in weapon_pickups) <= MAX_RIFLE_PICKUPS
    assert sum(pickup["weapon"] == "knife" for pickup in weapon_pickups) <= MAX_KNIFE_PICKUPS


def test_bot_spawns_armed_and_knife_stage_attacks_instead_of_seeking_guns(room):
    from app.bots import create_fill_bot, advance_fill_bot_ai
    activate_round(room)
    create_fill_bot()
    bot = next(iter(room["players"].values()))
    assert bot["weapon"] == "pistol"
    assert bot["ammo_in_mag"] == 12
    bot.update(weapon_level=4, x=1280.0, y=720.0)
    equip_progression_weapon(bot)
    target = make_player("target", x=1330.0, y=720.0)
    room["players"]["target"] = target
    weapon_pickups.append({"id": "bait", "weapon": "rifle", "x": 600.0, "y": 410.0})
    advance_fill_bot_ai(monotonic())
    assert not target["alive"]
    assert room["round_state"]["winner_id"] == bot["id"]


@pytest.mark.parametrize("weapon,count,ammo", [("shotgun", 6, 5), ("sniper", 1, 3)])
def test_new_guns_fire_once_and_enforce_cooldown(room, weapon, count, ammo):
    activate_round(room)
    player = make_player("shooter", weapon=weapon, ammo_in_mag=ammo, last_fire_at=0)
    room["players"]["shooter"] = player
    assert fire_weapon(player, {"direction_x": 1, "direction_y": 0})
    assert len(bullets) == count
    assert player["ammo_in_mag"] == ammo - 1
    assert not fire_weapon(player, {"direction_x": 1, "direction_y": 0})
    assert len(bullets) == count
    if weapon == "shotgun":
        assert min(b["velocity_y"] for b in bullets) < 0
        assert max(b["velocity_y"] for b in bullets) > 0
