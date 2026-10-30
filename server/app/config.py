"""Static configuration for Dropfire game rules and arena layout.

Everything here is pure data with no dependency on room state, so it can be
imported by the room-state, rules, and bot modules without creating cycles.
"""

import os


MAX_PLAYERS = 8
# Keep generous headroom: a single worker should never run at 100% CPU.
MAX_ROOMS = max(1, int(os.getenv("DROPFIRE_MAX_ROOMS", "12")))
LOBBY_BROADCAST_INTERVAL_SECONDS = 0.2

BOT_PREFERRED_RANGES = {"knife": 70.0, "pistol": 330.0, "rifle": 500.0}
BOT_FIRE_RANGES = {"pistol": 500.0, "rifle": 900.0}

WEAPON_TYPES = {"fists", "knife", "pistol", "rifle"}
RANGED_WEAPON_SETTINGS: dict[str, dict[str, float]] = {
    "pistol": {
        "damage": 25.0,
        "bullet_speed": 720.0,
        "bullet_lifetime_seconds": 0.75,
        "cooldown_seconds": 0.35,
    },
    "rifle": {
        "damage": 13.0,
        "bullet_speed": 1000.0,
        "bullet_lifetime_seconds": 1.5,
        "cooldown_seconds": 0.16,
    },
}
MAGAZINE_CAPACITIES = {"pistol": 12, "rifle": 20}
RELOAD_DURATION_SECONDS = 1.2

MELEE_WEAPON_SETTINGS: dict[str, dict[str, float]] = {
    "fists": {
        "damage": 30.0,
        "reach": 62.0,
        "cooldown_seconds": 0.5,
        "minimum_dot_product": 0.5,
        "attack_duration_seconds": 0.16,
    },
    "knife": {
        "damage": 100.0,
        "reach": 88.0,
        "cooldown_seconds": 0.65,
        "minimum_dot_product": 0.45,
        "attack_duration_seconds": 0.18,
    },
}

DEFAULT_WEAPON = "fists"
INITIAL_WEAPON_PICKUPS = (
    # Four outer pistols and four scarce one-shot knives, plus two central rifles.
    ("pistol-1", "pistol", 600.0, 410.0),
    ("knife-1", "knife", 1080.0, 430.0),
    ("knife-2", "knife", 1480.0, 430.0),
    ("pistol-2", "pistol", 1960.0, 410.0),
    ("pistol-3", "pistol", 600.0, 1030.0),
    ("knife-3", "knife", 1080.0, 1010.0),
    ("knife-4", "knife", 1480.0, 1010.0),
    ("pistol-4", "pistol", 1960.0, 1030.0),
    # Strong rifles are deliberately central and exposed from both side lanes.
    ("rifle-1", "rifle", 1140.0, 720.0),
    ("rifle-2", "rifle", 1420.0, 720.0),
)
COVER_WALLS = (
    # Citadel Run: three routes (top, centre, bottom) with 180-degree symmetry.
    {"id": "vault-north", "x": 1280.0, "y": 570.0, "width": 120.0, "height": 220.0},
    {"id": "vault-south", "x": 1280.0, "y": 870.0, "width": 120.0, "height": 220.0},
    {"id": "cover-north-west", "x": 760.0, "y": 500.0, "width": 280.0, "height": 72.0},
    {"id": "cover-north-east", "x": 1800.0, "y": 500.0, "width": 280.0, "height": 72.0},
    {"id": "cover-south-west", "x": 760.0, "y": 940.0, "width": 280.0, "height": 72.0},
    {"id": "cover-south-east", "x": 1800.0, "y": 940.0, "width": 280.0, "height": 72.0},
    {"id": "cover-west", "x": 430.0, "y": 720.0, "width": 72.0, "height": 240.0},
    {"id": "cover-east", "x": 2130.0, "y": 720.0, "width": 72.0, "height": 240.0},
)
SPAWN_POINTS = (
    (360.0, 260.0),
    (1120.0, 250.0),
    (1440.0, 250.0),
    (2200.0, 260.0),
    (360.0, 1180.0),
    (1120.0, 1190.0),
    (1440.0, 1190.0),
    (2200.0, 1180.0),
)

HEALTH_PICKUP_AMOUNT = 35
INITIAL_HEALTH_PICKUPS = (
    ("health-1", 900.0, 720.0),
    ("health-2", 1660.0, 720.0),
    ("health-3", 1280.0, 300.0),
    ("health-4", 1280.0, 1140.0),
)

PICKUP_SPAWN_INTERVAL_SECONDS = 8.0
MAX_WEAPON_PICKUPS = 14
MAX_HEALTH_PICKUPS = 7
MAX_RIFLE_PICKUPS = 3
MAX_KNIFE_PICKUPS = 6
PICKUP_SPAWN_MIN_PLAYER_DISTANCE = 140.0
PICKUP_SPAWN_MIN_PICKUP_DISTANCE = 90.0

PLAYER_SPEED = 280.0
KNIFE_SPEED_MULTIPLIER = 1.15
KNIFE_BLOCK_REACH = 104.0
# cos(90°) = 0: block anything in the front half-plane; lower values widen past 90°.
KNIFE_BLOCK_MINIMUM_DOT_PRODUCT = 0.0
PLAYER_RADIUS = 20.0
PLAYER_MAX_HP = 100
# The player centre may be within this radius; including PLAYER_RADIUS gives a
# forgiving 62px edge-to-centre pickup distance without allowing long-range looting.
PICKUP_RADIUS = 42.0
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
ROUND_END_DELAY_SECONDS = 20.0
RECONNECT_GRACE_SECONDS = 15.0
EMPTY_ROOM_TTL_SECONDS = 60.0
MATCH_DURATION_SECONDS = 180.0
RESPAWN_DELAY_SECONDS = 3.0
SPAWN_PROTECTION_SECONDS = 1.5
MIN_SPAWN_DISTANCE_FROM_ENEMY = 450.0

ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
