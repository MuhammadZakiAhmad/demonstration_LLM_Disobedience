"""Exact character-level scoring for the hyphen-compliance experiment.

Scoring rule
------------
The prohibited character is the literal ASCII hyphen-minus, U+002D ("-").
No normalization, replacement, Unicode folding, or dash conversion is performed.
En dash (U+2013), em dash (U+2014), and the Unicode minus sign (U+2212) are
different characters and do not count as violations of this constraint.

The primary score applies to the complete raw generated text. Email-body
extraction is not implemented; that keeps the primary score independent of a
fragile parsing step and is documented in the run manifest.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

SCORING_VERSION = "1.0.0"
PROHIBITED_CHARACTER = "-"
PROHIBITED_CODEPOINT = "U+002D"
DEFAULT_CONTEXT_CHARS = 40


def _validate_text(text: str) -> None:
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")


def score_text(text: str, context_chars: int = DEFAULT_CONTEXT_CHARS) -> dict[str, Any]:
    """Score one generated string using the exact ASCII hyphen-minus rule.

    Positions are zero-based Python string indices. Context excerpts are exact
    substrings around each occurrence; they are not whitespace-normalized here.
    """

    _validate_text(text)
    if not isinstance(context_chars, int) or context_chars < 0:
        raise ValueError("context_chars must be a non-negative integer")

    positions: list[int] = []
    contexts: list[dict[str, Any]] = []

    for position, character in enumerate(text):
        if character != PROHIBITED_CHARACTER:
            continue
        positions.append(position)
        start = max(0, position - context_chars)
        end = min(len(text), position + 1 + context_chars)
        contexts.append(
            {
                "position": position,
                "context_start": start,
                "context_end": end,
                "excerpt": text[start:end],
            }
        )

    count = len(positions)
    return {
        "contains_ascii_hyphen": count > 0,
        "ascii_hyphen_count": count,
        "violation_positions": positions,
        "violation_contexts": contexts,
        "is_compliant": count == 0,
        "scoring_version": SCORING_VERSION,
        "prohibited_character": PROHIBITED_CHARACTER,
        "prohibited_codepoint": PROHIBITED_CODEPOINT,
        "scored_text_source": "raw_generated_text",
    }


def count_ascii_hyphens(text: str) -> int:
    """Return the number of literal ASCII hyphen-minus characters in *text*."""

    _validate_text(text)
    return text.count(PROHIBITED_CHARACTER)


def find_ascii_hyphens(text: str) -> list[int]:
    """Return zero-based positions of every literal ASCII hyphen-minus."""

    _validate_text(text)
    return [index for index, character in enumerate(text) if character == PROHIBITED_CHARACTER]


def is_compliant(text: str) -> bool:
    """Return True only when *text* contains no literal ASCII hyphen-minus."""

    return count_ascii_hyphens(text) == 0


def regenerate_violations(
    trials: Iterable[Mapping[str, Any]],
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> list[dict[str, Any]]:
    """Rebuild violation records from raw trial records.

    Only successful generations are scored. Failed trials are never classified
    as compliant or violating. The output is deterministic for a given
    ``trials.jsonl`` and scoring implementation version.
    """

    records: list[dict[str, Any]] = []
    for trial in trials:
        if trial.get("generation_status") != "success":
            continue
        raw_text = trial.get("raw_generated_text")
        if not isinstance(raw_text, str):
            continue
        score = score_text(raw_text, context_chars=context_chars)
        if not score["contains_ascii_hyphen"]:
            continue
        records.append(
            {
                "run_id": trial.get("run_id"),
                "trial_id": trial.get("trial_id"),
                "prompt_id": trial.get("prompt_id"),
                "category": trial.get("category"),
                "prompt_variant": trial.get("prompt_variant"),
                "trial_index": trial.get("trial_index"),
                "timestamp_utc": trial.get("timestamp_utc"),
                "ascii_hyphen_count": score["ascii_hyphen_count"],
                "violation_positions": score["violation_positions"],
                "violation_contexts": score["violation_contexts"],
                "scoring_version": score["scoring_version"],
                "scored_text_source": score["scored_text_source"],
            }
        )
    return records


def compare_stored_score(
    trial: Mapping[str, Any],
    context_chars: int = DEFAULT_CONTEXT_CHARS,
) -> list[str]:
    """Compare stored scoring fields against a fresh score of the raw text.

    Returns human-readable mismatch messages. An empty list means the stored
    fields are consistent with the current scoring implementation.
    """

    if trial.get("generation_status") != "success":
        return []

    raw_text = trial.get("raw_generated_text")
    if not isinstance(raw_text, str):
        return ["successful trial is missing a string raw_generated_text"]

    fresh = score_text(raw_text, context_chars=context_chars)
    messages: list[str] = []

    expected_fields = (
        "contains_ascii_hyphen",
        "ascii_hyphen_count",
        "violation_positions",
        "is_compliant",
    )
    for field in expected_fields:
        if trial.get(field) != fresh[field]:
            messages.append(
                f"{field} differs: stored={trial.get(field)!r}, recomputed={fresh[field]!r}"
            )

    return messages
