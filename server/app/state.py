"""In-memory room storage and room-scoped state accessors.

Each room owns its own ``players``, ``bullets``, ``weapon_pickups``, and
``round_state``. A context variable marks which room the current WebSocket
handler or game-loop iteration is operating on, and the module-level proxies
(``players``, ``bullets``, ...) read and write through that context.
"""

from collections.abc import MutableMapping, MutableSequence
from contextvars import ContextVar
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from .config import INITIAL_WEAPON_PICKUPS, ROOM_CODE_ALPHABET


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
round_state: MutableMapping[str, Any] = RoomMapping("round_state")
hit_events: MutableSequence[dict[str, Any]] = RoomList("hit_events")


def create_initial_weapon_pickups() -> list[dict[str, Any]]:
    """Create new pickup dictionaries so testing resets cannot mutate the blueprint."""
    return [
        {"id": pickup_id, "weapon": weapon, "x": x, "y": y}
        for pickup_id, weapon, x, y in INITIAL_WEAPON_PICKUPS
    ]


def create_room() -> str:
    """Create an empty room with fully isolated authoritative game state."""
    while True:
        code = "".join(ROOM_CODE_ALPHABET[uuid4().int % len(ROOM_CODE_ALPHABET)] for _ in range(6))
        if code not in rooms:
            break
    rooms[code] = {
        "code": code,
        "should_close": False,
        "active_connections": [],
        "players": {},
        "bullets": [],
        "weapon_pickups": create_initial_weapon_pickups(),
        "hit_events": [],
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
