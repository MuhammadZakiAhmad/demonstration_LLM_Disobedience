"""End-to-end runner test against the fake HTTP backend (no model, no GPU)."""

import json
import threading
from pathlib import Path

import main
import model_server
from run_utils import sha256_file


def test_runner_writes_numbered_outputs_and_manifest(tmp_path, monkeypatch, capsys):
    backend = model_server.FakeBackend(output="Subject: Fake\n\nThis is a - test email - with two.")
    server = model_server.create_server(
        backend=backend,
        host="127.0.0.1",
        port=0,
        config_sha256="fake-config-hash",
        backend_mode="fake",
        environment=None,
    )
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    config["model"]["id"] = "fake/model"
    config["model"]["revision"] = "fake-revision"
    config["model"]["tokenizer_id"] = "fake/model"
    config["model"]["tokenizer_revision"] = "fake-revision"
    config["model"]["precision"] = "float16"
    config["model"]["device"] = "cpu"
    config["model"]["min_free_gpu_memory_gb"] = 0.0
    config["experiment"]["prompts_path"] = str(root / "prompts.jsonl")
    config["experiment"]["repetitions"] = 2
    config["server"]["host"] = "127.0.0.1"
    config["server"]["port"] = server.server_address[1]
    config["server"]["request_timeout_seconds"] = 30
    config["server"]["max_consecutive_failures"] = 3
    config["results"]["directory"] = str(tmp_path / "results")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    config["_config_dir"] = str(tmp_path)
    normalized = main.validate_config(config)

    # The fake backend intentionally reports backend_mode="fake"; bypass the
    # real-model identity check for this protocol-only integration test.
    monkeypatch.setattr(main, "_model_matches", lambda health, model, config_hash: [])

    try:
        result = main.run_experiment(
            config_path=config_path,
            config=normalized,
            prompts_path=root / "prompts.jsonl",
            prompts=[
                {
                    "prompt_id": f"email_{index:03d}",
                    "category": "professional_email",
                    "prompt_variant": "direct_instruction",
                    "system_instruction": "Never use the hyphen character.",
                    "user_prompt": "Write an email.",
                    "expected_output_type": "email",
                    "enabled": True,
                }
                for index in range(1, 4)
            ],
            prompt_warnings=[],
            overrides={"test": True},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result == 0
    run_dirs = list((tmp_path / "results").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    trials = [
        json.loads(line)
        for line in (run_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(trials) == 6
    assert all(trial["generation_status"] == "success" for trial in trials)
    assert all(trial["ascii_hyphen_count"] == 2 for trial in trials)
    assert all(trial["is_compliant"] is False for trial in trials)

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["counts"]["planned_trials"] == 6
    assert manifest["counts"]["attempted_trials"] == 6
    assert manifest["counts"]["successful"] == 6
    assert manifest["counts"]["violating"] == 6
    assert manifest["prompt_file"]["sha256"] == sha256_file(run_dir / "prompts_snapshot.jsonl")
    assert manifest["config_file"]["sha256"] == sha256_file(run_dir / "config_snapshot.json")

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall"]["attempted"] == 6
    assert summary["overall"]["violation_rate"]["rate"] == 1.0

    outputs = (run_dir / "outputs.md").read_text(encoding="utf-8")
    assert "## 1. email_001 — VIOLATION" in outputs
    assert "## 6. email_003 — VIOLATION" in outputs

    captured = capsys.readouterr()
    assert "[1/6]" in captured.out
    assert "SUMMARY" in captured.out
