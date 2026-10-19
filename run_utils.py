"""Shared utilities for run directories, hashes, atomic writes, and JSONL I/O."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    """Return a UTC timestamp with a ``Z`` suffix and second precision."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_run_id(now: datetime | None = None, suffix: str | None = None) -> str:
    """Create a Windows-safe, sortable, unique run id.

    Format: ``YYYYMMDD-HHMMSSZ-<6 lowercase hex>``.
    """

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    token = suffix if suffix is not None else secrets.token_hex(3)
    if not token or any(character not in "0123456789abcdef" for character in token.lower()):
        raise ValueError("run id suffix must be non-empty lowercase hexadecimal")
    return f"{moment.strftime('%Y%m%d-%H%M%SZ')}-{token.lower()}"


def create_run_directory(
    results_root: str | Path,
    run_id: str | None = None,
    max_attempts: int = 20,
) -> Path:
    """Create a brand-new run directory and never reuse an existing one.

    With an explicit ``run_id``, an existing directory raises ``FileExistsError``.
    Without one, fresh ids are generated and collisions are retried.
    """

    root = Path(results_root)
    root.mkdir(parents=True, exist_ok=True)

    if run_id is not None:
        path = root / run_id
        path.mkdir(parents=False, exist_ok=False)
        return path

    for _ in range(max_attempts):
        path = root / make_run_id()
        try:
            path.mkdir(parents=False, exist_ok=False)
            return path
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not allocate a unique run directory under {root}")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: str | Path, data: Any) -> None:
    """Write JSON through a same-directory temporary file, fsync, and replace."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_text_atomic(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def copy_file_atomic(source: str | Path, destination: str | Path) -> None:
    """Byte-for-byte copy with fsync and atomic replacement.

    Used for run input snapshots so their hashes match the bytes that were
    actually hashed. Text-mode copies would normalize Windows CRLF line endings.
    """

    src = Path(source)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with src.open("rb") as reader, temporary.open("wb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def _fsync_directory(directory: Path) -> None:
    """Best-effort directory fsync; not supported on every platform."""

    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def append_jsonl(path: str | Path, record: dict[str, Any]) -> None:
    """Append one complete JSON object as one line, then flush and fsync."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def write_jsonl_atomic(path: str | Path, records: Iterable[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(
                    json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read strict JSONL. Blank or malformed lines raise with their line number."""

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"JSONL file not found: {target}")

    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"{target}:{line_number}: blank line in JSONL")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{target}:{line_number}: invalid JSON at column {exc.colno}: {exc.msg}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"{target}:{line_number}: expected a JSON object, "
                    f"got {type(record).__name__}"
                )
            records.append(record)
    return records


def get_git_commit(repo_root: str | Path) -> str | None:
    """Return the current Git commit hash, or None when unavailable."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(repo_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = completed.stdout.strip()
    return commit or None


def get_git_dirty(repo_root: str | Path) -> bool | None:
    """Return whether the Git work tree has uncommitted changes, if available."""

    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=Path(repo_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(completed.stdout.strip())


def stable_trial_seed(base_seed: int, ordinal: int) -> int:
    """Derive a deterministic seed for trial *ordinal* (zero-based)."""

    if base_seed < 0:
        raise ValueError("base_seed must be non-negative")
    if ordinal < 0:
        raise ValueError("ordinal must be non-negative")
    # Keep the value within torch's accepted seed range.
    return (base_seed + ordinal) % (2**31)


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "unknown"
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            return f"{amount:.2f} {unit}"
        amount /= 1024.0
    return f"{amount:.2f} TiB"
