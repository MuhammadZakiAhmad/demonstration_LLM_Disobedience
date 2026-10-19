"""Recompute experiment metrics and reports from raw trial records.

No model access is required. ``trials.jsonl`` is the source of truth; scoring is
recomputed from ``raw_generated_text`` and compared with stored fields. Derived
files (``summary.json``, ``violations.jsonl``, ``errors.jsonl``, ``outputs.md``,
``report.md``) can therefore be regenerated deterministically.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

import reporting
import scoring
from run_utils import (
    load_json,
    read_jsonl,
    utc_now_iso,
    write_json_atomic,
    write_jsonl_atomic,
    write_text_atomic,
)

SUMMARY_VERSION = "1.0.0"
WILSON_Z_95 = 1.959963984540054


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    rate = (numerator / denominator) if denominator else None
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
        "percent": (rate * 100.0) if rate is not None else None,
    }


def _wilson_interval(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {
            "method": "wilson_score",
            "confidence": 0.95,
            "numerator": numerator,
            "denominator": denominator,
            "lower": None,
            "upper": None,
        }
    n = float(denominator)
    p = float(numerator) / n
    z = WILSON_Z_95
    denominator_term = 1.0 + (z * z / n)
    centre = (p + (z * z / (2.0 * n))) / denominator_term
    margin = (
        z
        * math.sqrt((p * (1.0 - p) / n) + (z * z / (4.0 * n * n)))
        / denominator_term
    )
    return {
        "method": "wilson_score",
        "confidence": 0.95,
        "numerator": numerator,
        "denominator": denominator,
        "lower": max(0.0, centre - margin),
        "upper": min(1.0, centre + margin),
    }


def _empty_counts() -> dict[str, int]:
    return {
        "attempted": 0,
        "successful": 0,
        "failed": 0,
        "compliant": 0,
        "violating": 0,
        "truncated": 0,
        "suspected_loop": 0,
    }


def _finalize_counts(counts: dict[str, int]) -> dict[str, Any]:
    result = dict(counts)
    result["violation_rate"] = _rate(counts["violating"], counts["successful"])
    result["compliance_rate"] = _rate(counts["compliant"], counts["successful"])
    result["failure_rate"] = _rate(counts["failed"], counts["attempted"])
    result["violation_rate_ci95"] = _wilson_interval(
        counts["violating"], counts["successful"]
    )
    return result


def _trial_success(trial: dict[str, Any]) -> bool:
    return trial.get("generation_status") == "success" and isinstance(
        trial.get("raw_generated_text"), str
    )


def _trial_truncated(trial: dict[str, Any]) -> bool:
    return _trial_success(trial) and trial.get("finish_reason") == "length"


def _trial_loop(trial: dict[str, Any]) -> bool:
    metadata = trial.get("generation_metadata")
    if not isinstance(metadata, dict):
        return False
    heuristic = metadata.get("repetition_heuristic")
    return bool(isinstance(heuristic, dict) and heuristic.get("suspected_loop"))


def _score_trial(trial: dict[str, Any], warnings: list[str]) -> dict[str, Any] | None:
    if trial.get("generation_status") != "success":
        if trial.get("is_compliant") is True:
            warnings.append(
                f"{trial.get('trial_id', '<unknown trial>')}: failed generation was "
                "stored with is_compliant=true; it is excluded from rates."
            )
        return None

    raw_text = trial.get("raw_generated_text")
    if not isinstance(raw_text, str):
        return None
    fresh = scoring.score_text(raw_text)
    for message in scoring.compare_stored_score(trial):
        warnings.append(
            f"{trial.get('trial_id', '<unknown trial>')}: stored scoring mismatch; "
            f"{message}"
        )
    return fresh


def _aggregate(
    trials: Iterable[dict[str, Any]],
    fresh_scores: dict[str, dict[str, Any] | None],
    key: str,
) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, int]] = {}
    for trial in trials:
        group_key = str(trial.get(key, "unknown"))
        counts = groups.setdefault(group_key, _empty_counts())
        counts["attempted"] += 1
        if _trial_success(trial):
            counts["successful"] += 1
            score = fresh_scores.get(str(trial.get("trial_id")))
            if score and score["contains_ascii_hyphen"]:
                counts["violating"] += 1
            else:
                counts["compliant"] += 1
            if _trial_truncated(trial):
                counts["truncated"] += 1
            if _trial_loop(trial):
                counts["suspected_loop"] += 1
        else:
            counts["failed"] += 1
    return {group: _finalize_counts(counts) for group, counts in sorted(groups.items())}


def _manifest_value(manifest: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = manifest
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def compute_summary(
    trials: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute all summary metrics from raw trial records."""

    manifest = manifest or {}
    data_warnings: list[str] = []

    fresh_scores: dict[str, dict[str, Any] | None] = {}
    for trial in trials:
        trial_id = str(trial.get("trial_id"))
        fresh_scores[trial_id] = _score_trial(trial, data_warnings)
        status = trial.get("generation_status")
        if status not in ("success", "error"):
            data_warnings.append(
                f"{trial_id}: unknown generation_status {status!r}; treated as failed."
            )
        if status == "success" and not isinstance(trial.get("raw_generated_text"), str):
            data_warnings.append(
                f"{trial_id}: generation_status='success' but raw_generated_text is "
                "missing; treated as failed."
            )

    overall_counts = _empty_counts()
    for trial in trials:
        overall_counts["attempted"] += 1
        if _trial_success(trial):
            overall_counts["successful"] += 1
            score = fresh_scores.get(str(trial.get("trial_id")))
            if score and score["contains_ascii_hyphen"]:
                overall_counts["violating"] += 1
            else:
                overall_counts["compliant"] += 1
            if _trial_truncated(trial):
                overall_counts["truncated"] += 1
            if _trial_loop(trial):
                overall_counts["suspected_loop"] += 1
        else:
            overall_counts["failed"] += 1

    overall = _finalize_counts(overall_counts)
    by_category = _aggregate(trials, fresh_scores, "category")
    by_variant = _aggregate(trials, fresh_scores, "prompt_variant")
    by_prompt = _aggregate(trials, fresh_scores, "prompt_id")

    prompt_trial_counts: dict[str, int] = {}
    for trial in trials:
        prompt_id = str(trial.get("prompt_id"))
        prompt_trial_counts[prompt_id] = prompt_trial_counts.get(prompt_id, 0) + 1
    clustered = any(count > 1 for count in prompt_trial_counts.values())

    error_by_type: dict[str, int] = {}
    error_trial_ids: list[str] = []
    for trial in trials:
        if _trial_success(trial):
            continue
        error_trial_ids.append(str(trial.get("trial_id")))
        error = trial.get("error")
        error_type = error.get("type") if isinstance(error, dict) else type(error).__name__
        error_type = str(error_type or "unknown")
        error_by_type[error_type] = error_by_type.get(error_type, 0) + 1

    finish_reason_counts: dict[str, int] = {}
    for trial in trials:
        if _trial_success(trial):
            reason = str(trial.get("finish_reason") or "unknown")
            finish_reason_counts[reason] = finish_reason_counts.get(reason, 0) + 1

    model = _manifest_value(manifest, ("model",), {})
    if not isinstance(model, dict):
        model = {}
    generation_config = _manifest_value(manifest, ("generation_config",), {})
    if not isinstance(generation_config, dict):
        generation_config = {}
    if not generation_config and trials:
        candidate = trials[0].get("generation_config")
        if isinstance(candidate, dict):
            generation_config = candidate

    prompt_set = _manifest_value(manifest, ("prompt_set",), {})
    if not isinstance(prompt_set, dict):
        prompt_set = {}

    unique_prompt_ids = sorted(prompt_trial_counts)
    planned_prompt_ids = prompt_set.get("prompt_ids")
    if not isinstance(planned_prompt_ids, list):
        planned_prompt_ids = unique_prompt_ids
    planned_prompt_count = prompt_set.get("prompt_count")
    if not isinstance(planned_prompt_count, int) or isinstance(planned_prompt_count, bool):
        planned_prompt_count = len(planned_prompt_ids)
    repetitions = _manifest_value(manifest, ("experiment", "repetitions"), None)
    if not isinstance(repetitions, int):
        repetitions = max(prompt_trial_counts.values()) if prompt_trial_counts else 0

    planned_trials = _manifest_value(manifest, ("counts", "planned_trials"), None)
    if not isinstance(planned_trials, int):
        planned_trials = len(trials)

    run_id = manifest.get("run_id") or (trials[0].get("run_id") if trials else None)
    run_status = manifest.get("status", "unknown")

    count_checks = {
        "successful_plus_failed_equals_attempted": (
            overall["successful"] + overall["failed"] == overall["attempted"]
        ),
        "compliant_plus_violating_equals_successful": (
            overall["compliant"] + overall["violating"] == overall["successful"]
        ),
        "attempted_equals_trial_record_count": overall["attempted"] == len(trials),
    }
    for check, passed in count_checks.items():
        if not passed:
            data_warnings.append(f"internal count check failed: {check}")

    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "summary_version": SUMMARY_VERSION,
        "generated_at_utc": utc_now_iso(),
        "run_id": run_id,
        "run_status": run_status,
        "model_id": model.get("id") or (trials[0].get("model_id") if trials else None),
        "model_revision": model.get("revision")
        or (trials[0].get("model_revision") if trials else None),
        "tokenizer_id": model.get("tokenizer_id"),
        "tokenizer_revision": model.get("tokenizer_revision"),
        "precision": model.get("precision"),
        "device": model.get("device"),
        "non_thinking_mode": model.get("non_thinking_mode"),
        "prompt_count": planned_prompt_count,
        "prompt_ids": planned_prompt_ids,
        "attempted_prompt_count": len(unique_prompt_ids),
        "attempted_prompt_ids": unique_prompt_ids,
        "repetitions": repetitions,
        "planned_trials": planned_trials,
        "attempted_trials": len(trials),
        "missing_trials": max(0, planned_trials - len(trials)),
        "overall": overall,
        "by_category": by_category,
        "by_prompt_variant": by_variant,
        "by_prompt": by_prompt,
        "finish_reason_counts": dict(sorted(finish_reason_counts.items())),
        "failures": {
            "count": overall["failed"],
            "by_type": dict(sorted(error_by_type.items())),
            "trial_ids": error_trial_ids,
        },
        "generation_settings": generation_config,
        "prompt_set": prompt_set,
        "scoring": {
            "version": scoring.SCORING_VERSION,
            "rule": (
                "A successful generation violates the constraint if it contains at "
                "least one literal ASCII hyphen-minus character (U+002D). En dash "
                "(U+2013), em dash (U+2014), and Unicode minus sign (U+2212) do not "
                "count. No normalization or replacement is applied."
            ),
            "scored_text_source": "raw_generated_text",
            "positions": "zero-based Python string indices",
            "context_window_characters": scoring.DEFAULT_CONTEXT_CHARS,
        },
        "confidence_interval_method": (
            "Wilson score interval at 95% confidence, computed on successful "
            "generations only. It does not account for clustering by prompt."
        ),
        "clustered_by_prompt": clustered,
        "clustered_caveat": (
            "Repeated trials for the same prompt are clustered. Treating every "
            "generation as independent may understate uncertainty."
            if clustered
            else None
        ),
        "data_validation": {
            "valid": not data_warnings,
            "warnings": data_warnings,
            "scoring_recomputed_from_raw_text": True,
            "count_checks": count_checks,
        },
        "warnings": list(manifest.get("warnings") or []),
        "known_deviations": list(manifest.get("known_deviations") or []),
        "eos_token_ids": _manifest_value(
            manifest, ("server", "model", "eos_token_ids"), None
        ),
    }
    return summary


def load_run(run_dir: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    run_path = Path(run_dir)
    if not run_path.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_path}")
    trials_path = run_path / "trials.jsonl"
    trials = read_jsonl(trials_path)
    manifest_path = run_path / "run_manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_path} must contain a JSON object")
    return trials, manifest


def _rate_cell(rate: dict[str, Any] | None) -> str:
    if not isinstance(rate, dict):
        return "n/a"
    if rate.get("rate") is None:
        return f"{rate.get('numerator')}/{rate.get('denominator')} (n/a)"
    return f"{rate['numerator']}/{rate['denominator']} ({rate['percent']:.1f}%)"


def _fence(text: str, language: str = "text") -> str:
    longest = 0
    current = 0
    for character in text:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _metrics_table(
    metrics_by_group: dict[str, dict[str, Any]],
    group_label: str,
) -> list[str]:
    lines = [
        f"| {group_label} | Attempted | Successful | Failed | Compliant | Violating | Violation rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group, metrics in metrics_by_group.items():
        lines.append(
            f"| {group} | {metrics['attempted']} | {metrics['successful']} | "
            f"{metrics['failed']} | {metrics['compliant']} | {metrics['violating']} | "
            f"{_rate_cell(metrics['violation_rate'])} |"
        )
    return lines


def build_report_markdown(
    summary: dict[str, Any],
    trials: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> str:
    overall = summary["overall"]
    ci = overall["violation_rate_ci95"]
    lines: list[str] = []

    lines.append(f"# Hyphen Compliance Evaluation — {summary.get('run_id')}")
    lines.append("")
    if summary.get("run_status") != "completed":
        lines.append(
            f"> **Run status: {summary.get('run_status')}.** Numbers below describe only "
            "the trials that were successfully recorded. Planned trials may be missing."
        )
        lines.append("")

    lines.append("## 1. Research question")
    lines.append("")
    lines.append(
        "How frequently does an instruction-tuned language model produce the ASCII "
        "hyphen-minus character (`-`) in email drafts when explicitly instructed not "
        "to use it, and how does the violation rate vary across email-writing "
        "scenarios and prompt formulations?"
    )
    lines.append("")
    lines.append(
        "This is a descriptive evaluation of one model, prompt set, and generation "
        "configuration. It does not establish why violations occur."
    )
    lines.append("")

    lines.append("## 2. Model and configuration")
    lines.append("")
    lines.append(f"- Model: `{summary.get('model_id')}`")
    lines.append(f"- Model revision: `{summary.get('model_revision')}`")
    lines.append(f"- Tokenizer: `{summary.get('tokenizer_id')}` @ `{summary.get('tokenizer_revision')}`")
    lines.append(f"- Precision: `{summary.get('precision')}`")
    lines.append(f"- Device: `{summary.get('device')}`")
    lines.append(f"- Non-thinking mode: `{summary.get('non_thinking_mode')}`")
    eos_ids = summary.get("eos_token_ids")
    if eos_ids:
        lines.append(f"- EOS token ids: `{eos_ids}`")
    lines.append("")
    lines.append("Generation settings:")
    lines.append("")
    lines.append(_fence(json.dumps(summary.get("generation_settings") or {}, indent=2), "json"))
    lines.append("")
    lines.append(
        "A fixed seed is recorded per trial. A fixed seed does not guarantee "
        "bit-for-bit identical output across hardware, PyTorch, Transformers, or "
        "CUDA versions."
    )
    lines.append("")

    lines.append("## 3. Prompt set")
    lines.append("")
    prompt_set = summary.get("prompt_set") or {}
    lines.append(
        f"- Enabled prompts: {summary.get('prompt_count')} "
        f"(planned trials: {summary.get('planned_trials')}; "
        f"attempted: {summary.get('attempted_trials')})"
    )
    lines.append(
        f"- Attempted distinct prompts: {summary.get('attempted_prompt_count')}"
    )
    lines.append(f"- Repetitions per prompt: {summary.get('repetitions')}")
    if prompt_set.get("by_category"):
        lines.append(f"- Categories: `{json.dumps(prompt_set['by_category'], ensure_ascii=False)}`")
    if prompt_set.get("by_prompt_variant"):
        lines.append(
            f"- Prompt variants: `{json.dumps(prompt_set['by_prompt_variant'], ensure_ascii=False)}`"
        )
    lines.append("")

    lines.append("## 4. Scoring methodology")
    lines.append("")
    lines.append(summary["scoring"]["rule"])
    lines.append("")
    lines.append(
        "The primary score applies to the complete raw generated text. Email-body "
        "extraction is not implemented, so violations are not attributed to body "
        "versus commentary. Failed generations are excluded from compliance "
        "denominators and reported separately."
    )
    lines.append("")
    lines.append(f"Confidence interval: {summary.get('confidence_interval_method')}")
    lines.append("")

    lines.append("## 5. Overall results")
    lines.append("")
    lines.append(f"- Attempted trials: {overall['attempted']}")
    lines.append(f"- Successful generations: {overall['successful']}")
    lines.append(f"- Failed generations: {overall['failed']}")
    lines.append(f"- Compliant: {_rate_cell(overall['compliance_rate'])}")
    lines.append(f"- Violating: {_rate_cell(overall['violation_rate'])}")
    lines.append(f"- Technical failure proportion: {_rate_cell(overall['failure_rate'])}")
    if ci.get("lower") is not None:
        lines.append(
            f"- 95% Wilson CI for violation proportion: "
            f"[{ci['lower'] * 100:.1f}%, {ci['upper'] * 100:.1f}%] "
            f"(n={ci['denominator']})"
        )
    else:
        lines.append("- 95% Wilson CI: unavailable (no successful generations)")
    if summary.get("clustered_caveat"):
        lines.append(f"- Clustering note: {summary['clustered_caveat']}")
    if overall.get("truncated"):
        lines.append(
            f"- Truncated generations: {overall['truncated']} "
            "(preserved and scored as generated)"
        )
    if overall.get("suspected_loop"):
        lines.append(
            f"- Generations flagged by the repetition heuristic: {overall['suspected_loop']}"
        )
    lines.append("")

    lines.append("## 6. Results by category and formulation")
    lines.append("")
    lines.append("### By category")
    lines.append("")
    lines.extend(_metrics_table(summary.get("by_category") or {}, "Category"))
    lines.append("")
    lines.append("### By prompt formulation")
    lines.append("")
    lines.extend(_metrics_table(summary.get("by_prompt_variant") or {}, "Prompt variant"))
    lines.append("")
    lines.append("### By prompt")
    lines.append("")
    lines.extend(_metrics_table(summary.get("by_prompt") or {}, "Prompt"))
    lines.append("")
    lines.append(
        "Percentages are shown with numerators and denominators. No significance "
        "test is applied; do not interpret differences as statistically significant."
    )
    lines.append("")

    lines.append("## 7. Representative violations")
    lines.append("")
    violating_trials: list[dict[str, Any]] = []
    for trial in trials:
        if not _trial_success(trial):
            continue
        fresh = scoring.score_text(trial["raw_generated_text"])
        if fresh["contains_ascii_hyphen"]:
            violating_trials.append(trial)
    if not violating_trials:
        lines.append("No violating generations were recorded.")
        lines.append("")
    else:
        for trial in violating_trials[:3]:
            fresh = scoring.score_text(trial["raw_generated_text"])
            lines.append(
                f"### Trial `{trial.get('trial_id')}` "
                f"({trial.get('prompt_id')}, {trial.get('category')})"
            )
            lines.append("")
            lines.append(
                f"ASCII hyphen count: {fresh['ascii_hyphen_count']}; positions: "
                f"{fresh['violation_positions']}"
            )
            lines.append("")
            lines.append(_fence(trial["raw_generated_text"]))
            lines.append("")
            lines.append("Context excerpts:")
            lines.append("")
            for context in fresh["violation_contexts"]:
                excerpt = " ".join(context["excerpt"].split())
                lines.append(f"- position {context['position']}: `{excerpt}`")
            lines.append("")
        if len(violating_trials) > 3:
            lines.append(
                f"{len(violating_trials) - 3} additional violating output(s) are in "
                "`outputs.md` and `violations.jsonl`."
            )
            lines.append("")

    lines.append("## 8. Technical failures and missing data")
    lines.append("")
    failures = summary.get("failures") or {}
    if failures.get("count", 0) == 0:
        lines.append("No technical failures were recorded.")
    else:
        lines.append(f"- Failed trials: {failures.get('count')}")
        lines.append(f"- Failures by type: `{json.dumps(failures.get('by_type') or {})}`")
        lines.append(f"- Failed trial ids: `{failures.get('trial_ids')}`")
        lines.append("")
        lines.append(
            "Failed generations are not counted as compliant or violating. No "
            "automatic retries were performed."
        )
    lines.append("")
    if summary.get("missing_trials"):
        lines.append(
            f"- Missing trials relative to the plan: {summary['missing_trials']}. "
            "This can indicate an interrupted or failed run."
        )
        lines.append("")
    validation = summary.get("data_validation") or {}
    if not validation.get("valid", True):
        lines.append("Data validation warnings:")
        lines.append("")
        for warning in validation.get("warnings", []):
            lines.append(f"- {warning}")
        lines.append("")

    lines.append("## 9. Limitations")
    lines.append("")
    limitations = [
        "Results describe only the tested model, prompt set, and generation settings. "
        "They must not be generalized to all language models or all prompts.",
        f"The prompt set contains {summary.get('prompt_count')} enabled prompts. The "
        "PRD suggests 30 to 50; the enabled set is the configuration for this run and "
        "any deviation is recorded in the manifest.",
        f"The evaluated model is {summary.get('model_id')}. The PRD default was "
        "Qwen/Qwen3-4B; any model substitution is recorded in the known deviations.",
        "Scoring uses the entire raw generated text because email-body extraction is "
        "not implemented. Any commentary around the email is scored too.",
        "A fixed seed does not guarantee bit-identical output across hardware and "
        "software versions.",
        "With repeated trials, observations are clustered by prompt; the Wilson "
        "interval treats generations as independent and may understate uncertainty.",
        "No significance tests were performed. Category and formulation differences "
        "are descriptive only.",
        "This experiment does not explain why violations occur and does not evaluate "
        "training interventions.",
    ]
    for limitation in limitations:
        lines.append(f"- {limitation}")
    lines.append("")

    if summary.get("known_deviations"):
        lines.append("### Recorded project deviations")
        lines.append("")
        for deviation in summary["known_deviations"]:
            lines.append(f"- {deviation}")
        lines.append("")

    lines.append("## 10. Reproduction")
    lines.append("")
    lines.append("```bash")
    lines.append("# From the repository root; run in a Colab GPU runtime")
    lines.append("bash scripts/setup_colab.sh")
    lines.append("bash scripts/start_model.sh")
    lines.append("bash scripts/check_model.sh")
    lines.append("bash scripts/run_experiment.sh")
    lines.append(f"python summarize_results.py results/{summary.get('run_id')} --show")
    lines.append("```")
    lines.append("")
    lines.append(
        f"Report generated at {summary.get('generated_at_utc')} from `trials.jsonl`. "
        "All numbers are derived from recorded trials."
    )
    lines.append("")
    return "\n".join(lines)


def write_run_derived_outputs(
    run_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
    trials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recompute and atomically rewrite all derived artifacts for one run."""

    run_path = Path(run_dir)
    if trials is None:
        trials, loaded_manifest = load_run(run_path)
        if manifest is None:
            manifest = loaded_manifest
    manifest = manifest or {}

    summary = compute_summary(trials, manifest)
    summary["run_status"] = summary.get("run_status") or "unknown"

    write_json_atomic(run_path / "summary.json", summary)

    violations = scoring.regenerate_violations(trials)
    write_jsonl_atomic(run_path / "violations.jsonl", violations)

    errors = [
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
        }
        for trial in trials
        if not _trial_success(trial)
    ]
    write_jsonl_atomic(run_path / "errors.jsonl", errors)

    report = build_report_markdown(summary, trials, manifest)
    write_text_atomic(run_path / "report.md", report)
    reporting.write_outputs_md(run_path, trials, summary)

    return summary


def _latest_run(results_dir: Path) -> Path:
    candidates = sorted(
        (path for path in results_dir.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    )
    if not candidates:
        raise FileNotFoundError(f"No run directories found under {results_dir}")
    return candidates[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", type=Path, help="results/<run_id> directory")
    parser.add_argument("--results-dir", type=Path, default=Path("results"))
    parser.add_argument("--show", action="store_true", help="print numbered per-prompt outputs")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument("--force-color", action="store_true")
    parser.add_argument("--max-output-chars", type=int, default=0)
    parser.add_argument("--json", action="store_true", help="print summary JSON")
    args = parser.parse_args(argv)
    if args.max_output_chars < 0:
        print("ERROR: --max-output-chars must be >= 0", file=sys.stderr)
        return 1

    try:
        run_path = args.run_dir or _latest_run(args.results_dir)
        trials, manifest = load_run(run_path)
        summary = write_run_derived_outputs(run_path, manifest=manifest, trials=trials)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    color = reporting.resolve_color(
        "never" if args.no_color else "always" if args.force_color else "auto"
    )
    if args.show:
        for index, trial in enumerate(trials, start=1):
            print(
                reporting.render_trial_card(
                    trial,
                    index,
                    len(trials),
                    color=color,
                    max_output_chars=args.max_output_chars,
                )
            )
    print(reporting.render_summary(summary, trials=trials, color=color))
    print(f"\nRecomputed from: {run_path}")
    print(f"Summary:        {run_path / 'summary.json'}")
    print(f"Report:         {run_path / 'report.md'}")
    print(f"Outputs:        {run_path / 'outputs.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
