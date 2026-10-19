"""Prepare a clean, self-contained Hugging Face research artifact directory.

This script never uploads anything and never contacts Hugging Face. It copies
only an explicit whitelist of run artifacts, verifies the prompt/config hashes
against the run manifest, and writes a research README plus checksums.

Inspect the output directory manually before publishing. Do not add tokens,
private data, model weights, or unrelated local files.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from run_utils import load_json, sha256_file, utc_now_iso, write_text_atomic


class ExportError(RuntimeError):
    pass


REQUIRED_RUN_FILES = (
    "run_manifest.json",
    "trials.jsonl",
    "summary.json",
    "violations.jsonl",
    "errors.jsonl",
    "environment.txt",
    "report.md",
    "outputs.md",
)

COPY_FILES = (
    "trials.jsonl",
    "violations.jsonl",
    "errors.jsonl",
    "summary.json",
    "environment.txt",
    "report.md",
    "outputs.md",
)


def _rate_cell(rate: dict[str, Any] | None) -> str:
    if not isinstance(rate, dict) or rate.get("rate") is None:
        numerator = rate.get("numerator") if isinstance(rate, dict) else 0
        denominator = rate.get("denominator") if isinstance(rate, dict) else 0
        return f"{numerator}/{denominator} (n/a)"
    return f"{rate['numerator']}/{rate['denominator']} ({rate['percent']:.1f}%)"


def _sanitize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Copy the manifest and replace local absolute paths with bundle names."""

    public = json.loads(json.dumps(manifest))
    if isinstance(public.get("prompt_file"), dict):
        public["prompt_file"]["path"] = "prompts.jsonl"
    if isinstance(public.get("config_file"), dict):
        public["config_file"]["path"] = "config.json"
    if isinstance(public.get("experiment"), dict):
        public["experiment"]["prompts_path"] = "prompts.jsonl"
    overrides = public.get("overrides")
    if isinstance(overrides, dict):
        for key, value in list(overrides.items()):
            if isinstance(value, str) and "path" in key.lower():
                overrides[key] = Path(value).name
    public["publication_note"] = (
        "Local absolute paths were replaced with bundle-relative filenames. "
        "Hashes, model identity, settings, counts, and raw records are unchanged."
    )
    public["exported_at_utc"] = utc_now_iso()
    return public


def _verify_source(source: Path, expected_hash: str | None, label: str) -> None:
    if not source.is_file():
        raise ExportError(f"Required {label} not found: {source}")
    if expected_hash:
        actual = sha256_file(source)
        if actual != expected_hash:
            raise ExportError(
                f"{label} hash mismatch: manifest records {expected_hash}, "
                f"but {source} has {actual}. The run inputs were edited after the "
                "run. Export the snapshot from the run directory instead."
            )


def _find_inputs(run_dir: Path, manifest: dict[str, Any], repo_root: Path) -> tuple[Path, Path]:
    prompt_hash = (manifest.get("prompt_file") or {}).get("sha256")
    config_hash = (manifest.get("config_file") or {}).get("sha256")

    prompt_candidates = [
        run_dir / "prompts_snapshot.jsonl",
        Path((manifest.get("prompt_file") or {}).get("path", "")),
        repo_root / "prompts.jsonl",
    ]
    config_candidates = [
        run_dir / "config_snapshot.json",
        Path((manifest.get("config_file") or {}).get("path", "")),
        repo_root / "config.json",
    ]

    prompt_source = next((path for path in prompt_candidates if path.is_file()), None)
    config_source = next((path for path in config_candidates if path.is_file()), None)
    if prompt_source is None:
        raise ExportError("Could not locate the prompt file used by this run")
    if config_source is None:
        raise ExportError("Could not locate the config file used by this run")
    _verify_source(prompt_source, prompt_hash, "prompt file")
    _verify_source(config_source, config_hash, "config file")
    return prompt_source, config_source


def _representative_violations(violations_path: Path, limit: int = 3) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with violations_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            records.append(record)
            if len(records) >= limit:
                break
    return records


def _readme(
    summary: dict[str, Any],
    manifest: dict[str, Any],
    violations: list[dict[str, Any]],
) -> str:
    overall = summary.get("overall") or {}
    ci = overall.get("violation_rate_ci95") or {}
    lines: list[str] = []
    lines.append("# Hyphen Prohibition in LLM Email Writing — Research Artifact")
    lines.append("")
    lines.append(f"Run ID: `{summary.get('run_id')}`")
    lines.append("")
    lines.append("## Research question")
    lines.append("")
    lines.append(
        "How frequently does an instruction-tuned language model produce the ASCII "
        "hyphen-minus character (`-`) in email drafts when explicitly instructed not "
        "to use it, and how does the violation rate vary across email-writing "
        "scenarios and prompt formulations?"
    )
    lines.append("")
    lines.append("## Hypothesis")
    lines.append("")
    lines.append(
        "The model will sometimes violate the explicit character constraint. "
        "Violation rates may differ across prompt categories and wording. This is a "
        "hypothesis to test, not a predetermined result."
    )
    lines.append("")
    lines.append("## Experiment")
    lines.append("")
    lines.append(f"- Model: `{summary.get('model_id')}`")
    lines.append(f"- Revision: `{summary.get('model_revision')}`")
    lines.append(f"- Non-thinking mode: `{summary.get('non_thinking_mode')}`")
    lines.append(f"- Precision: `{summary.get('precision')}` on `{summary.get('device')}`")
    lines.append(f"- Enabled prompts: {summary.get('prompt_count')}")
    lines.append(f"- Attempted distinct prompts: {summary.get('attempted_prompt_count')}")
    lines.append(f"- Repetitions per prompt: {summary.get('repetitions')}")
    lines.append(f"- Planned / attempted trials: {summary.get('planned_trials')} / {summary.get('attempted_trials')}")
    lines.append(f"- Run status: `{summary.get('run_status')}`")
    lines.append("")
    lines.append("Generation settings:")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(summary.get("generation_settings") or {}, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Scoring")
    lines.append("")
    lines.append(summary.get("scoring", {}).get("rule", ""))
    lines.append("")
    lines.append(
        "The score applies to the complete raw generated text. Failed generations are "
        "excluded from compliance denominators and reported separately."
    )
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Attempted trials | {overall.get('attempted')} |")
    lines.append(f"| Successful generations | {overall.get('successful')} |")
    lines.append(f"| Failed generations | {overall.get('failed')} |")
    lines.append(f"| Compliant | {_rate_cell(overall.get('compliance_rate'))} |")
    lines.append(f"| Violating | {_rate_cell(overall.get('violation_rate'))} |")
    lines.append(f"| Technical failures | {_rate_cell(overall.get('failure_rate'))} |")
    if ci.get("lower") is not None:
        lines.append(
            f"| 95% Wilson CI (violation) | "
            f"[{ci['lower'] * 100:.1f}%, {ci['upper'] * 100:.1f}%], n={ci['denominator']} |"
        )
    lines.append("")
    lines.append("### By category")
    lines.append("")
    lines.append("| Category | Attempted | Successful | Failed | Violating | Violation rate |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for category, metrics in (summary.get("by_category") or {}).items():
        lines.append(
            f"| {category} | {metrics.get('attempted')} | {metrics.get('successful')} | "
            f"{metrics.get('failed')} | {metrics.get('violating')} | "
            f"{_rate_cell(metrics.get('violation_rate'))} |"
        )
    lines.append("")
    lines.append("### By prompt formulation")
    lines.append("")
    lines.append("| Formulation | Attempted | Successful | Failed | Violating | Violation rate |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for variant, metrics in (summary.get("by_prompt_variant") or {}).items():
        lines.append(
            f"| {variant} | {metrics.get('attempted')} | {metrics.get('successful')} | "
            f"{metrics.get('failed')} | {metrics.get('violating')} | "
            f"{_rate_cell(metrics.get('violation_rate'))} |"
        )
    lines.append("")
    if violations:
        lines.append("## Representative violation excerpts")
        lines.append("")
        for violation in violations:
            lines.append(
                f"- `{violation.get('trial_id')}` ({violation.get('prompt_id')}): "
                f"{violation.get('ascii_hyphen_count')} hyphen(s) at positions "
                f"`{violation.get('violation_positions')}`"
            )
            contexts = violation.get("violation_contexts") or []
            for context in contexts[:2]:
                excerpt = " ".join(str(context.get("excerpt", "")).split())
                lines.append(f"  - position {context.get('position')}: `{excerpt}`")
        lines.append("")
    lines.append("## Files")
    lines.append("")
    files = [
        "`README.md` — this artifact overview",
        "`RESEARCH.md` — method, results, limitations, future work",
        "`prompts.jsonl` — exact prompt set used",
        "`config.json` — exact configuration file used",
        "`run_manifest.json` — reproducibility manifest (local paths sanitized)",
        "`trials.jsonl` — one record per attempted trial, including raw generations",
        "`violations.jsonl` — rebuilt violation records with positions and contexts",
        "`errors.jsonl` — technical failures",
        "`summary.json` — machine-readable metrics",
        "`report.md` — human-readable report",
        "`outputs.md` — numbered prompt-by-prompt outputs",
        "`environment.txt` — Python/package/GPU environment",
        "`checksums.sha256` — SHA-256 checksums for exported files",
    ]
    lines.extend(f"- {item}" for item in files)
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    limitations = [
        "Results describe only the tested model, prompt set, and generation settings. "
        "They should not be generalized to all language models without additional experiments.",
        f"The prompt set contains {summary.get('prompt_count')} enabled prompts; the PRD "
        "suggested 30 to 50, and any deviation is recorded in the manifest.",
        f"The evaluated model is {summary.get('model_id')}; the PRD default was "
        "Qwen/Qwen3-4B. Any substitution is recorded in the project deviations.",
        "Email-body extraction is not implemented; the complete raw generated text is scored.",
        "A fixed seed does not guarantee bit-for-bit identical output across hardware and "
        "software versions.",
        "No significance tests were performed. Category and formulation differences are "
        "descriptive only.",
        "The experiment does not establish why violations occur.",
    ]
    lines.extend(f"- {item}" for item in limitations)
    lines.append("")
    if summary.get("known_deviations"):
        lines.append("## Recorded project deviations")
        lines.append("")
        lines.extend(f"- {item}" for item in summary["known_deviations"])
        lines.append("")
    lines.append("## Publication checklist")
    lines.append("")
    lines.append(
        "This directory was generated locally and was **not** uploaded. Before publishing, "
        "inspect the files for anything private, confirm the model license "
        "(Qwen3-1.7B is Apache-2.0), and upload only this directory."
    )
    lines.append("")
    lines.append(f"Exported at: {utc_now_iso()}")
    lines.append("")
    return "\n".join(lines)


def _research_markdown(summary: dict[str, Any]) -> str:
    overall = summary.get("overall") or {}
    lines = [
        "# Research Method and Findings",
        "",
        "## Method",
        "",
        "Each prompt supplied a system instruction banning the literal ASCII "
        "hyphen-minus (`-`) and a user task requesting an email. The model was run in "
        "Qwen3 non-thinking mode with a pinned model/tokenizer revision and a fixed "
        "generation configuration. Every attempted trial was recorded incrementally.",
        "",
        "The primary outcome is whether a successful generation contains at least one "
        "literal U+002D character. En dash, em dash, and Unicode minus do not count. "
        "No normalization is applied. Technical failures are excluded from compliance "
        "denominators and reported separately.",
        "",
        "## Findings",
        "",
        f"- Successful / attempted: {overall.get('successful')} / {overall.get('attempted')}",
        f"- Violating: {_rate_cell(overall.get('violation_rate'))}",
        f"- Compliant: {_rate_cell(overall.get('compliance_rate'))}",
        f"- Failed: {_rate_cell(overall.get('failure_rate'))}",
        "",
        "These are descriptive results for this model, prompt set, and configuration. "
        "They do not establish a cause and should not be generalized without further "
        "experiments.",
        "",
        "## Limitations and future work",
        "",
        "- The prompt set is small (15 prompts) and uses two prompt formulations.",
        "- The experiment evaluates one model and one decoding configuration.",
        "- Email-body extraction was not implemented, so commentary would also be scored.",
        "- Repeated trials would be clustered by prompt; independence assumptions may "
        "understate uncertainty.",
        "- Future work could compare training approaches and inspect internal model "
        "changes associated with improved constraint compliance. That work is outside "
        "this artifact.",
        "",
    ]
    return "\n".join(lines)


def export_bundle(run_dir: Path, output_dir: Path, repo_root: Path) -> Path:
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise ExportError(f"Run directory not found: {run_dir}")
    missing = [name for name in REQUIRED_RUN_FILES if not (run_dir / name).is_file()]
    if missing:
        raise ExportError(
            f"Run directory is missing required files: {missing}. "
            "Run `python summarize_results.py "
            f"{run_dir}` first."
        )

    manifest = load_json(run_dir / "run_manifest.json")
    summary = load_json(run_dir / "summary.json")
    if not isinstance(manifest, dict) or not isinstance(summary, dict):
        raise ExportError("run_manifest.json and summary.json must contain JSON objects")

    prompt_source, config_source = _find_inputs(run_dir, manifest, repo_root)

    if output_dir.exists():
        raise ExportError(
            f"Output directory already exists: {output_dir}. Choose a new path or "
            "remove it manually after inspection."
        )
    output_dir.mkdir(parents=True, exist_ok=False)

    try:
        for name in COPY_FILES:
            shutil.copyfile(run_dir / name, output_dir / name)
        shutil.copyfile(prompt_source, output_dir / "prompts.jsonl")
        shutil.copyfile(config_source, output_dir / "config.json")

        public_manifest = _sanitize_manifest(manifest)
        write_text_atomic(
            output_dir / "run_manifest.json",
            json.dumps(public_manifest, ensure_ascii=False, indent=2) + "\n",
        )

        violations = _representative_violations(output_dir / "violations.jsonl")
        write_text_atomic(output_dir / "README.md", _readme(summary, manifest, violations))
        write_text_atomic(output_dir / "RESEARCH.md", _research_markdown(summary))

        checksum_targets = sorted(
            path for path in output_dir.iterdir() if path.is_file() and path.name != "checksums.sha256"
        )
        checksum_lines = [f"{sha256_file(path)}  {path.name}" for path in checksum_targets]
        write_text_atomic(output_dir / "checksums.sha256", "\n".join(checksum_lines) + "\n")
    except Exception:
        # Leave the partial directory for inspection rather than silently deleting it.
        raise
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    output_dir = args.output_dir or (Path("hf_export") / args.run_dir.resolve().name)
    try:
        exported = export_bundle(args.run_dir, output_dir, args.repo_root)
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Artifact bundle prepared: {exported}")
    print("Nothing was uploaded.")
    print("Inspect every file for private data before publishing, then upload the directory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
