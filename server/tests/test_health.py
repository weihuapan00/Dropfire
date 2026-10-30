"""Tests for the health/capacity endpoint."""

import asyncio

from app.main import health_check


def test_health_exposes_capacity_and_tick_metrics():
    data = asyncio.run(health_check())

    assert data["status"] == "ok"
    for key in (
        "rooms",
        "players",
        "max_rooms",
        "max_players_per_room",
        "tick_ms",
        "max_tick_ms",
        "loop_lag_ms",
        "max_loop_lag_ms",
    ):
        assert key in data
