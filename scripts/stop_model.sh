#!/usr/bin/env bash
# Stop the persistent model server gracefully.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PID_FILE="logs/model_server.pid"

if python scripts/server_client.py shutdown; then
    echo "Shutdown request accepted."
else
    echo "Shutdown endpoint was not reachable." >&2
    if [ -f "$PID_FILE" ]; then
        PID="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [ -n "${PID:-}" ] && kill -0 "$PID" >/dev/null 2>&1; then
            ARGS="$(ps -p "$PID" -o args= 2>/dev/null || true)"
            if printf '%s' "$ARGS" | grep -q "model_server.py"; then
                echo "Sending SIGTERM to model_server.py PID $PID ..."
                kill -TERM "$PID" 2>/dev/null || true
            else
                echo "PID $PID does not look like model_server.py; refusing to kill it." >&2
                echo "Process args: $ARGS" >&2
                exit 1
            fi
        else
            echo "No live server process found for PID file."
        fi
    else
        echo "No PID file found; no local server process to stop."
    fi
fi

if [ -f "$PID_FILE" ]; then
    PID="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [ -n "${PID:-}" ]; then
        for _ in $(seq 1 20); do
            if ! kill -0 "$PID" >/dev/null 2>&1; then
                break
            fi
            sleep 0.5
        done
        if kill -0 "$PID" >/dev/null 2>&1; then
            ARGS="$(ps -p "$PID" -o args= 2>/dev/null || true)"
            if printf '%s' "$ARGS" | grep -q "model_server.py"; then
                echo "Server did not exit promptly; sending SIGTERM."
                kill -TERM "$PID" 2>/dev/null || true
            fi
        fi
    fi
    rm -f "$PID_FILE"
fi

echo "Stop sequence complete. Confirm with: bash scripts/check_model.sh"
