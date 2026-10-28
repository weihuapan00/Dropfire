from math import hypot
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Dropfire Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: list[WebSocket] = []
players: dict[str, dict[str, float]] = {}
PLAYER_SPEED = 280.0
ARENA_MIN_X = 72.0
ARENA_MAX_X = 1208.0
ARENA_MIN_Y = 72.0
ARENA_MAX_Y = 608.0
MAX_MOVEMENT_STEP_SECONDS = 0.1


async def broadcast_world_state() -> None:
    """Send the complete current player list to every connected browser."""
    message = {
        "type": "world_state",
        "players": [
            {"id": player_id, "x": player["x"], "y": player["y"]}
            for player_id, player in players.items()
        ],
    }
    for connection in active_connections.copy():
        await connection.send_json(message)


def apply_move_intent(player: dict[str, float], message: dict[str, Any]) -> bool:
    """Apply one validated movement request using server time and server limits."""
    direction_x = message.get("direction_x")
    direction_y = message.get("direction_y")
    if not isinstance(direction_x, (int, float)) or not isinstance(direction_y, (int, float)):
        return False

    direction_length = hypot(direction_x, direction_y)
    if direction_length == 0:
        return False

    now = monotonic()
    elapsed = min(now - player["last_move_at"], MAX_MOVEMENT_STEP_SECONDS)
    distance = PLAYER_SPEED * elapsed
    player["x"] = max(ARENA_MIN_X, min(ARENA_MAX_X, player["x"] + direction_x / direction_length * distance))
    player["y"] = max(ARENA_MIN_Y, min(ARENA_MAX_Y, player["y"] + direction_y / direction_length * distance))
    player["last_move_at"] = now
    return True


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def game_socket(websocket: WebSocket) -> None:
    player_id = uuid4().hex
    await websocket.accept()
    active_connections.append(websocket)
    player_number = len(players)
    players[player_id] = {
        "x": 640 + player_number * 60,
        "y": 360,
        "last_move_at": monotonic(),
    }

    await websocket.send_json(
        {
            "type": "server_connected",
            "player_id": player_id,
            "server_time": monotonic(),
        }
    )
    await broadcast_world_state()

    try:
        while True:
            message: dict[str, Any] = await websocket.receive_json()
            if message.get("type") == "move_intent":
                if apply_move_intent(players[player_id], message):
                    await broadcast_world_state()
                continue

            await websocket.send_json(
                {
                    "type": "message_received",
                    "original_type": message.get("type", "unknown"),
                    "server_time": monotonic(),
                }
            )
    except WebSocketDisconnect:
        pass
    finally:
        active_connections.remove(websocket)
        players.pop(player_id, None)
        await broadcast_world_state()

