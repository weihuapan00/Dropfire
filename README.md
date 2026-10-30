# Dropfire

A browser-based, real-time 2D arena shooter for 2–8 players. Create a private
room, share its six-character code, add AI opponents if needed, then compete
for the most kills before the three-minute match ends.

## Play online

**[Play Dropfire →](https://dropfire.wpdatasoft.com/)**

The live game is served from an Oracle-hosted production server. Pushes to
`main` run the GitHub Actions checks and then deploy the client and FastAPI
server automatically.

## Gameplay

- Create or join a private room with a six-character invite code.
- The host can add AI bots and start once at least two players are present.
- Every player starts with a knife. Find pistols or rifles around the arena.
- A match lasts three minutes; kills rank first, then total damage breaks ties.
- The server owns movement, combat, pickups, respawns, round state, and bot
  behaviour, so every connected player sees the same shared world.

### Controls

| Platform | Controls |
| --- | --- |
| Desktop | `WASD` / arrow keys to move; mouse to aim and fire; `E` to pick up; `R` to reload |
| Mobile | Left stick to move; right side to aim and fire; on-screen **PICK** and **RELOAD** buttons |

## Architecture

```text
client/                    Phaser + TypeScript + Vite
  src/game/                Arena rendering and input
  src/network/             WebSocket client
server/                    FastAPI + authoritative WebSocket server
  app/config.py            Arena and rule tuning
  app/state.py             Per-room in-memory state
  app/rules.py             Combat, movement, pickup and round rules
  app/bots.py              AI and bot lifecycle
  app/main.py              HTTP/WebSocket wiring and fixed-rate game loop
```

The client sends player **intent**; the server validates and advances shared
state at a fixed tick rate before broadcasting snapshots to connected players.

## Run locally

### 1. Start the server

macOS/Linux:

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Windows PowerShell:

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Start the client

In a second terminal:

```bash
cd client
npm install
npm run dev -- --host 0.0.0.0
```

Open [http://localhost:5173](http://localhost:5173). Create a room in one
browser, then join its room code from another browser or device on the same
network.

## Verify changes

```bash
cd client && npm run typecheck && npm run build
cd ../server && python -m pip install -r requirements-dev.txt && pytest -q
```

## Deployment

The workflow in [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml)
runs client type checks/builds and server tests for pull requests. A successful
push to `main` deploys to the production Oracle host, builds the Vite client,
restarts the FastAPI service, and checks `/api/health` before reporting success.
