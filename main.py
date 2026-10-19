"""Experiment runner.

This process never imports torch or transformers and never loads the model. It
validates the experiment, connects to the already-running local model server,
writes one immutable run directory, and records every attempted trial
incrementally.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import reporting
import scoring
from environment_report import collect_environment, format_environment_text
from generation_utils import GenerationConfigError
from model_server import LOCALHOST_NAMES
from prompt_validation import (
    PromptValidationError,
    load_prompts,
    select_prompts,
    summarize_prompt_set,
)
from run_utils import (
    append_jsonl,
    copy_file_atomic,
    create_run_directory,
    get_git_commit,
    get_git_dirty,
    load_json,
    sha256_file,
    stable_trial_seed,
    utc_now_iso,
    write_json_atomic,
    write_text_atomic,
)

LOGGER = logging.getLogger("experiment")
SCHEMA_VERSION = "1.0"
START_COMMAND = "bash scripts/start_model.sh"
CHECK_COMMAND = "bash scripts/check_model.sh"
STOP_COMMAND = "bash scripts/stop_model.sh"

CONFIG_WARNING_KEYS = {
    "schema_version",
    "_config_dir",
    "model",
    "generation",
    "experiment",
    "server",
    "results",
    "scoring",
    "reporting",
    "known_deviations",
}


class ConfigValidationError(ValueError):
    """Raised for invalid config.json content."""


class ServerUnavailableError(RuntimeError):
    """Raised when the local model server cannot be reached."""


class ServerResponseError(RuntimeError):
    """Raised when the model server returns an error or malformed response."""

    def __init__(self, message: str, *, error_type: str = "server_error"):
        self.error_type = error_type
        super().__init__(message)


class ServerClient:
    def __init__(self, host: str, port: int, timeout_seconds: float):
        if host in ("localhost", "::1"):
            host_for_url = "127.0.0.1"
        else:
            host_for_url = host
        self.base_url = f"http://{host_for_url}:{port}"
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            body = exc.read()
            message = body.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(message)
                error = parsed.get("error") or {}
                error_type = str(error.get("type") or "http_error")
                detail = str(error.get("message") or message)
            except (json.JSONDecodeError, AttributeError):
                error_type = "http_error"
                detail = message
            raise ServerResponseError(
                f"HTTP {exc.code} from server: {detail}",
                error_type=error_type,
            ) from exc
        except URLError as exc:
            raise ServerUnavailableError(
                f"Could not reach the model server at {self.base_url}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise ServerUnavailableError(
                f"Timed out waiting for the model server at {self.base_url} "
                f"after {self.timeout_seconds:.0f}s"
            ) from exc
        except OSError as exc:
            raise ServerUnavailableError(
                f"Could not reach the model server at {self.base_url}: {exc}"
            ) from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServerResponseError(
                f"Server returned non-JSON response: {exc}", error_type="invalid_response"
            ) from exc
        if not isinstance(parsed, dict):
            raise ServerResponseError(
                "Server response must be a JSON object", error_type="invalid_response"
            )
        return parsed

    def health(self) -> dict[str, Any]:
        payload = self._request("GET", "/health")
        if not isinstance(payload, dict) or "status" not in payload:
            raise ServerResponseError(
                "Health response is missing 'status'", error_type="invalid_response"
            )
        return payload

    def generate(
        self,
        messages: list[dict[str, str]],
        generation_config: dict[str, Any],
        seed: int,
    ) -> dict[str, Any]:
        payload = self._request(
            "POST",
            "/generate",
            {
                "messages": messages,
                "generation_config": generation_config,
                "seed": seed,
            },
        )
        if not payload.get("ok"):
            error = payload.get("error") or {}
            raise ServerResponseError(
                str(error.get("message") or "server generation failed"),
                error_type=str(error.get("type") or "generation_error"),
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ServerResponseError(
                "Generate response is missing 'result'", error_type="invalid_response"
            )
        if not isinstance(result.get("generated_text"), str):
            raise ServerResponseError(
                "Generate response is missing generated_text",
                error_type="invalid_response",
            )
        if not isinstance(result.get("metadata"), dict):
            result["metadata"] = {}
        if not isinstance(result.get("warnings"), list):
            result["warnings"] = []
        return result


def _require_object(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ConfigValidationError(f"config.{key} must be an object")
    return value


def _require_string(section: dict[str, Any], key: str, prefix: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigValidationError(f"{prefix}.{key} must be a non-empty string")
    return value


def _require_bool(section: dict[str, Any], key: str, prefix: str) -> bool:
    value = section.get(key)
    if not isinstance(value, bool):
        raise ConfigValidationError(f"{prefix}.{key} must be true or false")
    return value


def _require_int(
    section: dict[str, Any],
    key: str,
    prefix: str,
    minimum: int,
    maximum: int,
) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ConfigValidationError(
            f"{prefix}.{key} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize configuration, resolving paths from the config dir."""

    if not isinstance(config, dict):
        raise ConfigValidationError("config root must be a JSON object")

    unknown_top = sorted(set(config) - CONFIG_WARNING_KEYS)
    if unknown_top:
        raise ConfigValidationError(f"unknown top-level config keys: {unknown_top}")

    model = _require_object(config, "model")
    model_id = _require_string(model, "id", "model")
    revision = _require_string(model, "revision", "model")
    tokenizer_id = _require_string(model, "tokenizer_id", "model")
    tokenizer_revision = _require_string(model, "tokenizer_revision", "model")
    precision = _require_string(model, "precision", "model")
    if precision not in ("float16", "bfloat16", "float32", "auto"):
        raise ConfigValidationError(
            "model.precision must be one of: float16, bfloat16, float32, auto"
        )
    device = _require_string(model, "device", "model")
    if device != "cpu" and not (device == "cuda" or device.startswith("cuda:")):
        raise ConfigValidationError("model.device must be 'cpu', 'cuda', or 'cuda:<index>'")
    if _require_bool(model, "non_thinking_mode", "model") is not True:
        raise ConfigValidationError(
            "model.non_thinking_mode must be true for the primary experiment"
        )
    trust_remote_code = _require_bool(model, "trust_remote_code", "model")
    min_free = model.get("min_free_gpu_memory_gb", 0.0)
    if not isinstance(min_free, (int, float)) or isinstance(min_free, bool) or min_free < 0:
        raise ConfigValidationError("model.min_free_gpu_memory_gb must be >= 0")

    generation = _require_object(config, "generation")
    max_new_tokens = _require_int(generation, "max_new_tokens", "generation", 1, 2048)
    do_sample = _require_bool(generation, "do_sample", "generation")
    seed = _require_int(generation, "seed", "generation", 0, 2**31 - 1)
    repetition_penalty = generation.get("repetition_penalty", 1.0)
    if (
        not isinstance(repetition_penalty, (int, float))
        or isinstance(repetition_penalty, bool)
        or not 0.5 <= float(repetition_penalty) <= 2.0
    ):
        raise ConfigValidationError("generation.repetition_penalty must be in [0.5, 2.0]")
    normalized_generation: dict[str, Any] = {
        "max_new_tokens": max_new_tokens,
        "do_sample": do_sample,
        "seed": seed,
        "repetition_penalty": float(repetition_penalty),
    }
    if do_sample:
        temperature = generation.get("temperature")
        if not isinstance(temperature, (int, float)) or not 0 < float(temperature) <= 2:
            raise ConfigValidationError(
                "generation.temperature must be in (0, 2] when do_sample is true"
            )
        top_p = generation.get("top_p")
        if not isinstance(top_p, (int, float)) or not 0 < float(top_p) <= 1:
            raise ConfigValidationError(
                "generation.top_p must be in (0, 1] when do_sample is true"
            )
        top_k = generation.get("top_k")
        if not isinstance(top_k, int) or isinstance(top_k, bool) or not 0 <= top_k <= 200:
            raise ConfigValidationError(
                "generation.top_k must be an integer in [0, 200] when do_sample is true"
            )
        normalized_generation.update(
            {
                "temperature": float(temperature),
                "top_p": float(top_p),
                "top_k": int(top_k),
            }
        )

    experiment = _require_object(config, "experiment")
    prompts_path = _require_string(experiment, "prompts_path", "experiment")
    repetitions = _require_int(experiment, "repetitions", "experiment", 1, 1000)
    include_prompt_ids = experiment.get("include_prompt_ids", [])
    include_categories = experiment.get("include_categories", [])
    for name, values in (
        ("include_prompt_ids", include_prompt_ids),
        ("include_categories", include_categories),
    ):
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ConfigValidationError(f"experiment.{name} must be an array of strings")
    output_extraction = experiment.get("output_extraction", {"enabled": False, "method": "none"})
    if not isinstance(output_extraction, dict):
        raise ConfigValidationError("experiment.output_extraction must be an object")
    if output_extraction.get("enabled", False):
        raise ConfigValidationError(
            "experiment.output_extraction.enabled=true is not implemented. Primary "
            "scoring applies to raw_generated_text. Set enabled to false."
        )

    server = _require_object(config, "server")
    host = _require_string(server, "host", "server")
    if host not in LOCALHOST_NAMES:
        raise ConfigValidationError(
            f"server.host must be a localhost name for this experiment, got {host!r}"
        )
    port = _require_int(server, "port", "server", 1, 65535)
    timeout_seconds = server.get("request_timeout_seconds", 300)
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ConfigValidationError("server.request_timeout_seconds must be > 0")
    startup_timeout = server.get("startup_timeout_seconds", 600)
    if not isinstance(startup_timeout, (int, float)) or startup_timeout <= 0:
        raise ConfigValidationError("server.startup_timeout_seconds must be > 0")
    max_consecutive_failures = _require_int(
        server, "max_consecutive_failures", "server", 1, 100
    )

    results = _require_object(config, "results")
    results_directory = _require_string(results, "directory", "results")

    scoring_section = _require_object(config, "scoring")
    scoring_version = _require_string(scoring_section, "version", "scoring")
    if scoring_version != scoring.SCORING_VERSION:
        raise ConfigValidationError(
            f"config scoring.version={scoring_version!r} does not match the "
            f"implemented scoring version {scoring.SCORING_VERSION!r}"
        )

    reporting_section = _require_object(config, "reporting")
    show_outputs = _require_bool(reporting_section, "show_outputs", "reporting")
    color = _require_string(reporting_section, "color", "reporting")
    if color not in ("auto", "always", "never"):
        raise ConfigValidationError("reporting.color must be auto, always, or never")
    max_output_chars = _require_int(
        reporting_section, "max_output_chars", "reporting", 0, 10_000_000
    )

    known_deviations = config.get("known_deviations", [])
    if not isinstance(known_deviations, list) or any(
        not isinstance(item, str) for item in known_deviations
    ):
        raise ConfigValidationError("known_deviations must be an array of strings")

    base_dir = Path(config.get("_config_dir", ".")).resolve()
    prompts_file = Path(prompts_path)
    if not prompts_file.is_absolute():
        prompts_file = (base_dir / prompts_file).resolve()
    results_dir = Path(results_directory)
    if not results_dir.is_absolute():
        results_dir = (base_dir / results_dir).resolve()

    normalized = {
        "model": {
            "id": model_id,
            "revision": revision,
            "tokenizer_id": tokenizer_id,
            "tokenizer_revision": tokenizer_revision,
            "precision": precision,
            "device": device,
            "trust_remote_code": trust_remote_code,
            "non_thinking_mode": True,
            "min_free_gpu_memory_gb": float(min_free),
        },
        "generation": normalized_generation,
        "experiment": {
            "prompts_path": str(prompts_file),
            "repetitions": repetitions,
            "include_prompt_ids": list(include_prompt_ids),
            "include_categories": list(include_categories),
            "output_extraction": {"enabled": False, "method": "none"},
        },
        "server": {
            "host": host,
            "port": port,
            "startup_timeout_seconds": float(startup_timeout),
            "request_timeout_seconds": float(timeout_seconds),
            "max_consecutive_failures": max_consecutive_failures,
        },
        "results": {"directory": str(results_dir)},
        "scoring": {"version": scoring.SCORING_VERSION},
        "reporting": {
            "show_outputs": show_outputs,
            "color": color,
            "max_output_chars": max_output_chars,
        },
        "known_deviations": list(known_deviations),
    }
    return normalized


def _model_matches(health: dict[str, Any], model: dict[str, Any], config_hash: str) -> list[str]:
    problems: list[str] = []
    if health.get("status") != "ready":
        problems.append(f"server status is {health.get('status')!r}, not 'ready'")
    if health.get("fake_backend"):
        problems.append(
            "server is running the fake test backend; it cannot produce experiment results"
        )
    if health.get("backend_mode") != "real":
        problems.append(
            f"server backend_mode is {health.get('backend_mode')!r}, expected 'real'"
        )

    server_model = health.get("model")
    if not isinstance(server_model, dict):
        problems.append("health response has no model information")
        return problems

    comparisons = (
        ("model_id", model["id"]),
        ("model_revision", model["revision"]),
        ("tokenizer_id", model["tokenizer_id"]),
        ("tokenizer_revision", model["tokenizer_revision"]),
        ("precision", model["precision"]),
    )
    for field, expected in comparisons:
        actual = server_model.get(field)
        if actual != expected:
            problems.append(f"{field} mismatch: server={actual!r}, config={expected!r}")

    server_device = str(server_model.get("device"))
    expected_device = model["device"]
    if expected_device == "cuda" and server_device == "cuda:0":
        pass
    elif server_device != expected_device:
        problems.append(
            f"device mismatch: server={server_device!r}, config={expected_device!r}"
        )

    if server_model.get("non_thinking_mode") is not True:
        problems.append("server is not in non-thinking mode")
    eos_ids = server_model.get("eos_token_ids")
    if not isinstance(eos_ids, list) or not eos_ids:
        problems.append("server did not report a non-empty EOS token id list")
    if health.get("config_sha256") and health.get("config_sha256") != config_hash:
        # Not fatal: the file may have changed only in reporting fields, but the
        # mismatch is recorded in the manifest for auditability.
        pass
    return problems


def _setup_file_logging(run_dir: Path) -> logging.Handler:
    handler = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime
    handler.setFormatter(formatter)
    logger = logging.getLogger("experiment")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return handler


def _write_manifest(run_dir: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at_utc"] = utc_now_iso()
    write_json_atomic(run_dir / "run_manifest.json", manifest)


def _initial_manifest(
    *,
    run_id: str,
    config_path: Path,
    config_hash: str,
    prompts_path: Path,
    prompt_hash: str,
    prompts: list[dict[str, Any]],
    planned_trials: int,
    config: dict[str, Any],
    environment: dict[str, Any],
    health: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    server_health = dict(health)
    server_environment = server_health.pop("environment", None)
    warnings = [
        "Prompt count is {}; the PRD suggests 30 to 50. This is a documented deviation.".format(
            len(prompts)
        )
    ] if not 30 <= len(prompts) <= 50 else []
    if health.get("config_sha256") and health.get("config_sha256") != config_hash:
        warnings.append(
            "The running server was started with a different config.json hash. "
            "Model identity fields were verified independently; restart the server "
            "after changing model/device/precision settings."
        )
    for warning in (health.get("model") or {}).get("warnings", []) or []:
        warnings.append(f"Server: {warning}")

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "start_time_utc": utc_now_iso(),
        "end_time_utc": None,
        "updated_at_utc": utc_now_iso(),
        "status": "running",
        "git_commit": get_git_commit(config_path.parent),
        "git_dirty": get_git_dirty(config_path.parent),
        "model": {
            "id": config["model"]["id"],
            "revision": config["model"]["revision"],
            "tokenizer_id": config["model"]["tokenizer_id"],
            "tokenizer_revision": config["model"]["tokenizer_revision"],
            "precision": config["model"]["precision"],
            "device": config["model"]["device"],
            "non_thinking_mode": config["model"]["non_thinking_mode"],
        },
        "generation_config": dict(config["generation"]),
        "experiment": {
            "prompts_path": str(prompts_path),
            "repetitions": config["experiment"]["repetitions"],
            "include_prompt_ids": config["experiment"]["include_prompt_ids"],
            "include_categories": config["experiment"]["include_categories"],
            "output_extraction": config["experiment"]["output_extraction"],
        },
        "prompt_file": {
            "path": str(prompts_path),
            "sha256": prompt_hash,
        },
        "config_file": {
            "path": str(config_path),
            "sha256": config_hash,
        },
        "prompt_set": summarize_prompt_set(prompts),
        "total_prompts_selected": len(prompts),
        "counts": {
            "planned_trials": planned_trials,
            "attempted_trials": 0,
            "successful": 0,
            "failed": 0,
            "compliant": 0,
            "violating": 0,
            "interrupted": False,
        },
        "scoring": {
            "version": scoring.SCORING_VERSION,
            "rule": (
                "Successful generations containing at least one literal ASCII "
                "hyphen-minus (U+002D) are violations. En dash, em dash, and Unicode "
                "minus do not count. No normalization is applied."
            ),
            "scored_text_source": "raw_generated_text",
        },
        "environment": environment,
        "server": server_health,
        "server_environment": server_environment,
        "overrides": overrides,
        "warnings": warnings,
        "known_deviations": list(config.get("known_deviations", [])),
        "error": None,
        "summary_error": None,
        "output_files": [
            "run_manifest.json",
            "trials.jsonl",
            "violations.jsonl",
            "errors.jsonl",
            "summary.json",
            "environment.txt",
            "report.md",
            "outputs.md",
            "run.log",
            "prompts_snapshot.jsonl",
            "config_snapshot.json",
        ],
    }


def _trial_error_record(
    *,
    run_id: str,
    trial_id: str,
    prompt: dict[str, Any],
    trial_index: int,
    timestamp: str,
    config: dict[str, Any],
    generation_config: dict[str, Any] | None,
    error_type: str,
    error_message: str,
    duration: float,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "trial_id": trial_id,
        "prompt_id": prompt["prompt_id"],
        "category": prompt["category"],
        "prompt_variant": prompt["prompt_variant"],
        "trial_index": trial_index,
        "timestamp_utc": timestamp,
        "model_id": config["model"]["id"],
        "model_revision": config["model"]["revision"],
        "generation_config": generation_config,
        "system_instruction": prompt["system_instruction"],
        "user_prompt": prompt["user_prompt"],
        "expected_output_type": prompt.get("expected_output_type", "email"),
        "raw_generated_text": None,
        "extracted_email_text": None,
        "generation_status": "error",
        "error": {"type": error_type, "message": error_message},
        "finish_reason": None,
        "warnings": [],
        "contains_ascii_hyphen": None,
        "ascii_hyphen_count": None,
        "violation_positions": None,
        "violation_contexts": None,
        "is_compliant": None,
        "generation_duration_seconds": duration,
    }


def _trial_success_record(
    *,
    run_id: str,
    trial_id: str,
    prompt: dict[str, Any],
    trial_index: int,
    timestamp: str,
    config: dict[str, Any],
    generation_config: dict[str, Any],
    result: dict[str, Any],
    duration: float,
) -> dict[str, Any]:
    raw_text = result["generated_text"]
    score = scoring.score_text(raw_text)
    metadata = dict(result.get("metadata") or {})
    metadata["request_metadata"] = result.get("request_metadata") or {}
    warnings = list(result.get("warnings") or [])
    return {
        "run_id": run_id,
        "trial_id": trial_id,
        "prompt_id": prompt["prompt_id"],
        "category": prompt["category"],
        "prompt_variant": prompt["prompt_variant"],
        "trial_index": trial_index,
        "timestamp_utc": timestamp,
        "model_id": metadata.get("model_id", config["model"]["id"]),
        "model_revision": metadata.get("model_revision", config["model"]["revision"]),
        "generation_config": generation_config,
        "system_instruction": prompt["system_instruction"],
        "user_prompt": prompt["user_prompt"],
        "expected_output_type": prompt.get("expected_output_type", "email"),
        "raw_generated_text": raw_text,
        "extracted_email_text": None,
        "generation_status": "success",
        "error": None,
        "finish_reason": result.get("finish_reason", "unknown"),
        "warnings": warnings,
        "contains_ascii_hyphen": score["contains_ascii_hyphen"],
        "ascii_hyphen_count": score["ascii_hyphen_count"],
        "violation_positions": score["violation_positions"],
        "violation_contexts": score["violation_contexts"],
        "is_compliant": score["is_compliant"],
        "generation_duration_seconds": duration,
        "generation_metadata": metadata,
        "scoring_version": score["scoring_version"],
        "scored_text_source": score["scored_text_source"],
    }


def _update_counts(counts: dict[str, int], trial: dict[str, Any]) -> None:
    counts["attempted_trials"] += 1
    if trial.get("generation_status") == "success":
        counts["successful"] += 1
        if trial.get("is_compliant") is True:
            counts["compliant"] += 1
        else:
            counts["violating"] += 1
    else:
        counts["failed"] += 1


def _error_from_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ServerUnavailableError):
        return "server_unavailable", str(exc)
    if isinstance(exc, ServerResponseError):
        return exc.error_type, str(exc)
    if isinstance(exc, GenerationConfigError):
        return "generation_config", str(exc)
    return type(exc).__name__, str(exc)


def run_experiment(
    *,
    config_path: Path,
    config: dict[str, Any],
    prompts_path: Path,
    prompts: list[dict[str, Any]],
    prompt_warnings: list[str],
    overrides: dict[str, Any],
) -> int:
    repetitions = config["experiment"]["repetitions"]
    planned_trials = len(prompts) * repetitions
    server_config = config["server"]
    client = ServerClient(
        server_config["host"],
        server_config["port"],
        server_config["request_timeout_seconds"],
    )

    print(f"Checking model server at {client.base_url} ...")
    try:
        health = client.health()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        print("", file=sys.stderr)
        print("The experiment runner does not load the model itself.", file=sys.stderr)
        print("Start the persistent server first:", file=sys.stderr)
        print(f"  {START_COMMAND}", file=sys.stderr)
        print("Then check readiness:", file=sys.stderr)
        print(f"  {CHECK_COMMAND}", file=sys.stderr)
        return 1

    config_hash = sha256_file(config_path)
    problems = _model_matches(health, config["model"], config_hash)
    if problems:
        print("ERROR: the running model server does not match this configuration:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Stop and restart the server after updating config.json:", file=sys.stderr)
        print(f"  {STOP_COMMAND}", file=sys.stderr)
        print(f"  {START_COMMAND}", file=sys.stderr)
        return 1

    prompt_hash = sha256_file(prompts_path)
    results_dir = Path(config["results"]["directory"])
    try:
        run_dir = create_run_directory(results_dir)
    except Exception as exc:
        print(f"ERROR: could not create a unique run directory: {exc}", file=sys.stderr)
        return 1

    run_id = run_dir.name
    _setup_file_logging(run_dir)
    LOGGER.info("Run %s starting", run_id)
    LOGGER.info("Config: %s sha256=%s", config_path, config_hash)
    LOGGER.info("Prompts: %s sha256=%s", prompts_path, prompt_hash)

    environment = collect_environment()
    write_text_atomic(run_dir / "environment.txt", format_environment_text(environment))
    copy_file_atomic(prompts_path, run_dir / "prompts_snapshot.jsonl")
    copy_file_atomic(config_path, run_dir / "config_snapshot.json")
    write_text_atomic(run_dir / "trials.jsonl", "")

    manifest = _initial_manifest(
        run_id=run_id,
        config_path=config_path,
        config_hash=config_hash,
        prompts_path=prompts_path,
        prompt_hash=prompt_hash,
        prompts=prompts,
        planned_trials=planned_trials,
        config=config,
        environment=environment,
        health=health,
        overrides=overrides,
    )
    manifest["warnings"].extend(prompt_warnings)
    _write_manifest(run_dir, manifest)

    color = reporting.resolve_color(config["reporting"]["color"])
    show_outputs = config["reporting"]["show_outputs"]
    max_output_chars = config["reporting"]["max_output_chars"]

    print(
        reporting.render_run_header(
            run_id=run_id,
            model_id=config["model"]["id"],
            model_revision=config["model"]["revision"],
            prompt_count=len(prompts),
            repetitions=repetitions,
            planned_trials=planned_trials,
            server_url=client.base_url,
            color=color,
        )
    )

    trials: list[dict[str, Any]] = []
    counts = manifest["counts"]
    stop_requested = False
    interrupted = False
    fatal_error: str | None = None
    consecutive_failures = 0
    ordinal = 0

    def handle_sigterm(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        print("\nSIGTERM received. Finishing the current request, then stopping.", file=sys.stderr)

    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, handle_sigterm)
        except (ValueError, OSError):
            pass

    try:
        for prompt in prompts:
            if stop_requested:
                interrupted = True
                break
            for trial_index in range(repetitions):
                if stop_requested:
                    interrupted = True
                    break

                trial_id = f"{prompt['prompt_id']}_t{trial_index:03d}"
                seed = stable_trial_seed(config["generation"]["seed"], ordinal)
                generation_config = dict(config["generation"])
                generation_config["seed"] = seed
                timestamp = utc_now_iso()
                messages = [
                    {"role": "system", "content": prompt["system_instruction"]},
                    {"role": "user", "content": prompt["user_prompt"]},
                ]

                started = time.perf_counter()
                try:
                    result = client.generate(messages, generation_config, seed)
                    duration = time.perf_counter() - started
                    trial = _trial_success_record(
                        run_id=run_id,
                        trial_id=trial_id,
                        prompt=prompt,
                        trial_index=trial_index,
                        timestamp=timestamp,
                        config=config,
                        generation_config=generation_config,
                        result=result,
                        duration=duration,
                    )
                    consecutive_failures = 0
                except KeyboardInterrupt:
                    duration = time.perf_counter() - started
                    trial = _trial_error_record(
                        run_id=run_id,
                        trial_id=trial_id,
                        prompt=prompt,
                        trial_index=trial_index,
                        timestamp=timestamp,
                        config=config,
                        generation_config=generation_config,
                        error_type="interrupted",
                        error_message=(
                            "Experiment interrupted by user during generation. The "
                            "generation result was not received and is not retried."
                        ),
                        duration=duration,
                    )
                    interrupted = True
                except Exception as exc:
                    duration = time.perf_counter() - started
                    error_type, error_message = _error_from_exception(exc)
                    trial = _trial_error_record(
                        run_id=run_id,
                        trial_id=trial_id,
                        prompt=prompt,
                        trial_index=trial_index,
                        timestamp=timestamp,
                        config=config,
                        generation_config=generation_config,
                        error_type=error_type,
                        error_message=error_message,
                        duration=duration,
                    )
                    consecutive_failures += 1
                    if isinstance(exc, ServerUnavailableError):
                        fatal_error = (
                            f"Model server became unreachable: {error_message}. "
                            f"Start it with: {START_COMMAND}"
                        )
                    elif consecutive_failures >= server_config["max_consecutive_failures"]:
                        fatal_error = (
                            f"{consecutive_failures} consecutive generation failures; "
                            "stopping the run."
                        )

                ordinal += 1
                append_jsonl(run_dir / "trials.jsonl", trial)
                trials.append(trial)
                _update_counts(counts, trial)
                if trial.get("generation_status") == "error":
                    append_jsonl(
                        run_dir / "errors.jsonl",
                        {
                            "run_id": trial.get("run_id"),
                            "trial_id": trial.get("trial_id"),
                            "prompt_id": trial.get("prompt_id"),
                            "category": trial.get("category"),
                            "prompt_variant": trial.get("prompt_variant"),
                            "trial_index": trial.get("trial_index"),
                            "timestamp_utc": trial.get("timestamp_utc"),
                            "generation_status": trial.get("generation_status"),
                            "error": trial.get("error"),
                        },
                    )
                elif trial.get("contains_ascii_hyphen"):
                    violation_records = scoring.regenerate_violations([trial])
                    for record in violation_records:
                        append_jsonl(run_dir / "violations.jsonl", record)

                manifest["counts"] = counts
                _write_manifest(run_dir, manifest)
                LOGGER.info(
                    "Trial %s status=%s hyphens=%s finish=%s duration=%.3fs",
                    trial_id,
                    trial.get("generation_status"),
                    trial.get("ascii_hyphen_count"),
                    trial.get("finish_reason"),
                    trial.get("generation_duration_seconds") or 0.0,
                )

                if show_outputs:
                    print(
                        reporting.render_trial_card(
                            trial,
                            len(trials),
                            planned_trials,
                            color=color,
                            max_output_chars=max_output_chars,
                        )
                    )

                if interrupted or fatal_error:
                    break
            if interrupted or fatal_error:
                break
    except KeyboardInterrupt:
        interrupted = True
        print("\nInterrupted. Finalizing partial results.", file=sys.stderr)
    except Exception as exc:
        fatal_error = f"{type(exc).__name__}: {exc}"
        LOGGER.error("Unexpected runner error: %s\n%s", exc, traceback.format_exc())

    if interrupted:
        final_status = "interrupted"
    elif fatal_error:
        final_status = "failed"
    elif counts["attempted_trials"] == planned_trials:
        final_status = "completed"
    else:
        final_status = "failed"
        fatal_error = fatal_error or (
            f"Only {counts['attempted_trials']} of {planned_trials} planned trials were attempted."
        )

    counts["interrupted"] = bool(interrupted)
    manifest["status"] = final_status
    manifest["end_time_utc"] = utc_now_iso()
    manifest["counts"] = counts
    manifest["error"] = fatal_error
    if interrupted:
        manifest["warnings"].append(
            "Run was interrupted. Only recorded trials are included in summaries; "
            "missing trials are reported."
        )
    if fatal_error:
        manifest["warnings"].append(fatal_error)
    _write_manifest(run_dir, manifest)

    summary: dict[str, Any] | None = None
    try:
        from summarize_results import write_run_derived_outputs

        summary = write_run_derived_outputs(run_dir, manifest=manifest, trials=trials)
        manifest["output_files"] = sorted(
            set(manifest["output_files"]) | {"summary.json", "report.md", "outputs.md"}
        )
        manifest["data_validation"] = summary.get("data_validation")
        _write_manifest(run_dir, manifest)
    except Exception as exc:
        manifest["summary_error"] = f"{type(exc).__name__}: {exc}"
        manifest["status"] = "failed"
        manifest["warnings"].append(
            "Derived summary generation failed; inspect run.log and trials.jsonl."
        )
        _write_manifest(run_dir, manifest)
        LOGGER.error("Summary generation failed: %s\n%s", exc, traceback.format_exc())
        print(f"ERROR: summary generation failed: {exc}", file=sys.stderr)

    if summary is not None:
        print(reporting.render_summary(summary, trials=trials, color=color))
    print("")
    print(f"Run status : {manifest['status']}")
    print(f"Trials     : {counts['attempted_trials']}/{planned_trials}")
    print(f"Run folder : {run_dir}")
    print(f"Raw trials : {run_dir / 'trials.jsonl'}")
    print(f"Summary    : {run_dir / 'summary.json'}")
    print(f"Report     : {run_dir / 'report.md'}")
    print(f"Outputs    : {run_dir / 'outputs.md'}")
    print(f"Run log    : {run_dir / 'run.log'}")

    logging.shutdown()
    if interrupted:
        return 130
    if manifest["status"] == "failed":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--prompts", type=Path, help="override experiment.prompts_path")
    parser.add_argument("--repetitions", type=int, help="override experiment.repetitions")
    parser.add_argument("--validate-only", action="store_true", help="validate config and prompts; do not run")
    parser.add_argument("--quiet", action="store_true", help="suppress per-trial output cards")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--force-color", action="store_true")
    parser.add_argument("--max-output-chars", type=int, help="override reporting.max_output_chars")
    args = parser.parse_args(argv)

    config_path = args.config.resolve()
    try:
        raw_config = load_json(config_path)
    except Exception as exc:
        print(f"ERROR: could not read config {config_path}: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw_config, dict):
        print("ERROR: config root must be a JSON object", file=sys.stderr)
        return 1
    raw_config["_config_dir"] = str(config_path.parent)
    try:
        config = validate_config(raw_config)
    except ConfigValidationError as exc:
        print(f"ERROR: invalid config: {exc}", file=sys.stderr)
        return 1

    overrides: dict[str, Any] = {}
    prompts_path = Path(config["experiment"]["prompts_path"])
    if args.prompts is not None:
        prompts_path = args.prompts.resolve()
        config["experiment"]["prompts_path"] = str(prompts_path)
        overrides["prompts_path"] = str(prompts_path)
    if args.repetitions is not None:
        if args.repetitions < 1 or args.repetitions > 1000:
            print("ERROR: --repetitions must be in [1, 1000]", file=sys.stderr)
            return 1
        config["experiment"]["repetitions"] = args.repetitions
        overrides["repetitions"] = args.repetitions
    if args.max_output_chars is not None:
        if args.max_output_chars < 0:
            print("ERROR: --max-output-chars must be >= 0", file=sys.stderr)
            return 1
        config["reporting"]["max_output_chars"] = args.max_output_chars
        overrides["max_output_chars"] = args.max_output_chars
    if args.quiet:
        config["reporting"]["show_outputs"] = False
        overrides["show_outputs"] = False
    if args.no_color:
        config["reporting"]["color"] = "never"
        overrides["color"] = "never"
    elif args.force_color:
        config["reporting"]["color"] = "always"
        overrides["color"] = "always"

    try:
        prompts, prompt_warnings = load_prompts(prompts_path, include_disabled=False)
        prompts = select_prompts(
            prompts,
            config["experiment"]["include_prompt_ids"],
            config["experiment"]["include_categories"],
        )
    except (FileNotFoundError, PromptValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.validate_only:
        print(f"Config valid: {config_path}")
        print(f"Prompts valid: {prompts_path}")
        print(f"Enabled prompts selected: {len(prompts)}")
        print(f"Repetitions: {config['experiment']['repetitions']}")
        print(
            "Planned trials: "
            f"{len(prompts) * config['experiment']['repetitions']}"
        )
        for warning in prompt_warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        return 0

    return run_experiment(
        config_path=config_path,
        config=config,
        prompts_path=prompts_path,
        prompts=prompts,
        prompt_warnings=prompt_warnings,
        overrides=overrides,
    )


if __name__ == "__main__":
    raise SystemExit(main())
