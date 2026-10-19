"""Collect and render environment details without exposing secrets.

Only known, non-sensitive fields are collected. Environment variables are never
dumped wholesale, and no credentials or tokens are included.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from run_utils import format_bytes, write_text_atomic

PACKAGE_NAMES = (
    "torch",
    "transformers",
    "accelerate",
    "tokenizers",
    "safetensors",
    "huggingface-hub",
    "pytest",
)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _collect_gpu() -> dict[str, Any]:
    result: dict[str, Any] = {
        "torch_available": False,
        "cuda_available": False,
        "devices": [],
        "error": None,
    }
    try:
        import torch  # imported lazily to keep the report usable without torch
    except Exception as exc:  # pragma: no cover - depends on local install
        result["error"] = f"torch import failed: {type(exc).__name__}: {exc}"
        return result

    result["torch_available"] = True
    result["torch_version"] = torch.__version__
    result["cuda_available"] = bool(torch.cuda.is_available())
    result["cuda_version"] = getattr(torch.version, "cuda", None)
    result["cudnn_version"] = (
        torch.backends.cudnn.version() if torch.backends.cudnn.is_available() else None
    )
    result["bf16_supported"] = (
        bool(torch.cuda.is_bf16_supported()) if result["cuda_available"] else False
    )
    if not result["cuda_available"]:
        return result

    result["device_count"] = torch.cuda.device_count()
    for index in range(torch.cuda.device_count()):
        properties = torch.cuda.get_device_properties(index)
        try:
            free_bytes, total_bytes = torch.cuda.mem_get_info(index)
        except Exception:  # pragma: no cover - driver-specific
            free_bytes, total_bytes = None, properties.total_memory
        result["devices"].append(
            {
                "index": index,
                "name": properties.name,
                "total_memory_bytes": int(total_bytes),
                "total_memory_human": format_bytes(total_bytes),
                "free_memory_bytes": int(free_bytes) if free_bytes is not None else None,
                "free_memory_human": format_bytes(free_bytes),
                "compute_capability": f"{properties.major}.{properties.minor}",
            }
        )
    return result


def collect_environment() -> dict[str, Any]:
    """Return a serializable environment report."""

    packages = {name: _package_version(name) for name in PACKAGE_NAMES}
    return {
        "collected_at_utc": _utc_now(),
        "python": {
            "version": sys.version,
            "version_info": list(sys.version_info[:3]),
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
        },
        "packages": packages,
        "gpu": _collect_gpu(),
        "notes": [
            "Available GPU memory is sampled at report time and may change.",
            "Environment variables are intentionally not collected.",
        ],
    }


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def format_environment_text(report: dict[str, Any]) -> str:
    """Render a human-readable environment report."""

    lines: list[str] = []
    lines.append("Environment report")
    lines.append("==================")
    lines.append(f"Collected at (UTC): {report.get('collected_at_utc')}")
    lines.append("")

    python = report.get("python", {})
    lines.append("[Python]")
    lines.append(f"  implementation: {python.get('implementation')}")
    lines.append(f"  version: {python.get('version', '').strip()}")
    lines.append("")

    platform_info = report.get("platform", {})
    lines.append("[Platform]")
    for key in ("system", "release", "machine", "processor", "platform", "cpu_count"):
        lines.append(f"  {key}: {platform_info.get(key)}")
    lines.append("")

    lines.append("[Packages]")
    for name, version in report.get("packages", {}).items():
        lines.append(f"  {name}: {version or 'not installed'}")
    lines.append("")

    gpu = report.get("gpu", {})
    lines.append("[GPU]")
    lines.append(f"  torch available: {gpu.get('torch_available')}")
    lines.append(f"  torch version: {gpu.get('torch_version')}")
    lines.append(f"  CUDA available: {gpu.get('cuda_available')}")
    lines.append(f"  CUDA version: {gpu.get('cuda_version')}")
    lines.append(f"  cuDNN version: {gpu.get('cudnn_version')}")
    lines.append(f"  bfloat16 supported: {gpu.get('bf16_supported')}")
    if gpu.get("error"):
        lines.append(f"  error: {gpu['error']}")
    devices = gpu.get("devices") or []
    if not devices:
        lines.append("  devices: none reported")
    for device in devices:
        lines.append(f"  device {device.get('index')}: {device.get('name')}")
        lines.append(f"    total memory: {device.get('total_memory_human')}")
        lines.append(f"    free memory: {device.get('free_memory_human')}")
        lines.append(f"    compute capability: {device.get('compute_capability')}")
    lines.append("")

    lines.append("[Notes]")
    for note in report.get("notes", []):
        lines.append(f"  - {note}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument("--output", type=Path, help="also write the report to this path")
    args = parser.parse_args(argv)

    report = collect_environment()
    text = json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_environment_text(report)
    print(text, end="" if text.endswith("\n") else "\n")
    if args.output:
        write_text_atomic(args.output, text + ("" if text.endswith("\n") else "\n"))
        print(f"Wrote environment report to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
