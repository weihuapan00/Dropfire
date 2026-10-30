"""Shared pytest fixtures for Dropfire server rules."""

from collections.abc import Iterator

import pytest

from app import state


@pytest.fixture
def room() -> Iterator[dict]:
    """Create a fresh room and bind it to the room context for one test."""
    code = state.create_room()
    bound_room = state.rooms[code]
    token = state.room_context.set(bound_room)
    try:
        yield bound_room
    finally:
        state.room_context.reset(token)
        state.rooms.pop(code, None)
