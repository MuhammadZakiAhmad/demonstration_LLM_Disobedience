#!/usr/bin/env python
"""Minimal client for the local model server health check and shutdown."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _base_url(config_path: Path) -> str:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    server = config.get("server")
    if not isinstance(server, dict):
        raise ValueError("config.json has no 'server' object")
    host = server.get("host", "127.0.0.1")
    port = server.get("port", 8765)
    if host in ("localhost", "::1"):
        host = "127.0.0.1"
    return f"http://{host}:{port}"


def _request(url: str, method: str, payload: dict | None, timeout: float) -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("health", "shutdown"))
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    if not args.config.is_file():
        print(f"ERROR: config not found: {args.config}", file=sys.stderr)
        return 1
    try:
        base_url = _base_url(args.config)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        if args.command == "health":
            status, payload = _request(f"{base_url}/health", "GET", None, args.timeout)
            if args.quiet:
                return 0 if payload.get("status") == "ready" else 1
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if status == 200 and payload.get("status") == "ready" else 1

        status, payload = _request(
            f"{base_url}/shutdown",
            "POST",
            {"confirm": "shutdown"},
            args.timeout,
        )
        if not args.quiet:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if status == 200 and payload.get("ok") else 1
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"ERROR: HTTP {exc.code}: {body}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(
            f"ERROR: could not reach {base_url}: {exc.reason}. "
            "Start the server with: bash scripts/start_model.sh",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
