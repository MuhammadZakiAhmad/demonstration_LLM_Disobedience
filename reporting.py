"""Human-readable console and Markdown presentation for experiment results.

The console renderer is intentionally dependency-free: ANSI color plus plain
text formatting. Model text is never altered here; wrapping applies to display
only, and ``outputs.md`` always contains the complete generated text.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any, Iterable

from run_utils import write_text_atomic

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
CYAN = "\x1b[36m"
BLUE = "\x1b[34m"


def resolve_color(mode: str = "auto") -> bool:
    """Resolve the reporting.color setting."""

    if mode == "always":
        return True
    if mode == "never":
        return False
    if mode not in ("auto", ""):
        raise ValueError("reporting.color must be 'auto', 'always', or 'never'")
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("COLAB_RELEASE_TAG") or "COLAB_GPU" in os.environ:
        return True
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _paint(text: str, code: str, enabled: bool, *, bold: bool = False) -> str:
    if not enabled:
        return text
    prefix = (BOLD if bold else "") + code
    return f"{prefix}{text}{RESET}"


def _terminal_width(width: int | None = None) -> int:
    if width is not None:
        return max(60, int(width))
    try:
        detected = shutil.get_terminal_size(fallback=(100, 24)).columns
    except Exception:
        detected = 100
    return max(60, min(120, detected))


def _status(trial: dict[str, Any]) -> tuple[str, str]:
    if trial.get("generation_status") != "success":
        return "ERROR", YELLOW
    if trial.get("ascii_hyphen_count", 0) > 0:
        return "VIOLATION", RED
    return "PASS", GREEN


def _status_label(trial: dict[str, Any]) -> str:
    status, _ = _status(trial)
    if trial.get("generation_status") == "success":
        if trial.get("finish_reason") == "length":
            status += "+TRUNCATED"
        heuristic = (trial.get("generation_metadata") or {}).get("repetition_heuristic") or {}
        if heuristic.get("suspected_loop"):
            status += "+LOOP?"
    return status


def _format_seconds(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "?"
    return f"{float(value):.2f}s"


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _preview(value: Any, limit: int) -> str:
    text = _one_line(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _wrap_prefixed(text: str, prefix: str, width: int) -> list[str]:
    if text == "":
        return [prefix]
    wrapper = textwrap.TextWrapper(
        width=max(20, width),
        initial_indent=prefix,
        subsequent_indent=prefix,
        replace_whitespace=False,
        drop_whitespace=True,
        break_long_words=False,
        break_on_hyphens=False,
    )
    lines: list[str] = []
    for original_line in text.splitlines() or [""]:
        if original_line == "":
            lines.append(prefix.rstrip())
        else:
            lines.extend(wrapper.wrap(original_line) or [prefix])
    return lines


def render_run_header(
    *,
    run_id: str,
    model_id: str,
    model_revision: str,
    prompt_count: int,
    repetitions: int,
    planned_trials: int,
    server_url: str | None = None,
    color: bool = True,
    width: int | None = None,
) -> str:
    line_width = min(_terminal_width(width), 100)
    rule = "=" * line_width
    lines = [
        _paint(rule, CYAN, color),
        _paint(f" RUN {run_id}", BOLD, color, bold=True),
        f" Model   : {model_id} @ {model_revision[:12]}",
        f" Set     : {prompt_count} prompts x {repetitions} repetition(s) = {planned_trials} trials",
    ]
    if server_url:
        lines.append(f" Server  : {server_url}")
    lines.append(_paint(rule, CYAN, color))
    return "\n".join(lines)


def render_trial_card(
    trial: dict[str, Any],
    index: int,
    total: int,
    *,
    color: bool = True,
    width: int | None = None,
    max_output_chars: int = 0,
) -> str:
    line_width = min(_terminal_width(width), 100)
    rule = "-" * line_width
    status, status_color = _status(trial)
    label = _status_label(trial)

    lines: list[str] = []
    lines.append("")
    lines.append(
        _paint(f"[{index}/{total}] {trial.get('trial_id')}", BOLD, color, bold=True)
        + f"  prompt={trial.get('prompt_id')}"
    )
    lines.append(f"  Category : {trial.get('category')}")
    lines.append(f"  Variant  : {trial.get('prompt_variant')}")
    task_preview = _preview(trial.get("user_prompt"), max(40, line_width - 12))
    lines.append(f"  Task     : {task_preview}")
    hyphen_count = trial.get("ascii_hyphen_count")
    finish_reason = trial.get("finish_reason") or "n/a"
    duration = _format_seconds(trial.get("generation_duration_seconds"))
    count_text = "n/a" if hyphen_count is None else str(hyphen_count)
    lines.append(
        f"  Result   : {_paint('[' + label + ']', status_color, color, bold=True)}"
        f"  {count_text} ASCII hyphen(s)  |  finish={finish_reason}  {duration}"
    )
    lines.append(rule)

    if trial.get("generation_status") == "success":
        raw_text = trial.get("raw_generated_text")
        if not isinstance(raw_text, str):
            raw_text = ""
        display_text = raw_text
        truncated_for_display = False
        if max_output_chars > 0 and len(display_text) > max_output_chars:
            display_text = display_text[:max_output_chars]
            truncated_for_display = True
        lines.extend(_wrap_prefixed(display_text, "  ", line_width - 2))
        if truncated_for_display:
            lines.append(
                _paint(
                    f"  ... display truncated at {max_output_chars} characters; "
                    "full text is in trials.jsonl and outputs.md",
                    DIM,
                    color,
                )
            )
    else:
        error = trial.get("error") or {}
        if isinstance(error, dict):
            message = f"{error.get('type', 'error')}: {error.get('message', '')}"
        else:
            message = str(error)
        lines.extend(_wrap_prefixed(message or "unknown generation error", "  ! ", line_width - 2))

    lines.append(rule)

    positions = trial.get("violation_positions") or []
    if positions and trial.get("generation_status") == "success":
        shown_positions = ", ".join(str(value) for value in positions[:20])
        if len(positions) > 20:
            shown_positions += f", ... (+{len(positions) - 20} more)"
        lines.append(f"  Positions (zero-based): {shown_positions}")
        contexts = trial.get("violation_contexts") or []
        for context in contexts[:5]:
            if not isinstance(context, dict):
                continue
            excerpt = _one_line(context.get("excerpt"))
            excerpt = _preview(excerpt, max(20, line_width - 24))
            lines.append(f"  @ {context.get('position')}: ...{excerpt}...")
        if len(contexts) > 5:
            lines.append(f"  ... {len(contexts) - 5} more context excerpt(s) in outputs.md")

    warnings = list(trial.get("warnings") or [])
    for warning in warnings:
        wrapped = _wrap_prefixed(str(warning), "  ! ", line_width - 2)
        lines.extend(_paint(line, YELLOW, color) for line in wrapped)

    return "\n".join(lines)


def _rate_text(rate: dict[str, Any] | None) -> str:
    if not isinstance(rate, dict):
        return "n/a"
    numerator = rate.get("numerator")
    denominator = rate.get("denominator")
    percent = rate.get("percent")
    if percent is None:
        return f"{numerator}/{denominator} (n/a)"
    return f"{numerator}/{denominator} ({percent:.1f}%)"


def _ci_text(summary: dict[str, Any]) -> str:
    ci = (summary.get("overall") or {}).get("violation_rate_ci95")
    if not isinstance(ci, dict) or ci.get("lower") is None or ci.get("upper") is None:
        return "95% Wilson CI unavailable (no successful generations)"
    return (
        f"95% Wilson CI (violation): "
        f"[{ci['lower'] * 100:.1f}%, {ci['upper'] * 100:.1f}%]  "
        f"(n={ci.get('denominator')})"
    )


def _trial_result_label(trial: dict[str, Any]) -> str:
    if trial.get("generation_status") != "success":
        return "ERROR"
    if trial.get("ascii_hyphen_count", 0) > 0:
        return "VIOLATION"
    return "PASS"


def render_summary(
    summary: dict[str, Any],
    *,
    trials: Iterable[dict[str, Any]] | None = None,
    color: bool = True,
    width: int | None = None,
) -> str:
    line_width = min(_terminal_width(width), 100)
    overall = summary.get("overall") or {}
    lines: list[str] = ["", _paint("SUMMARY", BOLD, color, bold=True)]
    lines.append("=" * min(line_width, 72))

    attempted = overall.get("attempted", 0)
    successful = overall.get("successful", 0)

    def status_paint(text: str, code: str) -> str:
        return _paint(text, code, color, bold=True)

    lines.append(f"  Successful : {successful}/{attempted}")
    lines.append(
        f"  Compliant  : {status_paint(_rate_text(overall.get('compliance_rate')), GREEN)}"
    )
    lines.append(
        f"  Violating  : {status_paint(_rate_text(overall.get('violation_rate')), RED)}"
    )
    lines.append(f"  Failed     : {_rate_text(overall.get('failure_rate'))}")
    lines.append(f"  {_ci_text(summary)}")
    if summary.get("clustered_by_prompt"):
        lines.append(
            "  Note       : repeated trials are clustered by prompt; treating every "
            "generation as independent may understate uncertainty."
        )
    status = summary.get("run_status")
    if status and status != "completed":
        lines.append(_paint(f"  Run status : {status.upper()}", YELLOW, color, bold=True))

    trial_source: Iterable[dict[str, Any]] = (
        trials if trials is not None else (summary.get("trials") or [])
    )
    trial_list = list(trial_source)
    if trial_list:
        lines.append("")
        lines.append("  Per-prompt results")
        compact = line_width < 88
        if compact:
            lines.append("  #   Prompt        Result       Hyphens")
            for index, trial in enumerate(trial_list, start=1):
                lines.append(
                    f"  {index:>2}  {str(trial.get('prompt_id'))[:12]:<12}  "
                    f"{_trial_result_label(trial):<10}  "
                    f"{trial.get('ascii_hyphen_count') if trial.get('ascii_hyphen_count') is not None else '-':>7}"
                )
        else:
            headers = ["#", "Prompt", "Category", "Variant", "Result", "Hyphens"]
            rows: list[list[str]] = []
            for index, trial in enumerate(trial_list, start=1):
                rows.append(
                    [
                        str(index),
                        str(trial.get("prompt_id")),
                        str(trial.get("category")),
                        str(trial.get("prompt_variant")),
                        _trial_result_label(trial),
                        str(
                            trial.get("ascii_hyphen_count")
                            if trial.get("ascii_hyphen_count") is not None
                            else "-"
                        ),
                    ]
                )
            widths = [2, 12, 22, 18, 10, 7]
            for row_index, header in enumerate(headers):
                widths[row_index] = max(widths[row_index], len(header))
                for row in rows:
                    widths[row_index] = min(
                        max(widths[row_index], len(row[row_index])),
                        30,
                    )
            header_line = "  " + "  ".join(
                header.ljust(widths[column]) for column, header in enumerate(headers)
            )
            lines.append(header_line.rstrip())
            lines.append("  " + "  ".join("-" * width for width in widths))
            for row in rows:
                cells = [
                    row[column][: widths[column]].ljust(widths[column])
                    for column in range(len(headers))
                ]
                result_cell = row[4]
                joined = "  ".join(cells).rstrip()
                if color:
                    code = GREEN if result_cell == "PASS" else RED if result_cell == "VIOLATION" else YELLOW
                    joined = joined.replace(
                        result_cell.ljust(widths[4]),
                        _paint(result_cell.ljust(widths[4]), code, True),
                        1,
                    )
                lines.append("  " + joined)

    by_category = summary.get("by_category") or {}
    if by_category:
        lines.append("")
        lines.append("  By category (violating / successful)")
        for category, metrics in by_category.items():
            lines.append(f"    {category:<32} {_rate_text(metrics.get('violation_rate'))}")

    by_variant = summary.get("by_prompt_variant") or {}
    if by_variant:
        lines.append("")
        lines.append("  By prompt formulation (violating / successful)")
        for variant, metrics in by_variant.items():
            lines.append(f"    {variant:<32} {_rate_text(metrics.get('violation_rate'))}")

    lines.append("=" * min(line_width, 72))
    return "\n".join(lines)


def _fence(text: str, language: str = "text") -> str:
    longest = 0
    current = 0
    for character in text:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _blockquote(text: str) -> str:
    if text == "":
        return "> (empty)"
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def write_outputs_md(
    run_dir: str | Path,
    trials: Iterable[dict[str, Any]],
    summary: dict[str, Any],
) -> Path:
    """Write the complete numbered prompt/output artifact for a run."""

    trial_list = list(trials)
    run_dir = Path(run_dir)
    lines: list[str] = []
    lines.append(f"# Prompt Outputs — {summary.get('run_id', 'unknown run')}")
    lines.append("")
    lines.append(f"- Run status: `{summary.get('run_status', 'unknown')}`")
    lines.append(f"- Model: `{summary.get('model_id')} @ {summary.get('model_revision')}`")
    lines.append(f"- Successful / attempted: {summary.get('overall', {}).get('successful')} / {summary.get('overall', {}).get('attempted')}")
    lines.append("")
    lines.append(
        "Generated outputs below are reproduced exactly from `trials.jsonl`. "
        "Scoring applies to the complete raw generated text."
    )
    lines.append("")

    for index, trial in enumerate(trial_list, start=1):
        status = _trial_result_label(trial)
        lines.append(f"## {index}. {trial.get('prompt_id')} — {status}")
        lines.append("")
        lines.append(f"- Trial: `{trial.get('trial_id')}`")
        lines.append(f"- Category: `{trial.get('category')}`")
        lines.append(f"- Prompt variant: `{trial.get('prompt_variant')}`")
        lines.append(f"- Generation status: `{trial.get('generation_status')}`")
        lines.append(f"- Finish reason: `{trial.get('finish_reason')}`")
        lines.append(f"- ASCII hyphens: `{trial.get('ascii_hyphen_count')}`")
        lines.append(f"- Duration: {_format_seconds(trial.get('generation_duration_seconds'))}")
        lines.append("")
        lines.append("### Prompt")
        lines.append("")
        lines.append("**System instruction:**")
        lines.append("")
        lines.append(_blockquote(str(trial.get("system_instruction") or "")))
        lines.append("")
        lines.append("**User prompt:**")
        lines.append("")
        lines.append(_blockquote(str(trial.get("user_prompt") or "")))
        lines.append("")
        lines.append("### Generated output")
        lines.append("")
        if trial.get("generation_status") == "success":
            lines.append(_fence(str(trial.get("raw_generated_text") or "")))
        else:
            error = trial.get("error") or {}
            if isinstance(error, dict):
                message = f"{error.get('type', 'error')}: {error.get('message', '')}"
            else:
                message = str(error)
            lines.append(_fence(f"GENERATION FAILED\n{message}"))
        lines.append("")

        positions = trial.get("violation_positions") or []
        if positions:
            lines.append("### Violation positions")
            lines.append("")
            lines.append(
                "Zero-based character positions: "
                + ", ".join(str(value) for value in positions)
            )
            contexts = trial.get("violation_contexts") or []
            if contexts:
                lines.append("")
                lines.append("Contexts:")
                lines.append("")
                for context in contexts:
                    if isinstance(context, dict):
                        lines.append(
                            f"- position {context.get('position')}: "
                            f"`{_one_line(context.get('excerpt'))}`"
                        )
            lines.append("")

        warnings = trial.get("warnings") or []
        if warnings:
            lines.append("### Warnings")
            lines.append("")
            for warning in warnings:
                lines.append(f"- {warning}")
            lines.append("")
        lines.append("---")
        lines.append("")

    path = run_dir / "outputs.md"
    write_text_atomic(path, "\n".join(lines))
    return path
