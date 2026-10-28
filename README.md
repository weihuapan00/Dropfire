# Dropfire

A browser-based, real-time 2D party shooter for 2-8 players.

> Drop in. Loot up. Be the last one standing.

## Project structure

```text
client/   Phaser + TypeScript + Vite
server/   FastAPI + WebSocket
```

## Run the server on Windows

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Run the client on Windows

```powershell
cd client
npm install
npm run dev -- --host 0.0.0.0
```

Open `http://localhost:5173` in a browser. The status indicator should change to
`Server connected`, and the player marker can be moved with WASD or the arrow keys.

## Run on macOS

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open another terminal:

```bash
cd client
npm install
npm run dev -- --host 0.0.0.0
```

