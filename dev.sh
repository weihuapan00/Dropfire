#!/usr/bin/env bash
set -euo pipefail

# Resolve paths relative to this file, so it also works from another directory.
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVER_ONLY=false
case "${1:-}" in
  --server-only) SERVER_ONLY=true ;;
  --help|-h)
    echo "Usage: ./dev.sh [--server-only]"
    echo "Starts the local game (API :8000, browser :5173). Ctrl+C stops both."
    exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1. Try ./dev.sh --help" >&2; exit 1 ;;
esac

command -v python3 >/dev/null || { echo "Install Python 3 first." >&2; exit 1; }
if ! "$SERVER_ONLY"; then
  command -v npm >/dev/null || { echo "Install Node.js and npm first." >&2; exit 1; }
fi

# Fail clearly instead of connecting the browser to an unrelated old server.
python3 - "$SERVER_ONLY" <<'PY'
import socket
import sys

ports = [8000] if sys.argv[1] == "true" else [8000, 5173]
for port in ports:
    with socket.socket() as probe:
        try:
            probe.bind(("0.0.0.0", port))
        except OSError:
            sys.exit(f"Port {port} is unavailable. Stop the existing server and try again.")
PY

cd "$ROOT/server"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if [[ ! -f .venv/.dropfire-deps-ready || requirements.txt -nt .venv/.dropfire-deps-ready ]]; then
  .venv/bin/python -m pip install -r requirements.txt
  touch .venv/.dropfire-deps-ready
fi

if ! "$SERVER_ONLY"; then
  cd "$ROOT/client"
  if [[ ! -f node_modules/.dropfire-deps-ready || package.json -nt node_modules/.dropfire-deps-ready || package-lock.json -nt node_modules/.dropfire-deps-ready ]]; then
    npm ci
    touch node_modules/.dropfire-deps-ready
  fi
fi

# Python owns each process group (including reload workers). Kill only those
# groups on exit; never kill arbitrary processes that happen to use our ports.
children=()
cleanup() {
  trap - EXIT INT TERM
  for pid in "${children[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done
  for pid in "${children[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start() {
  python3 - "$@" <<'PY' &
import os
import sys

os.setsid()
os.execvp(sys.argv[1], sys.argv[1:])
PY
  children+=("$!")
}

cd "$ROOT/server"
start "$ROOT/server/.venv/bin/python" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
if ! "$SERVER_ONLY"; then
  cd "$ROOT/client"
  start npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
  echo "Game: http://localhost:5173"
fi
echo "API:  http://localhost:8000/api/health"
echo "Press Ctrl+C to stop."

# Bash 3.2 (the macOS default) has no wait -n. Stop the other service if either
# process exits, so a failed start never leaves half the game running.
while true; do
  for pid in "${children[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid"
      exit 1
    fi
  done
  sleep 1
done
