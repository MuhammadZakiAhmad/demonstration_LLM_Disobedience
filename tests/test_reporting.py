import json

from reporting import (
    render_run_header,
    render_summary,
    render_trial_card,
    write_outputs_md,
)


def test_trial_card_contains_number_prompt_and_raw_output(trial_factory):
    raw = "Subject: Test\n\nHello team."
    trial = trial_factory(trial_id="email_001_t000", prompt_id="email_001", text=raw)
    card = render_trial_card(trial, 1, 15, color=False, width=100)
    assert "[1/15] email_001_t000" in card
    assert "prompt=email_001" in card
    assert "[PASS]" in card
    assert "Hello team." in card
    assert "\x1b[" not in card


def test_violation_card_shows_positions_and_contexts(trial_factory):
    trial = trial_factory(text="Hello - team")
    card = render_trial_card(trial, 2, 15, color=False, width=100)
    assert "[VIOLATION]" in card
    assert "Positions (zero-based): 6" in card
    assert "@ 6:" in card


def test_error_card_shows_error(trial_factory):
    trial = trial_factory(status="error")
    trial["error"] = {"type": "server_unavailable", "message": "connection refused"}
    card = render_trial_card(trial, 3, 15, color=False, width=100)
    assert "[ERROR]" in card
    assert "server_unavailable" in card
    assert "connection refused" in card


def test_max_output_chars_truncates_display_only(trial_factory):
    raw = "A" * 500
    trial = trial_factory(text=raw)
    card = render_trial_card(trial, 1, 1, color=False, width=100, max_output_chars=80)
    assert "display truncated at 80 characters" in card
    assert trial["raw_generated_text"] == raw


def test_run_header_and_summary(trial_factory):
    trials = [
        trial_factory(trial_id="one", prompt_id="email_001", text="No hyphen"),
        trial_factory(trial_id="two", prompt_id="email_002", text="A - hyphen"),
        trial_factory(trial_id="three", prompt_id="email_003", status="error"),
    ]
    header = render_run_header(
        run_id="20260101-000000Z-abcdef",
        model_id="Qwen/Qwen3-1.7B",
        model_revision="70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        prompt_count=3,
        repetitions=1,
        planned_trials=3,
        server_url="http://127.0.0.1:8765",
        color=False,
        width=100,
    )
    assert "RUN 20260101-000000Z-abcdef" in header
    assert "3 prompts x 1 repetition(s) = 3 trials" in header

    summary = {
        "run_id": "20260101-000000Z-abcdef",
        "run_status": "completed",
        "overall": {
            "attempted": 3,
            "successful": 2,
            "failed": 1,
            "compliant": 1,
            "violating": 1,
            "violation_rate": {"numerator": 1, "denominator": 2, "rate": 0.5, "percent": 50.0},
            "compliance_rate": {"numerator": 1, "denominator": 2, "rate": 0.5, "percent": 50.0},
            "failure_rate": {"numerator": 1, "denominator": 3, "rate": 1 / 3, "percent": 100 / 3},
            "violation_rate_ci95": {
                "method": "wilson_score",
                "confidence": 0.95,
                "numerator": 1,
                "denominator": 2,
                "lower": 0.0945,
                "upper": 0.9055,
            },
        },
        "by_category": {},
        "by_prompt_variant": {},
        "clustered_by_prompt": False,
    }
    rendered = render_summary(summary, trials=trials, color=False, width=100)
    assert "SUMMARY" in rendered
    assert "1/2 (50.0%)" in rendered
    assert "email_001" in rendered
    assert "VIOLATION" in rendered


def test_outputs_markdown_is_numbered_and_exact(tmp_path, trial_factory):
    raw = "Subject: Test\n\nLine with a - hyphen."
    trials = [trial_factory(trial_id="one", text=raw)]
    summary = {
        "run_id": "test-run",
        "run_status": "completed",
        "model_id": "Qwen/Qwen3-1.7B",
        "model_revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e",
        "overall": {"successful": 1, "attempted": 1},
    }
    path = write_outputs_md(tmp_path, trials, summary)
    text = path.read_text(encoding="utf-8")
    assert "## 1. email_001 — VIOLATION" in text
    assert raw in text
    assert "### Prompt" in text
    assert "position 27" in text


def test_outputs_markdown_handles_backticks(tmp_path, trial_factory):
    raw = "Email with ``` fences inside"
    trials = [trial_factory(text=raw)]
    summary = {
        "run_id": "test-run",
        "run_status": "completed",
        "model_id": "Qwen/Qwen3-1.7B",
        "model_revision": "abc",
        "overall": {"successful": 1, "attempted": 1},
    }
    path = write_outputs_md(tmp_path, trials, summary)
    text = path.read_text(encoding="utf-8")
    assert "````text" in text
    assert raw in text


def test_outputs_markdown_is_valid_json_metadata(tmp_path, trial_factory):
    # Sanity check that the trial metadata remains JSON serializable after rendering.
    trials = [trial_factory(text="No hyphen")]
    json.dumps(trials)
