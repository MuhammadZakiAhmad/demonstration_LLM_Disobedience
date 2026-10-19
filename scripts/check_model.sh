#!/usr/bin/env bash
# Print model-server health details. Exits non-zero if the server is not ready.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if python scripts/server_client.py health; then
    echo
    echo "Server is ready."
else
    echo
    echo "Server is not ready. Start it with:" >&2
    echo "  bash scripts/start_model.sh" >&2
    echo "Inspect the log with:" >&2
    echo "  tail -n 50 logs/model_server.log" >&2
    exit 1
fi
