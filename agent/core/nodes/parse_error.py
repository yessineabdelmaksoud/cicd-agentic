"""
Node — parse_error (fix.md FIX-5 + FIX-4, v5 §7.3)

Two responsibilities:
  (a) Locate the REAL error — task-anchored + dynamic window, not a fixed
      5/10-line slice. For Yocto, prefers the per-task log.do_* file (the
      top-level ERROR: summary is often dozens of lines below the real
      failure) uploaded alongside build.log by the CI notify step.
  (b) Rules-first classification — match the log against a build-type regex
      table before any LLM is involved (core/rules/). A deterministic match
      can carry a ready-to-apply fix; a category-only match still narrows the
      frame handed to the Diagnostician; no match sets structural_confidence
      = low, which makes the objective gate stricter downstream.

No-match is explicit: an empty error_context routes the graph straight to
post_comment (see route_after_parse in core/graph.py) instead of silently
continuing with a hollow diagnosis.
"""

import re
import structlog
from core.state import AgentState
from core.rules import RULES_BY_BUILD_TYPE, match_rules
from services.metrics import node_duration

log = structlog.get_logger()

MAX_WINDOW_LINES = 60
FILE_EXTRACT_RE = re.compile(r"\b([\w./-]+\.(?:c|cpp|cc|cxx|h|hpp|bb|bbappend|cmake|mk|conf))\b")
YOCTO_TASK_RE = re.compile(r"ERROR:\s*(?P<recipe>\S+)\s+(?P<task>do_\w+):")
GENERIC_ERROR_RE = re.compile(r"(?i)\berror\b|undefined reference to|ninja: error")


def _extract_files(text: str) -> list:
    return list(dict.fromkeys(FILE_EXTRACT_RE.findall(text)))


def _locate_yocto_task(lines: list) -> dict:
    for line in lines:
        m = YOCTO_TASK_RE.search(line)
        if m:
            return {"failing_recipe": m.group("recipe"), "failing_task": m.group("task")}
    return {}


def _capture_block(lines: list, start_idx: int, before: int = 5, max_lines: int = MAX_WINDOW_LINES) -> tuple:
    """Dynamic window: expand forward until two consecutive blank lines or the
    next ninja progress marker ('[n/m]') — not a fixed line count."""
    end = start_idx
    blank_run = 0
    for i in range(start_idx, min(len(lines), start_idx + max_lines)):
        end = i
        if not lines[i].strip():
            blank_run += 1
            if blank_run >= 2:
                break
        else:
            blank_run = 0
        if i > start_idx and re.match(r"^\[\d+/\d+\]", lines[i]):
            end = i - 1
            break
    lines_before = lines[max(0, start_idx - before):start_idx]
    lines_after = lines[start_idx + 1:end + 1]
    return lines_before, lines_after


def _build_error_span_yocto(raw_log: str, task_log: str) -> dict:
    """Prefer the per-task log for the real error; fall back to the summary log
    if no task log was uploaded (older pipelines / CI didn't attach one)."""
    summary_lines = raw_log.splitlines()
    task_info = _locate_yocto_task(summary_lines)

    source_lines = task_log.splitlines() if task_log else summary_lines
    used_task_log = bool(task_log)

    error_idx = None
    for i, line in enumerate(source_lines):
        if GENERIC_ERROR_RE.search(line):
            error_idx = i
            break

    if error_idx is None:
        return {}

    before, after = _capture_block(source_lines, error_idx)
    return {
        "error_line": source_lines[error_idx].strip(),
        "error_line_number": error_idx + 1,
        "lines_before": before,
        "lines_after": after,
        "used_task_log": used_task_log,
        **task_info,
    }


def _build_error_span_generic(raw_log: str) -> dict:
    """Zephyr/QNX: anchor on the first error:/undefined-reference/ninja:error
    line, capture the whole failing invocation (dynamic), not a fixed count."""
    lines = raw_log.splitlines()
    error_idx = None
    for i, line in enumerate(lines):
        if GENERIC_ERROR_RE.search(line):
            error_idx = i
            break

    if error_idx is None:
        return {}

    before, after = _capture_block(lines, error_idx)
    return {
        "error_line": lines[error_idx].strip(),
        "error_line_number": error_idx + 1,
        "lines_before": before,
        "lines_after": after,
        "used_task_log": False,
    }


async def parse_error(state: AgentState) -> AgentState:
    """LangGraph node: locate the real error + run rules-first classification."""
    with node_duration.labels(node="parse_error").time():
        build_type = state["build_type"]
        raw_log = state.get("raw_log", "")
        task_log = state.get("task_log", "")

        if not raw_log or raw_log.startswith("ERROR: Could not fetch log"):
            log.warning("parse_error.no_log", build_type=build_type)
            return {**state, "error_context": {}, "error_message": "No build log available to parse"}

        if build_type == "yocto":
            span = _build_error_span_yocto(raw_log, task_log)
            classify_source = (task_log or raw_log).splitlines()
        else:
            span = _build_error_span_generic(raw_log)
            classify_source = raw_log.splitlines()

        if not span:
            log.warning("parse_error.no_match", build_type=build_type)
            return {**state, "error_context": {}, "error_message": "Could not locate an error in the build log"}

        rules = RULES_BY_BUILD_TYPE.get(build_type, [])
        rule_match = match_rules(classify_source, rules)

        span_text = "\n".join(span.get("lines_before", []) + [span.get("error_line", "")] + span.get("lines_after", []))
        extracted_files = _extract_files(span_text)
        if rule_match:
            for f in rule_match.candidate_files:
                if f not in extracted_files:
                    extracted_files.append(f)

        error_context = {
            "build_type": build_type,
            **span,
            "matched_category": rule_match.category if rule_match else "unknown",
            "rule_fix": rule_match.rule_fix if rule_match else None,
            "deterministic": bool(rule_match and rule_match.deterministic),
            "extracted_files": extracted_files,
            "structural_confidence": "high" if rule_match else "low",
        }

        log.info(
            "parse_error.result",
            category=error_context["matched_category"],
            deterministic=error_context["deterministic"],
            files=extracted_files,
            build_type=build_type,
            used_task_log=span.get("used_task_log", False),
        )

        return {**state, "error_context": error_context}
