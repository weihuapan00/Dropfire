"""Exercise two real WebSocket routes and the running authoritative game loop."""

from fastapi.testclient import TestClient

from app import rules, state
from app.config import COVER_WALLS
from app.main import app


def receive_until(socket, predicate):
    # Active rounds broadcast continuously; cap the number of snapshots so an
    # incorrect result fails instead of waiting for an entire three-minute round.
    for _ in range(120):
        message = socket.receive_json()
        if predicate(message):
            return message
    raise AssertionError("Expected multiplayer state was not received")


def player_in(snapshot, player_id):
    return next(player for player in snapshot["players"] if player["id"] == player_id)


def test_two_players_receive_map_and_share_exclusive_pickup(monkeypatch):
    # Place both players within reach of the same initial pistol. All joining,
    # host checks, match start, pickup, and broadcast logic remain real.
    monkeypatch.setattr(rules, "find_spawn_position", lambda _id, number: (600 + number * 15, 410))
    with TestClient(app) as client:
        response = client.post("/api/rooms")
        assert response.status_code == 200
        code = response.json()["code"]
        try:
            with client.websocket_connect(f"/ws/{code}?session=flow-host") as host:
                host_id = host.receive_json()["player_id"]
                host_map = host.receive_json()
                with client.websocket_connect(f"/ws/{code}?session=flow-guest") as guest:
                    guest_id = guest.receive_json()["player_id"]
                    guest_map = guest.receive_json()
                    assert host_map == guest_map == {"type": "arena_config", "covers": list(COVER_WALLS)}

                    host.send_json({"type": "start_match"})
                    for socket in (host, guest):
                        snapshot = receive_until(socket, lambda message: (
                            message["type"] == "world_state" and message["round"]["phase"] == "active"
                        ))
                        assert len(snapshot["players"]) == 2
                        assert all(player["weapon"] == "fists" for player in snapshot["players"])

                    host.send_json({"type": "pickup_intent"})
                    for socket in (host, guest):
                        snapshot = receive_until(socket, lambda message: (
                            message["type"] == "world_state"
                            and player_in(message, host_id)["weapon"] == "pistol"
                        ))
                        assert "pistol-1" not in {pickup["id"] for pickup in snapshot["pickups"]}
                        assert player_in(snapshot, guest_id)["weapon"] == "fists"

                    # A second player cannot acquire the already-consumed gun.
                    guest.send_json({"type": "pickup_intent"})
                    guest.send_json({"type": "ping", "client_sent_at": "after-pickup"})
                    receive_until(guest, lambda message: message["type"] == "pong")
                    # The pong establishes command ordering, while an outbound
                    # snapshot may still predate the command. Check committed
                    # server state as well so a stale snapshot cannot hide a bug.
                    assert state.rooms[code]["players"][guest_id]["weapon"] == "fists"
                    snapshot = receive_until(guest, lambda message: message["type"] == "world_state")
                    assert player_in(snapshot, guest_id)["weapon"] == "fists"
                    assert player_in(snapshot, host_id)["weapon"] == "pistol"
        finally:
            state.rooms.pop(code, None)
