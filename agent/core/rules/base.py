"""
Shared rule-matching engine for the rules-first classification layer.

A Rule is a regex signature mapped to a failure category. Some rules carry a
`fix_builder` — a function that, given the matched lines, can derive a fully
deterministic fix payload (e.g. "replace this checksum with that one") with no
LLM call at all. Rules without a `fix_builder` still narrow the frame handed
to the Diagnostician (matched_category + candidate_files) instead of the LLM
reasoning from a blank slate.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional
import re


@dataclass
class RuleMatch:
    category: str
    deterministic: bool
    rule_fix: Optional[dict]
    candidate_files: list
    matched_line: str
    matched_line_number: int


@dataclass
class Rule:
    pattern: str
    category: str
    # True only if fix_builder can reliably produce a correct, mechanical fix
    # from the log text alone (no guessing).
    deterministic: bool = False
    # Named capture group in `pattern` that holds a file path, if any.
    file_group: Optional[str] = None
    # Optional: derive candidate files by scanning nearby log lines
    # (e.g. walking back to find the recipe path a bitbake task belongs to).
    file_from_context: Optional[Callable[[list, int], list]] = None
    # Optional: build a deterministic fix payload from the matched context.
    # Signature: (lines, matched_index) -> dict | None. Returning None means
    # "matched the category but couldn't build a safe deterministic fix" —
    # falls back to the LLM path with the category hint still applied.
    fix_builder: Optional[Callable[[list, int], Optional[dict]]] = None

    _compiled: "re.Pattern" = field(default=None, repr=False, compare=False)

    def compiled(self) -> "re.Pattern":
        if self._compiled is None:
            self._compiled = re.compile(self.pattern)
        return self._compiled


def match_rules(lines: list, rules: list) -> Optional[RuleMatch]:
    """
    Scan `lines` against `rules` in priority order (first match wins).
    Returns None if nothing matches — caller must route to the LLM path with
    structural_confidence=low, never drop the log silently.
    """
    for rule in rules:
        regex = rule.compiled()
        for i, line in enumerate(lines):
            m = regex.search(line)
            if not m:
                continue

            candidate_files = []
            groups = m.groupdict()
            if rule.file_group and groups.get(rule.file_group):
                candidate_files.append(groups[rule.file_group])
            if rule.file_from_context:
                candidate_files.extend(rule.file_from_context(lines, i))

            rule_fix = None
            deterministic = False
            if rule.fix_builder:
                rule_fix = rule.fix_builder(lines, i)
                deterministic = rule.deterministic and rule_fix is not None

            return RuleMatch(
                category=rule.category,
                deterministic=deterministic,
                rule_fix=rule_fix,
                candidate_files=[f for f in dict.fromkeys(candidate_files) if f],
                matched_line=line.strip(),
                matched_line_number=i + 1,
            )
    return None
