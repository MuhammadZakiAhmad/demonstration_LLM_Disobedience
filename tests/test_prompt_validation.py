import json
from pathlib import Path

import pytest

from prompt_validation import (
    PromptValidationError,
    load_prompts,
    select_prompts,
    summarize_prompt_set,
)

ROOT = Path(__file__).resolve().parents[1]


def record(prompt_id="email_001", *, enabled=True, **overrides):
    data = {
        "prompt_id": prompt_id,
        "category": "professional_email",
        "prompt_variant": "direct_instruction",
        "system_instruction": "Never use the ASCII hyphen-minus character (-).",
        "user_prompt": "Write an email.",
        "expected_output_type": "email",
        "enabled": enabled,
    }
    data.update(overrides)
    return data


def write_jsonl(path, records, *, blank_before=None):
    lines = []
    if blank_before:
        lines.extend([""] * blank_before)
    lines.extend(json.dumps(item) if isinstance(item, dict) else str(item) for item in records)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_valid_jsonl_is_accepted(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("email_001"), record("email_002")],
    )
    prompts, warnings = load_prompts(path)
    assert [prompt["prompt_id"] for prompt in prompts] == ["email_001", "email_002"]
    assert warnings == []


def test_invalid_json_reports_line_number(tmp_path):
    path = tmp_path / "prompts.jsonl"
    path.write_text(
        json.dumps(record("email_001")) + "\n{not json}\n",
        encoding="utf-8",
    )
    with pytest.raises(PromptValidationError) as exc_info:
        load_prompts(path)
    message = str(exc_info.value)
    assert "line 2" in message
    assert "invalid JSON" in message


def test_duplicate_prompt_ids_rejected(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("email_001"), record("email_001")],
    )
    with pytest.raises(PromptValidationError) as exc_info:
        load_prompts(path)
    assert "duplicate prompt_id" in str(exc_info.value)


def test_missing_required_fields_rejected(tmp_path):
    invalid = record("email_001")
    del invalid["user_prompt"]
    path = write_jsonl(tmp_path / "prompts.jsonl", [invalid])
    with pytest.raises(PromptValidationError) as exc_info:
        load_prompts(path)
    assert "missing required field 'user_prompt'" in str(exc_info.value)


def test_wrong_field_types_rejected(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("email_001", enabled="yes")],
    )
    with pytest.raises(PromptValidationError) as exc_info:
        load_prompts(path)
    assert "'enabled' must be true or false" in str(exc_info.value)


def test_disabled_prompts_are_excluded(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("email_001"), record("email_002", enabled=False)],
    )
    prompts, _ = load_prompts(path)
    assert [prompt["prompt_id"] for prompt in prompts] == ["email_001"]

    all_prompts, _ = load_prompts(path, include_disabled=True)
    assert [prompt["prompt_id"] for prompt in all_prompts] == ["email_001", "email_002"]


def test_blank_lines_rejected(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("email_001")],
        blank_before=1,
    )
    with pytest.raises(PromptValidationError) as exc_info:
        load_prompts(path)
    assert "blank line" in str(exc_info.value)
    assert "line 1" in str(exc_info.value)


def test_expected_output_type_must_be_email(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("email_001", expected_output_type="letter")],
    )
    with pytest.raises(PromptValidationError) as exc_info:
        load_prompts(path)
    assert "expected_output_type must be 'email'" in str(exc_info.value)


def test_ordering_is_file_order(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [record("z_prompt"), record("a_prompt"), record("m_prompt")],
    )
    prompts, _ = load_prompts(path)
    assert [prompt["prompt_id"] for prompt in prompts] == ["z_prompt", "a_prompt", "m_prompt"]


def test_selection_preserves_file_order(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [
            record("email_001"),
            record("email_002", category="follow_up"),
            record("email_003", category="follow_up"),
        ],
    )
    prompts, _ = load_prompts(path)
    selected = select_prompts(prompts, include_prompt_ids=["email_003", "email_001"])
    assert [prompt["prompt_id"] for prompt in selected] == ["email_001", "email_003"]

    selected = select_prompts(prompts, include_categories=["follow_up"])
    assert [prompt["prompt_id"] for prompt in selected] == ["email_002", "email_003"]


def test_unknown_selection_id_rejected(tmp_path):
    path = write_jsonl(tmp_path / "prompts.jsonl", [record("email_001")])
    prompts, _ = load_prompts(path)
    with pytest.raises(PromptValidationError):
        select_prompts(prompts, include_prompt_ids=["missing"])


def test_prompt_set_summary(tmp_path):
    path = write_jsonl(
        tmp_path / "prompts.jsonl",
        [
            record("email_001"),
            record("email_002", category="follow_up"),
            record("email_003", prompt_variant="natural_instruction"),
        ],
    )
    prompts, _ = load_prompts(path)
    summary = summarize_prompt_set(prompts)
    assert summary["prompt_count"] == 3
    assert summary["by_category"] == {"follow_up": 1, "professional_email": 2}
    assert summary["by_prompt_variant"] == {
        "direct_instruction": 2,
        "natural_instruction": 1,
    }


def test_repository_prompt_file_is_valid():
    prompts, warnings = load_prompts(ROOT / "prompts.jsonl")
    assert len(prompts) == 50
    assert prompts[0]["prompt_id"] == "email_001"
    assert prompts[-1]["prompt_id"] == "email_050"
    assert warnings == []
