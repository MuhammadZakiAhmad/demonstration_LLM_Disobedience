#!/usr/bin/env bash
# Start the persistent model server in the background and wait for readiness.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs results

PID_FILE="logs/model_server.pid"
LOG_FILE="logs/model_server.log"

if python scripts/server_client.py health --quiet >/dev/null 2>&1; then
    echo "Model server is already running and healthy."
    python scripts/server_client.py health
    exit 0
fi

if [ -f "$PID_FILE" ]; then
    OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${OLD_PID:-}" ] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
        echo "A process with PID $OLD_PID is alive but is not answering the health check."
        echo "Inspect $LOG_FILE. If it is a stale/unrelated process, stop it and retry."
        exit 1
    fi
    echo "Removing stale PID file."
    rm -f "$PID_FILE"
fi

TIMEOUT_SECONDS="$(python - <<'PY'
import json
from pathlib import Path
config = json.loads(Path("config.json").read_text(encoding="utf-8"))
print(int(config.get("server", {}).get("startup_timeout_seconds", 600)))
PY
)"

echo "Starting model server. Log: $LOG_FILE"
nohup python -u model_server.py --config config.json >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" >"$PID_FILE"
echo "Started PID $SERVER_PID. Waiting up to ${TIMEOUT_SECONDS}s for the health check ..."

START_TIME="$(date +%s)"
while true; do
    if python scripts/server_client.py health --quiet >/dev/null 2>&1; then
        echo
        echo "Model server is ready."
        python scripts/server_client.py health
        exit 0
    fi

    if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
        echo
        echo "ERROR: model server exited during startup. Last log lines:" >&2
        tail -n 40 "$LOG_FILE" >&2 || true
        rm -f "$PID_FILE"
        exit 1
    fi

    NOW="$(date +%s)"
    if [ $((NOW - START_TIME)) -ge "$TIMEOUT_SECONDS" ]; then
        echo
        echo "ERROR: model server did not become ready within ${TIMEOUT_SECONDS}s." >&2
        echo "Last log lines:" >&2
        tail -n 40 "$LOG_FILE" >&2 || true
        echo "The process is still running. Inspect the log, then stop it with:" >&2
        echo "  bash scripts/stop_model.sh" >&2
        exit 1
    fi

    sleep 5
done
