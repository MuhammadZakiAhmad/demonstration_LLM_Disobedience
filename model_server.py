"""Persistent local HTTP model server.

The server loads the model once and keeps it resident while experiment code is
edited and rerun in a separate process. Requests are accepted concurrently by
the HTTP layer, but inference is strictly serialized with a lock.

Endpoints
---------
GET  /health    readiness, model identity, EOS configuration, request counters
POST /generate  {"messages": [...], "generation_config": {...}, "seed": 42}
POST /shutdown  {"confirm": "shutdown"}

The server binds to localhost by default. A fake backend is available only for
protocol tests and is clearly reported as ``"fake"`` in health responses.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from environment_report import collect_environment
from run_utils import load_json, sha256_file

LOGGER = logging.getLogger("model_server")

MAX_REQUEST_BYTES = 1 * 1024 * 1024
LOCALHOST_NAMES = {"127.0.0.1", "localhost", "::1"}


class RequestValidationError(ValueError):
    """Raised for malformed client requests."""


class FakeBackend:
    """Deterministic backend for protocol tests; never used for real results."""

    def __init__(self, output: str | None = None, *, model_id: str = "fake/model"):
        self.output = output if output is not None else (
            "Subject: Protocol test\n\n"
            "This is a deterministic fake completion used only for server protocol tests."
        )
        self.model_id = model_id
        self.lock = threading.Lock()
        self.calls = 0

    def info(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_revision": "fake-revision",
            "tokenizer_id": self.model_id,
            "tokenizer_revision": "fake-revision",
            "precision": "none",
            "device": "cpu",
            "non_thinking_mode": True,
            "eos_token_ids": [151643, 151645],
            "pad_token_id": 151643,
            "warnings": ["Fake backend active. Results are not real model outputs."],
        }

    def generate(
        self,
        messages: list[dict[str, str]],
        generation_config: dict[str, Any],
        seed: int,
    ) -> dict[str, Any]:
        with self.lock:
            self.calls += 1
            call_number = self.calls
        text = f"{self.output}\n\n[fake call {call_number}, seed {seed}]"
        return {
            "generated_text": text,
            "finish_reason": "eos",
            "warnings": ["Fake backend active. Results are not real model outputs."],
            "metadata": {
                "model_id": self.model_id,
                "model_revision": "fake-revision",
                "precision": "none",
                "device": "cpu",
                "seed": seed,
                "prompt_tokens": sum(len(item["content"].split()) for item in messages),
                "generated_tokens": len(text.split()),
                "generation_duration_seconds": 0.0,
                "eos_token_ids": [151643, 151645],
                "pad_token_id": 151643,
                "non_thinking_mode": True,
                "repetition_heuristic": {"suspected_loop": False},
            },
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_generation_payload(payload: Any) -> tuple[list[dict[str, str]], dict[str, Any], int]:
    if not isinstance(payload, dict):
        raise RequestValidationError("request body must be a JSON object")

    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RequestValidationError("'messages' must be a non-empty array")
    if len(messages) > 8:
        raise RequestValidationError("'messages' may contain at most 8 entries")

    cleaned_messages: list[dict[str, str]] = []
    total_characters = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise RequestValidationError(f"messages[{index}] must be an object")
        role = message.get("role")
        content = message.get("content")
        if role not in ("system", "user"):
            raise RequestValidationError(
                f"messages[{index}].role must be 'system' or 'user'"
            )
        if not isinstance(content, str) or not content.strip():
            raise RequestValidationError(
                f"messages[{index}].content must be a non-empty string"
            )
        total_characters += len(content)
        cleaned_messages.append({"role": role, "content": content})
    if total_characters > 100_000:
        raise RequestValidationError("combined message content is too large")

    generation_config = payload.get("generation_config")
    if not isinstance(generation_config, dict):
        raise RequestValidationError("'generation_config' must be an object")
    allowed = {
        "max_new_tokens",
        "do_sample",
        "temperature",
        "top_p",
        "top_k",
        "repetition_penalty",
        "seed",
    }
    unknown = sorted(set(generation_config) - allowed)
    if unknown:
        raise RequestValidationError(f"unknown generation_config keys: {unknown}")

    max_new_tokens = generation_config.get("max_new_tokens")
    if (
        not isinstance(max_new_tokens, int)
        or isinstance(max_new_tokens, bool)
        or not 1 <= max_new_tokens <= 2048
    ):
        raise RequestValidationError("max_new_tokens must be an integer in [1, 2048]")

    do_sample = generation_config.get("do_sample")
    if not isinstance(do_sample, bool):
        raise RequestValidationError("do_sample must be a boolean")

    if do_sample:
        temperature = generation_config.get("temperature")
        if not isinstance(temperature, (int, float)) or not 0 < float(temperature) <= 2:
            raise RequestValidationError("temperature must be in (0, 2] when sampling")
        top_p = generation_config.get("top_p")
        if not isinstance(top_p, (int, float)) or not 0 < float(top_p) <= 1:
            raise RequestValidationError("top_p must be in (0, 1] when sampling")
        top_k = generation_config.get("top_k")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 0 <= top_k <= 200:
            raise RequestValidationError("top_k must be an integer in [0, 200]")

    repetition_penalty = generation_config.get("repetition_penalty", 1.0)
    if not isinstance(repetition_penalty, (int, float)) or not 0.5 <= float(
        repetition_penalty
    ) <= 2.0:
        raise RequestValidationError("repetition_penalty must be in [0.5, 2.0]")

    seed = payload.get("seed")
    if (
        not isinstance(seed, int)
        or isinstance(seed, bool)
        or not 0 <= seed < 2**31
    ):
        raise RequestValidationError("seed must be an integer in [0, 2**31)")

    config_seed = generation_config.get("seed")
    if config_seed is not None and (
        not isinstance(config_seed, int)
        or isinstance(config_seed, bool)
        or config_seed != seed
    ):
        raise RequestValidationError(
            "generation_config.seed, when present, must equal the request seed"
        )

    return cleaned_messages, dict(generation_config), seed


class ServerState:
    def __init__(
        self,
        backend: Any,
        *,
        host: str,
        port: int,
        config_sha256: str | None,
        backend_mode: str,
        environment: dict[str, Any] | None = None,
    ):
        self.backend = backend
        self.host = host
        self.port = port
        self.config_sha256 = config_sha256
        self.backend_mode = backend_mode
        self.environment = environment
        self.started_at_utc = _utc_now()
        self.started_monotonic = time.monotonic()
        self.generation_lock = threading.Lock()
        self.request_count = 0
        self.generation_count = 0
        self.last_error: dict[str, Any] | None = None
        self.shutting_down = False

    def health(self) -> dict[str, Any]:
        model_info = self.backend.info()
        return {
            "status": "shutting_down" if self.shutting_down else "ready",
            "backend_mode": self.backend_mode,
            "fake_backend": self.backend_mode == "fake",
            "pid": os.getpid(),
            "host": self.host,
            "port": self.port,
            "started_at_utc": self.started_at_utc,
            "uptime_seconds": round(time.monotonic() - self.started_monotonic, 3),
            "request_count": self.request_count,
            "generation_count": self.generation_count,
            "last_error": self.last_error,
            "config_sha256": self.config_sha256,
            "model": model_info,
            "environment": self.environment,
        }


class EvalHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], state: ServerState):
        self.state = state
        super().__init__(server_address, handler_class)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HyphenEvalModelServer/1.0"

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOGGER.info("%s - %s", self.client_address[0], format % args)

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)
        self.wfile.flush()

    def _read_json(self) -> Any:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            raise RequestValidationError("missing Content-Length header")
        try:
            length = int(content_length)
        except ValueError as exc:
            raise RequestValidationError("invalid Content-Length header") from exc
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise RequestValidationError(
                f"request body must be between 0 and {MAX_REQUEST_BYTES} bytes"
            )
        raw = self.rfile.read(length)
        if not raw:
            raise RequestValidationError("request body is empty")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestValidationError(f"request body is not valid JSON: {exc}") from exc

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/", "/health"):
            self._send_json(HTTPStatus.OK, self.state.health())
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"ok": False, "error": {"type": "not_found", "message": f"unknown path {path}"}},
        )

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path == "/generate":
            self._handle_generate()
            return
        if path == "/shutdown":
            self._handle_shutdown()
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"ok": False, "error": {"type": "not_found", "message": f"unknown path {path}"}},
        )

    def _handle_generate(self) -> None:
        self.state.request_count += 1
        try:
            payload = self._read_json()
            messages, generation_config, seed = _validate_generation_payload(payload)
        except RequestValidationError as exc:
            self.state.last_error = {
                "timestamp_utc": _utc_now(),
                "type": "request_validation",
                "message": str(exc),
            }
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"type": "request_validation", "message": str(exc)}},
            )
            return

        if self.state.shutting_down:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "ok": False,
                    "error": {"type": "shutting_down", "message": "server is shutting down"},
                },
            )
            return

        request_started = time.perf_counter()
        try:
            with self.state.generation_lock:
                if self.state.shutting_down:
                    raise RuntimeError("server is shutting down")
                result = self.state.backend.generate(messages, generation_config, seed)
            self.state.generation_count += 1
        except Exception as exc:
            self.state.last_error = {
                "timestamp_utc": _utc_now(),
                "type": type(exc).__name__,
                "message": str(exc),
            }
            LOGGER.error("Generation failed: %s: %s", type(exc).__name__, exc)
            LOGGER.debug("Generation traceback:\n%s", traceback.format_exc())
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                },
            )
            return

        result["request_metadata"] = {
            "server_request_duration_seconds": time.perf_counter() - request_started,
            "server_pid": os.getpid(),
        }
        self._send_json(HTTPStatus.OK, {"ok": True, "result": result})

    def _handle_shutdown(self) -> None:
        try:
            payload = self._read_json()
        except RequestValidationError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": {"type": "request_validation", "message": str(exc)}},
            )
            return
        if not isinstance(payload, dict) or payload.get("confirm") != "shutdown":
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": {
                        "type": "request_validation",
                        "message": "shutdown requires {\"confirm\": \"shutdown\"}",
                    },
                },
            )
            return
        if self.state.shutting_down:
            self._send_json(HTTPStatus.OK, {"ok": True, "message": "already shutting down"})
            return
        self.state.shutting_down = True
        LOGGER.info("Shutdown requested by %s", self.client_address[0])
        self._send_json(HTTPStatus.OK, {"ok": True, "message": "shutdown scheduled"})
        threading.Thread(target=self.server.shutdown, daemon=True).start()


def create_server(
    *,
    backend: Any,
    host: str,
    port: int,
    config_sha256: str | None,
    backend_mode: str,
    environment: dict[str, Any] | None = None,
    allow_non_localhost: bool = False,
) -> EvalHTTPServer:
    """Create (but do not start) the HTTP server. Port 0 selects a free port."""

    if not allow_non_localhost and host not in LOCALHOST_NAMES:
        raise ValueError(
            f"Refusing to bind to non-local host {host!r}. The model server must "
            "listen on localhost unless --allow-non-localhost is explicitly used."
        )
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise ValueError(f"Invalid port: {port!r}")

    state = ServerState(
        backend,
        host=host,
        port=port,
        config_sha256=config_sha256,
        backend_mode=backend_mode,
        environment=environment,
    )
    try:
        server = EvalHTTPServer((host, port), Handler, state)
    except OSError as exc:
        raise OSError(
            f"Could not bind the model server to {host}:{port}: {exc}. "
            "If the port is busy, stop the old server or change server.port in "
            "config.json."
        ) from exc
    state.port = int(server.server_address[1])
    return server


def _resolve_host_port(config: dict[str, Any], args: argparse.Namespace) -> tuple[str, int]:
    server_section = config.get("server")
    if not isinstance(server_section, dict):
        raise ValueError("config is missing the 'server' object")
    host = args.host or server_section.get("host", "127.0.0.1")
    port = args.port if args.port is not None else server_section.get("port", 8765)
    if not isinstance(host, str) or not host:
        raise ValueError("server.host must be a non-empty string")
    if not isinstance(port, int) or isinstance(port, bool):
        raise ValueError("server.port must be an integer")
    return host, port


def _build_backend(config: dict[str, Any], fake_model: bool) -> tuple[Any, str]:
    if fake_model:
        return FakeBackend(), "fake"
    from model_loader import load_model

    return load_model(config), "real"


def _configure_logging(level: str) -> None:
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--host", help="override server.host")
    parser.add_argument("--port", type=int, help="override server.port")
    parser.add_argument(
        "--fake-model",
        action="store_true",
        help="use the deterministic fake backend (protocol tests only)",
    )
    parser.add_argument(
        "--allow-non-localhost",
        action="store_true",
        help="explicitly allow binding beyond localhost",
    )
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)
    try:
        config = load_json(args.config)
    except Exception as exc:
        LOGGER.error("Could not read config %s: %s", args.config, exc)
        return 1
    if not isinstance(config, dict):
        LOGGER.error("config root must be a JSON object")
        return 1

    try:
        host, port = _resolve_host_port(config, args)
    except ValueError as exc:
        LOGGER.error("%s", exc)
        return 1

    try:
        config_hash = sha256_file(args.config)
        environment = collect_environment()
        backend, backend_mode = _build_backend(config, args.fake_model)
        server = create_server(
            backend=backend,
            host=host,
            port=port,
            config_sha256=config_hash,
            backend_mode=backend_mode,
            environment=environment,
            allow_non_localhost=args.allow_non_localhost,
        )
    except Exception as exc:
        LOGGER.error("SERVER STARTUP FAILED: %s: %s", type(exc).__name__, exc)
        LOGGER.debug("Startup traceback:\n%s", traceback.format_exc())
        return 1

    def request_shutdown(signum: int, _frame: Any) -> None:
        LOGGER.info("Signal %s received; shutting down", signum)
        server.state.shutting_down = True
        threading.Thread(target=server.shutdown, daemon=True).start()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            try:
                signal.signal(getattr(signal, signal_name), request_shutdown)
            except (ValueError, OSError):  # pragma: no cover - platform-specific
                pass

    actual_host, actual_port = server.server_address[0], server.server_address[1]
    LOGGER.info(
        "MODEL SERVER READY http://%s:%s backend=%s fake=%s pid=%s",
        actual_host,
        actual_port,
        backend_mode,
        backend_mode == "fake",
        os.getpid(),
    )
    if backend_mode == "fake":
        LOGGER.warning(
            "FAKE BACKEND ACTIVE: outputs are deterministic test strings, not model results."
        )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        LOGGER.info("KeyboardInterrupt; shutting down")
    finally:
        server.server_close()
        LOGGER.info("Model server stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
