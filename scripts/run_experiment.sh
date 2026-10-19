#!/usr/bin/env bash
# Check the persistent server, then run one experiment in a fresh results directory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! python scripts/server_client.py health --quiet >/dev/null 2>&1; then
    echo "ERROR: the model server is not ready." >&2
    echo "Start it with:" >&2
    echo "  bash scripts/start_model.sh" >&2
    echo "Then check it with:" >&2
    echo "  bash scripts/check_model.sh" >&2
    exit 1
fi

exec python -u main.py --config config.json "$@"
