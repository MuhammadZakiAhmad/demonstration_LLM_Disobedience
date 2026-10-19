"""Runner interruption behavior without a real model or network server."""

import json
from pathlib import Path

import main


class _InterruptingClient:
    base_url = "http://127.0.0.1:0"

    def health(self):
        return {
            "status": "ready",
            "backend_mode": "real",
            "fake_backend": False,
            "config_sha256": "test",
            "model": {
                "model_id": "Qwen/Qwen3-1.7B",
                "model_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
                "tokenizer_id": "Qwen/Qwen3-1.7B",
                "tokenizer_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
                "precision": "float16",
                "device": "cuda:0",
                "non_thinking_mode": True,
                "eos_token_ids": [151643, 151645],
                "warnings": [],
            },
        }

    def generate(self, messages, generation_config, seed):
        raise KeyboardInterrupt


def test_interrupted_run_is_finalized_honestly(tmp_path, monkeypatch, capsys):
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    config["experiment"]["prompts_path"] = str(root / "prompts.jsonl")
    config["experiment"]["repetitions"] = 1
    config["results"]["directory"] = str(tmp_path / "results")
    config["_config_dir"] = str(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    normalized = main.validate_config(config)

    monkeypatch.setattr(main, "ServerClient", lambda host, port, timeout: _InterruptingClient())
    monkeypatch.setattr(main, "_model_matches", lambda health, model, config_hash: [])

    prompts = [
        {
            "prompt_id": "email_001",
            "category": "professional_email",
            "prompt_variant": "direct_instruction",
            "system_instruction": "Never use the hyphen character.",
            "user_prompt": "Write an email.",
            "expected_output_type": "email",
            "enabled": True,
        },
        {
            "prompt_id": "email_002",
            "category": "follow_up",
            "prompt_variant": "natural_instruction",
            "system_instruction": "Never use the hyphen character.",
            "user_prompt": "Write another email.",
            "expected_output_type": "email",
            "enabled": True,
        },
    ]

    result = main.run_experiment(
        config_path=config_path,
        config=normalized,
        prompts_path=root / "prompts.jsonl",
        prompts=prompts,
        prompt_warnings=[],
        overrides={},
    )
    assert result == 130

    run_dir = next((tmp_path / "results").iterdir())
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "interrupted"
    assert manifest["counts"]["planned_trials"] == 2
    assert manifest["counts"]["attempted_trials"] == 1
    assert manifest["counts"]["failed"] == 1
    assert manifest["counts"]["interrupted"] is True
    assert manifest["end_time_utc"]

    trials = [
        json.loads(line)
        for line in (run_dir / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(trials) == 1
    assert trials[0]["generation_status"] == "error"
    assert trials[0]["error"]["type"] == "interrupted"
    assert trials[0]["is_compliant"] is None

    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["run_status"] == "interrupted"
    assert summary["attempted_trials"] == 1
    assert summary["missing_trials"] == 1
    assert summary["overall"]["successful"] == 0
    assert summary["overall"]["failed"] == 1

    captured = capsys.readouterr()
    assert "Run status : interrupted" in captured.out
