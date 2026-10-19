import pytest

from generation_utils import (
    GenerationConfigError,
    detect_repetition,
    determine_finish_reason,
    normalize_eos_token_ids,
    truncation_warning,
)


def test_qwen3_model_and_tokenizer_eos_ids_are_merged():
    assert normalize_eos_token_ids([151645, 151643], 151645) == [151643, 151645]


def test_single_eos_id_is_accepted():
    assert normalize_eos_token_ids(1, None) == [1]


def test_missing_eos_is_rejected():
    with pytest.raises(GenerationConfigError):
        normalize_eos_token_ids(None, None)
    with pytest.raises(GenerationConfigError):
        normalize_eos_token_ids([], [])


def test_invalid_eos_values_are_rejected():
    with pytest.raises(GenerationConfigError):
        normalize_eos_token_ids("151645", None)
    with pytest.raises(GenerationConfigError):
        normalize_eos_token_ids([True], None)
    with pytest.raises(GenerationConfigError):
        normalize_eos_token_ids([-1], None)


def test_finish_reason_eos():
    assert determine_finish_reason([5, 6, 151645], [151643, 151645]) == "eos"
    assert determine_finish_reason([5, 6, 151643], [151643, 151645]) == "eos"


def test_finish_reason_length():
    assert determine_finish_reason([5, 6, 7], [151643, 151645]) == "length"


def test_finish_reason_no_tokens():
    assert determine_finish_reason([], [151645]) == "no_tokens"


def test_repetition_detected_for_repeated_phrase():
    phrase = "this is a repeated sentence that keeps coming back again and again"
    text = " ".join([phrase] * 4)
    result = detect_repetition(text, ngram_size=8, min_repeats=4)
    assert result["suspected_loop"] is True
    assert result["repeated_ngram_count"] >= 4


def test_repetition_not_flagged_for_normal_email():
    text = (
        "Subject: Quarterly report\n\n"
        "Hello team,\n\n"
        "The quarterly report is attached. Please review your sections and send "
        "feedback by Thursday. Thank you for your work this quarter.\n\n"
        "Best regards,\nAlex"
    )
    result = detect_repetition(text)
    assert result["suspected_loop"] is False


def test_repeated_lines_detected():
    text = "Subject: Notice\n\n" + "Please review this line.\n" * 3
    result = detect_repetition(text, min_repeated_lines=3)
    assert result["suspected_loop"] is True
    assert result["repeated_line_count"] >= 3


def test_truncation_warning():
    assert truncation_warning("length") is not None
    assert truncation_warning("eos") is None
    assert truncation_warning("no_tokens") is not None


def test_repetition_rejects_bad_arguments():
    with pytest.raises(ValueError):
        detect_repetition("text", ngram_size=1)
    with pytest.raises(TypeError):
        detect_repetition(None)  # type: ignore[arg-type]
