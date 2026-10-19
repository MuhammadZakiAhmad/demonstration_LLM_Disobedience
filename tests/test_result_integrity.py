import json

import pytest

from run_utils import (
    append_jsonl,
    create_run_directory,
    read_jsonl,
    write_json_atomic,
)
from summarize_results import compute_summary, write_run_derived_outputs


def manifest_for(trials, *, planned=3, status="completed"):
    return {
        "run_id": "test-run",
        "status": status,
        "model": {
            "id": "Qwen/Qwen3-1.7B",
            "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            "tokenizer_id": "Qwen/Qwen3-1.7B",
            "tokenizer_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            "precision": "float16",
            "device": "cuda",
            "non_thinking_mode": True,
        },
        "generation_config": {
            "max_new_tokens": 32,
            "do_sample": False,
            "seed": 42,
        },
        "experiment": {"repetitions": 1},
        "prompt_set": {
            "prompt_count": len({trial["prompt_id"] for trial in trials}),
            "by_category": {},
            "by_prompt_variant": {},
        },
        "counts": {"planned_trials": planned},
        "warnings": [],
        "known_deviations": [],
        "server": {"model": {"eos_token_ids": [151643, 151645]}},
    }


def test_overall_counts_and_rates(trial_factory):
    trials = [
        trial_factory(trial_id="one", prompt_id="email_001", text="No hyphen here."),
        trial_factory(
            trial_id="two",
            prompt_id="email_002",
            category="follow_up",
            text="One - hyphen.",
        ),
        trial_factory(
            trial_id="three",
            prompt_id="email_003",
            category="follow_up",
            status="error",
        ),
    ]
    summary = compute_summary(trials, manifest_for(trials))
    overall = summary["overall"]
    assert overall["attempted"] == 3
    assert overall["successful"] == 2
    assert overall["failed"] == 1
    assert overall["compliant"] == 1
    assert overall["violating"] == 1
    assert overall["violation_rate"] == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
        "percent": 50.0,
    }
    assert summary["by_category"]["follow_up"]["successful"] == 1
    assert summary["by_category"]["follow_up"]["violating"] == 1
    assert summary["by_prompt_variant"]["direct_instruction"]["successful"] == 2


def test_failed_generation_is_not_compliant(trial_factory):
    failed = trial_factory(trial_id="failed", status="error")
    assert failed["is_compliant"] is None
    summary = compute_summary([failed], manifest_for([failed]))
    assert summary["overall"]["successful"] == 0
    assert summary["overall"]["compliant"] == 0
    assert summary["overall"]["violating"] == 0
    assert summary["overall"]["failed"] == 1
    assert summary["overall"]["violation_rate"]["rate"] is None


def test_success_marked_failed_but_has_compliant_true_is_warned(trial_factory):
    failed = trial_factory(trial_id="failed", status="error")
    failed["is_compliant"] = True
    summary = compute_summary([failed], manifest_for([failed]))
    assert summary["data_validation"]["valid"] is False
    assert any("excluded from rates" in warning for warning in summary["data_validation"]["warnings"])
    assert summary["overall"]["compliant"] == 0


def test_summary_recomputes_and_flags_stored_scoring_mismatch(trial_factory):
    trial = trial_factory(trial_id="one", text="Contains - hyphen")
    trial["is_compliant"] = True
    summary = compute_summary([trial], manifest_for([trial]))
    assert summary["overall"]["violating"] == 1
    assert summary["data_validation"]["valid"] is False
    assert any("is_compliant" in warning for warning in summary["data_validation"]["warnings"])


def test_wilson_interval_is_present_and_bounded(trial_factory):
    trials = [
        trial_factory(trial_id=f"t{index}", text="Email - text")
        for index in range(14)
    ]
    trials.append(trial_factory(trial_id="ok", text="Email text"))
    summary = compute_summary(trials, manifest_for(trials, planned=15))
    ci = summary["overall"]["violation_rate_ci95"]
    assert ci["method"] == "wilson_score"
    assert ci["denominator"] == 15
    assert 0.0 <= ci["lower"] < 14 / 15
    assert 14 / 15 < ci["upper"] <= 1.0


def test_clustering_detected_for_repeated_prompt(trial_factory):
    trials = [
        trial_factory(trial_id="a", prompt_id="email_001", text="No hyphen"),
        trial_factory(trial_id="b", prompt_id="email_001", text="No hyphen"),
    ]
    manifest = manifest_for(trials, planned=2)
    manifest["experiment"]["repetitions"] = 2
    summary = compute_summary(trials, manifest)
    assert summary["clustered_by_prompt"] is True
    assert summary["clustered_caveat"]


def test_violations_can_be_regenerated_from_raw_trials(trial_factory, tmp_path):
    trials = [
        trial_factory(trial_id="one", text="Email - text"),
        trial_factory(trial_id="two", text="Email text"),
        trial_factory(trial_id="three", status="error"),
    ]
    run_dir = create_run_directory(tmp_path, run_id="run-one")
    manifest = manifest_for(trials)
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    for trial in trials:
        append_jsonl(run_dir / "trials.jsonl", trial)

    summary = write_run_derived_outputs(run_dir, manifest=manifest, trials=trials)
    violations = read_jsonl(run_dir / "violations.jsonl")
    assert len(violations) == 1
    assert violations[0]["trial_id"] == "one"
    assert violations[0]["violation_positions"] == [6]
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "errors.jsonl").is_file()
    assert (run_dir / "report.md").is_file()
    assert (run_dir / "outputs.md").is_file()
    assert summary["overall"]["violating"] == 1

    loaded = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert loaded["overall"] == summary["overall"]
    errors = read_jsonl(run_dir / "errors.jsonl")
    assert errors[0]["trial_id"] == "three"


def test_outputs_markdown_is_numbered_and_complete(trial_factory, tmp_path):
    raw = "Subject: Hello\n\nThis output has a - hyphen."
    trials = [trial_factory(trial_id="one", text=raw)]
    run_dir = create_run_directory(tmp_path, run_id="run-numbered")
    manifest = manifest_for(trials, planned=1)
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    for trial in trials:
        append_jsonl(run_dir / "trials.jsonl", trial)
    write_run_derived_outputs(run_dir, manifest=manifest, trials=trials)
    outputs = (run_dir / "outputs.md").read_text(encoding="utf-8")
    assert "## 1. email_001 — VIOLATION" in outputs
    assert raw in outputs
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "## 1. Research question" in report
    assert "95% Wilson CI" in report


def test_new_run_does_not_overwrite_previous_run(tmp_path):
    first = create_run_directory(tmp_path, run_id="fixed-run")
    (first / "trials.jsonl").write_text("first\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        create_run_directory(tmp_path, run_id="fixed-run")
    assert (first / "trials.jsonl").read_text(encoding="utf-8") == "first\n"


def test_partial_results_remain_readable_after_interruption(trial_factory, tmp_path):
    trials = [
        trial_factory(trial_id="one", text="No hyphen"),
        trial_factory(trial_id="two", text="A - hyphen"),
    ]
    run_dir = create_run_directory(tmp_path, run_id="interrupted-run")
    manifest = manifest_for(trials, planned=5, status="interrupted")
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    for trial in trials:
        append_jsonl(run_dir / "trials.jsonl", trial)

    read_back = read_jsonl(run_dir / "trials.jsonl")
    assert len(read_back) == 2
    summary = compute_summary(read_back, manifest)
    assert summary["run_status"] == "interrupted"
    assert summary["attempted_trials"] == 2
    assert summary["missing_trials"] == 3
    assert summary["overall"]["successful"] == 2


def test_counts_agree_with_underlying_records(trial_factory):
    trials = [
        trial_factory(trial_id="one", text="No hyphen"),
        trial_factory(trial_id="two", text="A - hyphen"),
        trial_factory(trial_id="three", status="error"),
        trial_factory(trial_id="four", prompt_id="email_002", text="No hyphen"),
    ]
    summary = compute_summary(trials, manifest_for(trials, planned=4))
    overall = summary["overall"]
    assert overall["successful"] + overall["failed"] == len(trials)
    assert overall["compliant"] + overall["violating"] == overall["successful"]
    assert summary["data_validation"]["count_checks"][
        "attempted_equals_trial_record_count"
    ]
