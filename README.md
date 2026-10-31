# Dropfire

A browser-based, real-time 2D arena shooter for 2–8 players. Create a
room, share its six-character code, add AI opponents if needed, then compete
to finish the Gun Game weapon progression first.

## Play online

**[Play Dropfire →](https://dropfire.wpdatasoft.com/)**

The live game is served from an Oracle-hosted production server. Pushes to
`main` run GitHub Actions checks. Production deployment is triggered manually
from the **Deploy** workflow.

## Gameplay

- Create or join a room with a six-character code. Rooms are publicly listed
  in the lobby; the code is a shortcut for joining, not an access restriction.
- The host can add AI bots and start once at least two players are present.
- Humans and bots start with pistols: pistol → shotgun → rifle → sniper → knife.
  Each stage kill advances your weapon; the final knife kill wins. Death preserves the current weapon stage.
- No match timer or ground weapons; medkits still spawn. Old-stage bullets
  can score kills but cannot skip the next stage.
- The server owns movement, combat, pickups, respawns, round state, and bot
  behaviour, so every connected player sees the same shared world.

### Controls

| Platform | Controls |
| --- | --- |
| Desktop | `WASD` / arrow keys to move; mouse to aim and fire; `E` to pick up; `R` to reload |
| Mobile | Left stick to move; right stick to aim and fire; on-screen **PICK** (medkits) and **RELOAD** buttons |

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

On macOS/Linux, install Python 3 and Node.js, then run from the project root:

```bash
./dev.sh
```

The script creates the Python virtual environment, installs dependencies on the
first run (and when manifests change), then starts both services with live reload.
Open [http://localhost:5173](http://localhost:5173). Press **Ctrl+C** to stop both.
Use `./dev.sh --server-only` to start just the backend. Ports 8000 and 5173 must
be available. For manual setup or Windows, follow the steps below.

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
cd client && npm test && npm run typecheck && npm run build
cd ../server && python -m pip install -r requirements-dev.txt && pytest -q
```

## Deployment

Development-only WebSocket commands are disabled by default. For local debugging,
start the server with `DROPFIRE_ENABLE_DEBUG_COMMANDS=1`; even then, only the room
host can run them. Leave this unset on the public server.

[CI](.github/workflows/ci.yml) runs client checks/builds and server tests on
pushes and pull requests to `main`. Pushes do not deploy the game.

To publish an update, open **GitHub → Actions → Deploy → Run workflow**, select
`main`, then click **Run workflow**. The [Deploy](.github/workflows/deploy.yml)
workflow reruns CI and, if successful, deploys that exact commit to Oracle,
builds the client, restarts FastAPI, and checks `/api/health`. Deployments from
other branches are skipped. Deployment uses the existing production secrets.

Deployment snapshots the previous commit, Python virtual environment, and
published frontend before making changes. A build, restart, or health-check
failure automatically restores those snapshots and checks the old service.
Actions still reports failure after a successful rollback. If rollback fails,
the server retains the snapshot and logs its location for manual recovery.
The server checkout must have no tracked edits and pass its initial health check.
A restart still disconnects players and clears in-memory rooms. Automatic rollback
covers script errors, not forced termination, host failure, or database migrations.
