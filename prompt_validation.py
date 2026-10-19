"""Strict validation and deterministic loading of the JSONL prompt set."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

PROMPT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.]*$")

REQUIRED_FIELDS = (
    "prompt_id",
    "category",
    "prompt_variant",
    "system_instruction",
    "user_prompt",
    "expected_output_type",
    "enabled",
)

STRING_FIELDS = (
    "prompt_id",
    "category",
    "prompt_variant",
    "system_instruction",
    "user_prompt",
    "expected_output_type",
)


class PromptValidationError(ValueError):
    """Raised with a complete, line-oriented list of prompt-file problems."""

    def __init__(self, path: str | Path, errors: list[str]):
        self.path = str(path)
        self.errors = errors
        joined = "\n".join(f"  - {message}" for message in errors)
        super().__init__(f"Invalid prompt file {self.path}:\n{joined}")


def _validate_record(
    record: Any,
    line_number: int,
    seen_ids: set[str],
    known_categories: set[str],
    warnings: list[str],
) -> list[str]:
    errors: list[str] = []

    if not isinstance(record, dict):
        return [f"line {line_number}: expected a JSON object, got {type(record).__name__}"]

    for field in REQUIRED_FIELDS:
        if field not in record:
            errors.append(f"line {line_number}: missing required field {field!r}")

    for field in STRING_FIELDS:
        if field not in record:
            continue
        value = record[field]
        if not isinstance(value, str):
            errors.append(
                f"line {line_number}: field {field!r} must be a string, "
                f"got {type(value).__name__}"
            )
        elif not value.strip():
            errors.append(f"line {line_number}: field {field!r} must not be empty")

    if "enabled" in record and not isinstance(record["enabled"], bool):
        errors.append(
            f"line {line_number}: field 'enabled' must be true or false, "
            f"got {type(record['enabled']).__name__}"
        )

    if record.get("expected_output_type") not in (None, "email"):
        errors.append(
            f"line {line_number}: expected_output_type must be 'email', "
            f"got {record.get('expected_output_type')!r}"
        )

    prompt_id = record.get("prompt_id")
    if isinstance(prompt_id, str):
        if not PROMPT_ID_RE.match(prompt_id):
            errors.append(
                f"line {line_number}: prompt_id {prompt_id!r} must match "
                f"{PROMPT_ID_RE.pattern!r}"
            )
        if prompt_id in seen_ids:
            errors.append(f"line {line_number}: duplicate prompt_id {prompt_id!r}")
        seen_ids.add(prompt_id)

    category = record.get("category")
    if isinstance(category, str):
        known_categories.add(category)

    system_instruction = record.get("system_instruction")
    user_prompt = record.get("user_prompt")
    if isinstance(system_instruction, str) and isinstance(user_prompt, str):
        combined = (system_instruction + "\n" + user_prompt).lower()
        if "hyphen" not in combined and "-" not in (system_instruction + user_prompt):
            warnings.append(
                f"line {line_number}: neither the system instruction nor the user "
                "prompt appears to mention the hyphen constraint; verify that the "
                "prompt belongs to the primary prohibition condition"
            )

    return errors


def load_prompts(
    path: str | Path,
    include_disabled: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load and validate prompts in file order.

    Blank lines are rejected because ``prompts.jsonl`` must contain exactly one
    JSON object per line. Disabled prompts are validated but excluded from the
    returned runnable list unless ``include_disabled`` is true.
    """

    prompt_path = Path(path)
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    if not prompt_path.is_file():
        raise PromptValidationError(prompt_path, ["path is not a regular file"])

    try:
        text = prompt_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PromptValidationError(prompt_path, [f"file is not valid UTF-8: {exc}"]) from exc

    lines = text.splitlines()
    errors: list[str] = []
    warnings: list[str] = []
    prompts: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    known_categories: set[str] = set()

    if not lines:
        raise PromptValidationError(prompt_path, ["file is empty"])

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(
                f"line {line_number}: blank line. Every line must contain exactly one JSON object."
            )
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                f"line {line_number}: invalid JSON at column {exc.colno}: {exc.msg}"
            )
            continue

        line_errors = _validate_record(
            record,
            line_number,
            seen_ids,
            known_categories,
            warnings,
        )
        errors.extend(line_errors)
        if line_errors:
            continue

        if record.get("enabled") or include_disabled:
            prompts.append(record)

    if errors:
        raise PromptValidationError(prompt_path, errors)

    if not prompts:
        raise PromptValidationError(
            prompt_path,
            ["no runnable prompts remain after filtering disabled entries"],
        )

    return prompts, warnings


def select_prompts(
    prompts: Iterable[dict[str, Any]],
    include_prompt_ids: Iterable[str] | None = None,
    include_categories: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply optional filters while preserving the prompt file's deterministic order."""

    prompt_list = list(prompts)
    ids = [value for value in (include_prompt_ids or []) if value]
    categories = [value for value in (include_categories or []) if value]

    known_ids = {prompt["prompt_id"] for prompt in prompt_list}
    unknown_ids = sorted(set(ids) - known_ids)
    if unknown_ids:
        raise PromptValidationError(
            "<selection>",
            [f"include_prompt_ids contains unknown prompt ids: {unknown_ids}"],
        )

    id_set = set(ids)
    category_set = set(categories)
    selected = [
        prompt
        for prompt in prompt_list
        if (not id_set or prompt["prompt_id"] in id_set)
        and (not category_set or prompt["category"] in category_set)
    ]

    if not selected:
        raise PromptValidationError(
            "<selection>",
            ["prompt filters selected zero enabled prompts"],
        )

    return selected


def summarize_prompt_set(prompts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return deterministic prompt-set counts for manifests and reports."""

    prompt_list = list(prompts)
    by_category: dict[str, int] = {}
    by_variant: dict[str, int] = {}
    for prompt in prompt_list:
        category = prompt["category"]
        variant = prompt["prompt_variant"]
        by_category[category] = by_category.get(category, 0) + 1
        by_variant[variant] = by_variant.get(variant, 0) + 1

    return {
        "prompt_count": len(prompt_list),
        "prompt_ids": [prompt["prompt_id"] for prompt in prompt_list],
        "by_category": dict(sorted(by_category.items())),
        "by_prompt_variant": dict(sorted(by_variant.items())),
    }
