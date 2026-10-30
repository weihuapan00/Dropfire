"""Exercise disconnect/rejoin through the real WebSocket endpoint."""

from fastapi.testclient import TestClient

from app.main import app
from app.rules import advance_player_movement


def receive_type(socket, message_type):
    for _ in range(30):
        message = socket.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"Did not receive {message_type}")


def flush_commands(socket):
    """A pong confirms the endpoint processed all preceding ordered commands."""
    socket.send_json({"type": "ping"})
    receive_type(socket, "pong")


def test_disconnect_stops_movement_and_reconnect_accepts_fresh_input(room):
    # Do not start lifespan: step movement explicitly, without a racing game loop.
    client = TestClient(app)
    path = f"/ws/{room['code']}?session=reconnect-test"
    try:
        with client.websocket_connect(path) as socket:
            connected = receive_type(socket, "server_connected")
            player_id = connected["player_id"]
            player = room["players"][player_id]
            socket.send_json({"type": "add_ai_bot"})
            socket.send_json({"type": "start_match"})
            socket.send_json({"type": "move_intent", "direction_x": 1, "direction_y": 0})
            flush_commands(socket)
            assert room["round_state"]["phase"] == "active"
            assert player["move_x"] == 1

        assert player["connected"] is False
        assert (player["move_x"], player["move_y"]) == (0, 0)
        position = (player["x"], player["y"])
        # Defend against stale input even if some caller left it on the record.
        player["move_x"] = 1
        assert advance_player_movement(player, 0.1) is False
        assert (player["x"], player["y"]) == position

        with client.websocket_connect(path) as socket:
            reconnected = receive_type(socket, "server_connected")
            assert reconnected["player_id"] == player_id
            assert player["connected"] is True
            assert (player["move_x"], player["move_y"]) == (0, 0)
            assert advance_player_movement(player, 0.1) is False

            # Holding the same direction across reconnect must work when resent.
            socket.send_json({"type": "move_intent", "direction_x": 1, "direction_y": 0})
            flush_commands(socket)
            assert advance_player_movement(player, 0.01) is True
            assert player["x"] > position[0]
    finally:
        client.close()
