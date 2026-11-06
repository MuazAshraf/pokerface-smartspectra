#!/usr/bin/env bash
# Starts the FastAPI backend, waits until it is healthy, then launches Electron.
# Closing the app (or Ctrl+C) stops the backend too.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "Missing .env — copy .env.example to .env and add your keys."; exit 1; }
[ -d node_modules ] || npm install
(cd backend && uv sync --quiet)

if curl -sf -m 2 http://127.0.0.1:8000/health >/dev/null; then
    echo "Port 8000 is already in use (an old backend still running?). Close it and retry."
    exit 1
fi

npm run backend &
BACKEND_PID=$!

stop_backend() {
    # On Windows (Git Bash) kill only stops npm, not the Python server under it,
    # so end the whole process tree.
    if [ -r "/proc/$BACKEND_PID/winpid" ]; then
        taskkill //PID "$(cat /proc/$BACKEND_PID/winpid)" //T //F >/dev/null 2>&1 || true
    else
        pkill -P "$BACKEND_PID" 2>/dev/null || true
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
}
trap stop_backend EXIT
trap 'exit 130' INT TERM

for _ in $(seq 1 30); do
    curl -sf http://127.0.0.1:8000/health >/dev/null && break
    kill -0 $BACKEND_PID 2>/dev/null || { echo "Backend failed to start."; exit 1; }
    sleep 1
done
curl -sf http://127.0.0.1:8000/health >/dev/null || { echo "Backend did not become healthy in 30 s."; exit 1; }

# VS Code terminals can export this, which makes Electron run as plain Node.
unset ELECTRON_RUN_AS_NODE
npm start
