import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scoring


@pytest.fixture
def trial_factory():
    """Build synthetic trial records using the real scoring implementation."""

    def make(
        *,
        trial_id="email_001_t000",
        prompt_id="email_001",
        category="professional_email",
        prompt_variant="direct_instruction",
        trial_index=0,
        text="Subject: Test\n\nCompliant email text.",
        status="success",
        finish_reason="eos",
        timestamp="2026-01-01T00:00:00Z",
        run_id="test-run",
    ):
        record = {
            "run_id": run_id,
            "trial_id": trial_id,
            "prompt_id": prompt_id,
            "category": category,
            "prompt_variant": prompt_variant,
            "trial_index": trial_index,
            "timestamp_utc": timestamp,
            "model_id": "Qwen/Qwen3-1.7B",
            "model_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
            "generation_config": {"max_new_tokens": 32, "do_sample": False, "seed": 42},
            "system_instruction": "Never use the ASCII hyphen-minus character (-).",
            "user_prompt": "Write a short email.",
            "expected_output_type": "email",
            "raw_generated_text": text if status == "success" else None,
            "extracted_email_text": None,
            "generation_status": status,
            "error": None if status == "success" else {"type": "server_error", "message": "boom"},
            "finish_reason": finish_reason if status == "success" else None,
            "warnings": [],
            "generation_duration_seconds": 1.0,
            "generation_metadata": {"repetition_heuristic": {"suspected_loop": False}},
        }
        if status == "success":
            score = scoring.score_text(text)
            record.update(
                {
                    "contains_ascii_hyphen": score["contains_ascii_hyphen"],
                    "ascii_hyphen_count": score["ascii_hyphen_count"],
                    "violation_positions": score["violation_positions"],
                    "violation_contexts": score["violation_contexts"],
                    "is_compliant": score["is_compliant"],
                    "scoring_version": score["scoring_version"],
                    "scored_text_source": score["scored_text_source"],
                }
            )
        else:
            record.update(
                {
                    "contains_ascii_hyphen": None,
                    "ascii_hyphen_count": None,
                    "violation_positions": None,
                    "violation_contexts": None,
                    "is_compliant": None,
                }
            )
        return record

    return make
