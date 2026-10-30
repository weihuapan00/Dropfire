"""Tests for room cleanup after the last human leaves."""

from time import monotonic

from app import state
from app.bots import remove_expired_disconnections
from app.state import mark_stale_empty_rooms


def test_room_marks_close_when_last_human_disconnect_expires(room):
    room["players"]["p1"] = {
        "id": "p1",
        "is_bot": False,
        "connected": False,
        "disconnect_deadline": monotonic() - 1.0,
    }

    remove_expired_disconnections(monotonic())

    assert "p1" not in room["players"]
    assert room["should_close"] is True


def test_room_stays_open_while_another_human_remains(room):
    room["players"]["p1"] = {
        "id": "p1",
        "is_bot": False,
        "connected": False,
        "disconnect_deadline": monotonic() - 1.0,
    }
    room["players"]["p2"] = {
        "id": "p2",
        "is_bot": False,
        "connected": True,
        "disconnect_deadline": None,
    }

    remove_expired_disconnections(monotonic())

    assert "p1" not in room["players"]
    assert "p2" in room["players"]
    assert room["should_close"] is False


def test_stale_empty_room_is_marked_for_close(room):
    room["created_at"] = monotonic() - 61.0

    mark_stale_empty_rooms(monotonic())

    assert room["should_close"] is True


def test_fresh_empty_room_is_not_marked_for_close(room):
    mark_stale_empty_rooms(monotonic())

    assert room["should_close"] is False


def test_occupied_room_is_not_marked_for_close(room):
    room["created_at"] = monotonic() - 3600.0
    room["players"]["p1"] = {"id": "p1"}

    mark_stale_empty_rooms(monotonic())

    assert room["should_close"] is False


def test_create_room_respects_capacity(room, monkeypatch):
    monkeypatch.setattr(state, "MAX_ROOMS", len(state.rooms) + 1)

    extra_code = state.create_room()
    assert extra_code is not None
    try:
        assert state.create_room() is None
    finally:
        state.rooms.pop(extra_code, None)
