"""Exercise debug authorization through the real WebSocket endpoint."""

from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from app import main


DEBUG_COMMANDS = (
    "spawn_test_bot",
    "debug_respawn_bot",
    "debug_reset_weapon_pickups",
    "debug_reset_test_round",
    "debug_collect_pickup",
    "debug_move_bot",
)


def receive_type(socket, message_type):
    for _ in range(20):
        message = socket.receive_json()
        if message["type"] == message_type:
            return message
    pytest.fail(f"Did not receive {message_type}")


def connect(stack, client, code, session):
    socket = stack.enter_context(client.websocket_connect(f"/ws/{code}?session={session}"))
    identity = receive_type(socket, "server_connected")
    receive_type(socket, "arena_config")
    return socket, identity["player_id"]


@pytest.mark.parametrize("command", DEBUG_COMMANDS)
@pytest.mark.parametrize("debug_enabled", (False, True))
def test_debug_commands_require_both_opt_in_and_host(room, monkeypatch, command, debug_enabled):
    monkeypatch.setattr(main, "ENABLE_DEBUG_COMMANDS", debug_enabled)
    # No lifespan loop: only client messages advance state in these authorization tests.
    client = TestClient(main.app)
    with ExitStack() as stack:
        host, host_id = connect(stack, client, room["code"], "host")
        if debug_enabled:
            sender, _ = connect(stack, client, room["code"], "guest")
        else:
            sender = host
        room["weapon_pickups"].clear()
        room["players"][host_id]["kills"] = 3
        player_ids = set(room["players"])

        sender.send_json({"type": command, "player_id": host_id})
        receive_type(sender, "command_denied")

        assert room["weapon_pickups"] == []
        assert room["players"][host_id]["kills"] == 3
        assert set(room["players"]) == player_ids
        assert room["round_state"]["phase"] == "waiting"
        assert room["round_state"]["number"] == 0
        # Denial leaves the gameplay connection usable.
        sender.send_json({"type": "ping", "client_sent_at": 42})
        assert receive_type(sender, "pong")["client_sent_at"] == 42


def test_host_can_use_explicitly_enabled_development_commands(room, monkeypatch):
    monkeypatch.setattr(main, "ENABLE_DEBUG_COMMANDS", True)
    client = TestClient(main.app)
    with ExitStack() as stack:
        host, host_id = connect(stack, client, room["code"], "host")
        room["weapon_pickups"].clear()
        host.send_json({"type": "debug_reset_weapon_pickups"})
        host.send_json({"type": "ping"})
        receive_type(host, "pong")
        assert room["weapon_pickups"]

        room["players"][host_id]["kills"] = 3
        host.send_json({"type": "debug_reset_test_round"})
        host.send_json({"type": "ping"})
        receive_type(host, "pong")
        assert room["round_state"]["phase"] == "active"
        assert room["round_state"]["number"] == 1
        assert room["players"][host_id]["kills"] == 0


@pytest.mark.parametrize("payload", ("{", "[]", "null", '{"type": 12}'))
def test_malformed_messages_are_rejected_without_losing_connection(room, payload):
    client = TestClient(main.app)
    with ExitStack() as stack:
        socket, _ = connect(stack, client, room["code"], "host")
        socket.send_text(payload)
        receive_type(socket, "invalid_message")
        socket.send_json({"type": "ping", "client_sent_at": 42})
        assert receive_type(socket, "pong")["client_sent_at"] == 42
