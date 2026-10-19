"""Optional real-model smoke test.

This test is skipped by default. Enable it only in a GPU environment where the
pinned model can be downloaded:

    RUN_MODEL_SMOKE_TEST=1 pytest -q tests/test_model_smoke.py

It performs one short generation and verifies the Qwen3 EOS/non-thinking
wiring. It does not evaluate compliance.
"""

import json
import os
from pathlib import Path

import pytest

RUN_SMOKE = os.environ.get("RUN_MODEL_SMOKE_TEST") == "1"


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


pytestmark = [
    pytest.mark.skipif(not RUN_SMOKE, reason="set RUN_MODEL_SMOKE_TEST=1 to enable"),
    pytest.mark.skipif(not _cuda_available(), reason="CUDA GPU not available"),
]


def test_single_short_generation():
    from model_loader import load_model

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    model = load_model(config)
    assert model.eos_token_ids, "EOS ids must be non-empty"
    assert 151645 in model.eos_token_ids
    result = model.generate(
        [
            {"role": "system", "content": "Return only the word hello."},
            {"role": "user", "content": "Say hello."},
        ],
        {
            "max_new_tokens": 16,
            "do_sample": False,
            "repetition_penalty": 1.0,
        },
        seed=42,
    )
    assert isinstance(result["generated_text"], str)
    assert result["finish_reason"] in ("eos", "length", "no_tokens")
    assert result["metadata"]["eos_token_ids"] == model.eos_token_ids
