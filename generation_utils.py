"""Pure helpers for generation safety and diagnostics.

These functions avoid importing torch/transformers so that CPU-only tests can
exercise the tricky EOS and repetition logic without loading a model.
"""

from __future__ import annotations

import re
from typing import Any, Iterable


class GenerationConfigError(ValueError):
    """Raised when generation settings are internally unsafe or inconsistent."""


def _normalize_one_eos(source: Any, source_name: str) -> list[int]:
    if source is None:
        return []
    if isinstance(source, bool):
        raise GenerationConfigError(f"{source_name} must not be a boolean")
    if isinstance(source, int):
        values = [source]
    elif isinstance(source, (list, tuple, set)):
        values = list(source)
    else:
        raise GenerationConfigError(
            f"{source_name} must be an int or a sequence of ints, got {type(source).__name__}"
        )

    result: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise GenerationConfigError(
                f"{source_name} contains a non-integer value: {value!r}"
            )
        if value < 0:
            raise GenerationConfigError(
                f"{source_name} contains a negative token id: {value}"
            )
        result.append(value)
    return result


def normalize_eos_token_ids(model_eos: Any, tokenizer_eos: Any) -> list[int]:
    """Merge model and tokenizer EOS ids into one sorted, unique, non-empty list.

    Qwen3's generation config uses two EOS ids (``<|im_end|>`` and
    ``<|endoftext|>``). Passing only ``tokenizer.eos_token_id`` (one id) is a
    common cause of runaway generation, so the server refuses to start without a
    validated, non-empty EOS list.
    """

    ids = _normalize_one_eos(model_eos, "model eos_token_id")
    ids.extend(_normalize_one_eos(tokenizer_eos, "tokenizer eos_token_id"))
    unique = sorted(set(ids))
    if not unique:
        raise GenerationConfigError(
            "No EOS token id could be resolved from the model or tokenizer. "
            "Refusing to start: generation could fail to terminate."
        )
    return unique


def determine_finish_reason(
    generated_token_ids: Iterable[int],
    eos_token_ids: Iterable[int],
) -> str:
    """Classify why generation stopped.

    ``eos`` means the final generated token is one of the validated EOS ids.
    ``length`` means the token budget was exhausted. ``no_tokens`` means the
    model returned an empty completion.
    """

    eos_set = set(int(value) for value in eos_token_ids)
    token_ids = [int(value) for value in generated_token_ids]
    if not token_ids:
        return "no_tokens"
    if token_ids[-1] in eos_set:
        return "eos"
    return "length"


_WORD_RE = re.compile(r"\S+")
_LINE_RE = re.compile(r"[^\n]+")


def detect_repetition(
    text: str,
    ngram_size: int = 8,
    min_repeats: int = 4,
    min_repeated_lines: int = 3,
) -> dict[str, Any]:
    """Heuristically detect degenerate loops in generated text.

    This is diagnostic only. It never alters or retries the generation. A loop
    is reported when the same word n-gram occurs at least ``min_repeats`` times,
    or when the same non-empty line occurs at least ``min_repeated_lines`` times.
    Thresholds are intentionally conservative for ordinary email prose.
    """

    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    if ngram_size < 2:
        raise ValueError("ngram_size must be >= 2")
    if min_repeats < 2:
        raise ValueError("min_repeats must be >= 2")
    if min_repeated_lines < 2:
        raise ValueError("min_repeated_lines must be >= 2")

    words = _WORD_RE.findall(text)
    ngram_counts: dict[tuple[str, ...], int] = {}
    for index in range(0, len(words) - ngram_size + 1):
        gram = tuple(words[index : index + ngram_size])
        ngram_counts[gram] = ngram_counts.get(gram, 0) + 1

    best_ngram: tuple[str, ...] | None = None
    best_count = 0
    for gram, count in ngram_counts.items():
        if count > best_count:
            best_ngram = gram
            best_count = count

    line_counts: dict[str, int] = {}
    for line in _LINE_RE.findall(text):
        stripped = line.strip()
        if stripped:
            line_counts[stripped] = line_counts.get(stripped, 0) + 1

    best_line: str | None = None
    best_line_count = 0
    for line, count in line_counts.items():
        if count > best_line_count:
            best_line = line
            best_line_count = count

    suspected_ngram = best_count >= min_repeats
    suspected_line = best_line_count >= min_repeated_lines
    return {
        "suspected_loop": suspected_ngram or suspected_line,
        "repeated_ngram": " ".join(best_ngram) if suspected_ngram and best_ngram else None,
        "repeated_ngram_count": best_count if suspected_ngram else 0,
        "repeated_line": best_line if suspected_line else None,
        "repeated_line_count": best_line_count if suspected_line else 0,
        "ngram_size": ngram_size,
        "min_repeats": min_repeats,
        "min_repeated_lines": min_repeated_lines,
    }


def truncation_warning(finish_reason: str) -> str | None:
    """Return a warning string when the model hit the token limit."""

    if finish_reason == "length":
        return (
            "Generation reached max_new_tokens before an EOS token. The output is "
            "preserved exactly as generated and scored, but it may be incomplete."
        )
    if finish_reason == "no_tokens":
        return "Generation produced no completion tokens."
    return None
