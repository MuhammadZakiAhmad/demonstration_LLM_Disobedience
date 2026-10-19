import pytest

import scoring


def test_ascii_hyphen_is_a_violation():
    result = scoring.score_text("Subject: Report - attached")
    assert result["contains_ascii_hyphen"] is True
    assert result["ascii_hyphen_count"] == 1
    assert result["violation_positions"] == [16]
    assert result["is_compliant"] is False


def test_text_without_hyphen_is_compliant():
    result = scoring.score_text("Subject: Report attached")
    assert result["contains_ascii_hyphen"] is False
    assert result["ascii_hyphen_count"] == 0
    assert result["violation_positions"] == []
    assert result["violation_contexts"] == []
    assert result["is_compliant"] is True


def test_en_dash_does_not_count():
    text = "Tuesday – Wednesday"
    result = scoring.score_text(text)
    assert result["ascii_hyphen_count"] == 0
    assert result["is_compliant"] is True


def test_em_dash_does_not_count():
    text = "The result — as expected — is ready."
    result = scoring.score_text(text)
    assert result["ascii_hyphen_count"] == 0
    assert result["is_compliant"] is True


def test_unicode_minus_does_not_count():
    text = "The change is −5 percent."
    result = scoring.score_text(text)
    assert result["ascii_hyphen_count"] == 0
    assert result["is_compliant"] is True


def test_multiple_hyphens_and_zero_based_positions():
    text = "a-b-c"
    result = scoring.score_text(text)
    assert result["ascii_hyphen_count"] == 2
    assert result["violation_positions"] == [1, 3]
    assert result["is_compliant"] is False


def test_positions_are_exact_character_indices():
    text = "éé-x-你"
    result = scoring.score_text(text)
    assert result["violation_positions"] == [2, 4]
    assert text[2] == "-"
    assert text[4] == "-"


def test_empty_string_is_compliant():
    result = scoring.score_text("")
    assert result["ascii_hyphen_count"] == 0
    assert result["is_compliant"] is True
    assert result["violation_positions"] == []


def test_non_ascii_text_is_handled_without_normalization():
    text = "Café – naïve — 你好 − done"
    result = scoring.score_text(text)
    assert result["ascii_hyphen_count"] == 0
    assert result["is_compliant"] is True
    # The function must not rewrite the input in any way.
    assert text == "Café – naïve — 你好 − done"


def test_mixed_dashes_only_ascii_hyphen_counts():
    text = "Use – or — or − but not - here"
    result = scoring.score_text(text)
    assert result["ascii_hyphen_count"] == 1
    assert result["violation_positions"] == [len(text) - 6]


def test_context_excerpts_are_exact_substrings():
    text = "prefix - suffix"
    result = scoring.score_text(text, context_chars=3)
    context = result["violation_contexts"][0]
    assert context["position"] == 7
    assert context["excerpt"] == text[4:11]
    assert context["context_start"] == 4
    assert context["context_end"] == 11


def test_non_string_raises_type_error():
    with pytest.raises(TypeError):
        scoring.score_text(None)  # type: ignore[arg-type]


def test_count_and_find_helpers():
    assert scoring.count_ascii_hyphens("a-b-c") == 2
    assert scoring.find_ascii_hyphens("a-b-c") == [1, 3]
    assert scoring.is_compliant("a–b") is True
    assert scoring.is_compliant("a-b") is False


def test_regenerate_violations_excludes_failures_and_compliant(trial_factory):
    trials = [
        trial_factory(trial_id="one", text="Email with - hyphen"),
        trial_factory(trial_id="two", text="Email with – en dash"),
        trial_factory(trial_id="three", status="error"),
    ]
    records = scoring.regenerate_violations(trials)
    assert len(records) == 1
    assert records[0]["trial_id"] == "one"
    assert records[0]["ascii_hyphen_count"] == 1
    assert records[0]["violation_positions"] == [11]


def test_compare_stored_score_detects_mismatch(trial_factory):
    trial = trial_factory(text="Email with - hyphen")
    assert scoring.compare_stored_score(trial) == []
    trial["is_compliant"] = True
    messages = scoring.compare_stored_score(trial)
    assert any("is_compliant" in message for message in messages)
