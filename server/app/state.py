"""In-memory room storage and room-scoped state accessors.

Each room owns its own ``players``, ``bullets``, ``weapon_pickups``, and
``round_state``. A context variable marks which room the current WebSocket
handler or game-loop iteration is operating on, and the module-level proxies
(``players``, ``bullets``, ...) read and write through that context.
"""

from collections.abc import MutableMapping, MutableSequence
from contextvars import ContextVar
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from .config import (
    EMPTY_ROOM_TTL_SECONDS,
    HEALTH_PICKUP_AMOUNT,
    INITIAL_HEALTH_PICKUPS,
    INITIAL_WEAPON_PICKUPS,
    MAX_ROOMS,
    ROOM_CODE_ALPHABET,
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
weapon_pickups: MutableSequence[dict[str, Any]] = RoomList("weapon_pickups")
health_pickups: MutableSequence[dict[str, Any]] = RoomList("health_pickups")
round_state: MutableMapping[str, Any] = RoomMapping("round_state")
hit_events: MutableSequence[dict[str, Any]] = RoomList("hit_events")


def create_initial_weapon_pickups() -> list[dict[str, Any]]:
    """Create new pickup dictionaries so testing resets cannot mutate the blueprint."""
    return [
        {"id": pickup_id, "weapon": weapon, "x": x, "y": y}
        for pickup_id, weapon, x, y in INITIAL_WEAPON_PICKUPS
    ]


def create_initial_health_pickups() -> list[dict[str, Any]]:
    """Create fresh medkits so a round reset cannot mutate the blueprint."""
    return [
        {"id": pickup_id, "x": x, "y": y, "amount": HEALTH_PICKUP_AMOUNT}
        for pickup_id, x, y in INITIAL_HEALTH_PICKUPS
    ]


def create_room() -> str | None:
    """Create an empty room, or return None when the server is at capacity."""
    if len(rooms) >= MAX_ROOMS:
        return None
    while True:
        code = "".join(ROOM_CODE_ALPHABET[uuid4().int % len(ROOM_CODE_ALPHABET)] for _ in range(6))
        if code not in rooms:
            break
    rooms[code] = {
        "code": code,
        "should_close": False,
        "created_at": monotonic(),
        "last_broadcast_at": 0.0,
        "active_connections": [],
        "players": {},
        "bullets": [],
        "weapon_pickups": [],
        "health_pickups": create_initial_health_pickups(),
        "hit_events": [],
        "next_pickup_spawn_at": 0.0,
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


def mark_stale_empty_rooms(now: float) -> None:
    """Mark rooms that were created but never joined for removal."""
    for room in rooms.values():
        if not room["players"] and now - room.get("created_at", now) > EMPTY_ROOM_TTL_SECONDS:
            room["should_close"] = True
