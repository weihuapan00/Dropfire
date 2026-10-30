"""Tests for room cleanup after the last human leaves."""

from time import monotonic

from app.bots import remove_expired_disconnections


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
