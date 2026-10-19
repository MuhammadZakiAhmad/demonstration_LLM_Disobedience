import json
from pathlib import Path

from export_hf_bundle import export_bundle
from run_utils import (
    append_jsonl,
    create_run_directory,
    sha256_file,
    write_json_atomic,
    write_text_atomic,
)
from summarize_results import write_run_derived_outputs


def test_export_bundle_contains_expected_files_and_checksums(tmp_path, trial_factory):
    root = Path(__file__).resolve().parents[1]
    run_dir = create_run_directory(tmp_path / "results", run_id="20260101-000000Z-abcdef")
    prompts_source = root / "prompts.jsonl"
    config_source = root / "config.json"
    prompts_copy = run_dir / "prompts_snapshot.jsonl"
    config_copy = run_dir / "config_snapshot.json"
    prompts_copy.write_bytes(prompts_source.read_bytes())
    config_copy.write_bytes(config_source.read_bytes())

    trial = trial_factory(text="Subject: Test\n\nA - violating email.", run_id=run_dir.name)
    append_jsonl(run_dir / "trials.jsonl", trial)
    manifest = {
        "run_id": run_dir.name,
        "status": "completed",
        "model": {
            "id": "Qwen/Qwen3-1.7B",
            "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            "tokenizer_id": "Qwen/Qwen3-1.7B",
            "tokenizer_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            "precision": "float16",
            "device": "cuda",
            "non_thinking_mode": True,
        },
        "generation_config": {"max_new_tokens": 32, "do_sample": False, "seed": 42},
        "experiment": {"repetitions": 1, "prompts_path": str(prompts_copy)},
        "prompt_file": {"path": str(prompts_copy), "sha256": sha256_file(prompts_copy)},
        "config_file": {"path": str(config_copy), "sha256": sha256_file(config_copy)},
        "prompt_set": {"prompt_count": 15},
        "counts": {"planned_trials": 1},
        "warnings": [],
        "known_deviations": ["Test deviation."],
        "server": {"model": {"eos_token_ids": [151643, 151645]}},
    }
    write_json_atomic(run_dir / "run_manifest.json", manifest)
    write_text_atomic(run_dir / "environment.txt", "Test environment\n")
    write_run_derived_outputs(run_dir, manifest=manifest, trials=[trial])

    output_dir = tmp_path / "bundle"
    export_bundle(run_dir, output_dir, root)

    expected = {
        "README.md",
        "RESEARCH.md",
        "prompts.jsonl",
        "config.json",
        "run_manifest.json",
        "trials.jsonl",
        "violations.jsonl",
        "errors.jsonl",
        "summary.json",
        "environment.txt",
        "report.md",
        "outputs.md",
        "checksums.sha256",
    }
    assert {path.name for path in output_dir.iterdir()} == expected
    readme = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "Research question" in readme
    assert "Nothing was uploaded" not in readme  # that text belongs to the CLI

    public_manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert public_manifest["prompt_file"]["path"] == "prompts.jsonl"
    assert public_manifest["config_file"]["path"] == "config.json"
    assert "publication_note" in public_manifest

    checksums = (output_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "README.md" in checksums
    assert "summary.json" in checksums
