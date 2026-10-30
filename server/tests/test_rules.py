"""Unit tests for the server-authoritative combat and round rules."""

from time import monotonic

import pytest

from app.rules import (
    advance_round,
    apply_damage,
    apply_move_intent,
    attack_with_melee,
    collect_weapon_pickup,
    fire_weapon,
    request_match_start,
    switch_weapon,
)
from app.state import bullets, hit_events, weapon_pickups


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


def test_collect_weapon_pickup_equips_and_removes_pickup(room):
    activate_round(room)
    player = make_player("p1", x=600.0, y=410.0)
    room["players"]["p1"] = player
    pickup_ids_before = {pickup["id"] for pickup in weapon_pickups}

    collected = collect_weapon_pickup(player)

    assert collected is True
    assert player["weapon"] == "pistol"
    assert player["gun_weapon"] == "pistol"
    assert player["ammo_in_mag"] == 12
    assert player["magazine_capacity"] == 12
    assert "pistol-1" in pickup_ids_before
    assert "pistol-1" not in {pickup["id"] for pickup in weapon_pickups}


def test_collect_knife_upgrades_melee_slot(room):
    activate_round(room)
    player = make_player("p1", x=1080.0, y=430.0)
    room["players"]["p1"] = player

    collected = collect_weapon_pickup(player)

    assert collected is True
    assert player["weapon"] == "knife"
    assert player["melee_weapon"] == "knife"
    assert player["gun_weapon"] is None
    assert "knife-1" not in {pickup["id"] for pickup in weapon_pickups}


def test_switch_weapon_toggles_between_gun_and_melee(room):
    activate_round(room)
    player = make_player(
        "p1",
        weapon="pistol",
        melee_weapon="knife",
        gun_weapon="pistol",
        ammo_in_mag=12,
        magazine_capacity=12,
    )
    room["players"]["p1"] = player

    assert switch_weapon(player) is True
    assert player["weapon"] == "knife"

    assert switch_weapon(player) is True
    assert player["weapon"] == "pistol"


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
    assert fists_target["hp"] == 70
    assert fists_target["alive"] is True


def test_advance_round_starts_when_requested(room):
    room["round_state"]["start_requested"] = True
    room["players"]["p1"] = make_player("p1")
    room["players"]["p2"] = make_player("p2")

    advance_round(monotonic())

    assert room["round_state"]["phase"] == "active"
    assert room["round_state"]["number"] == 1
    assert isinstance(room["round_state"]["ends_at"], float)


def test_request_match_start_requires_host(room):
    room["players"]["host"] = make_player("host")
    room["players"]["guest"] = make_player("guest")
    room["host_player_id"] = "host"

    assert request_match_start("host") is True
    assert room["round_state"]["start_requested"] is True

    room["round_state"]["start_requested"] = False
    assert request_match_start("guest") is False
