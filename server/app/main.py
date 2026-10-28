from time import monotonic
from typing import Any

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


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def game_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "server_connected",
            "server_time": monotonic(),
        }
    )

    try:
        while True:
            message: dict[str, Any] = await websocket.receive_json()
            await websocket.send_json(
                {
                    "type": "message_received",
                    "original_type": message.get("type", "unknown"),
                    "server_time": monotonic(),
                }
            )
    except WebSocketDisconnect:
        return

