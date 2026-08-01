"""
Yocto/BitBake rule signatures — fix.md §FIX-4/7.3 table.
"""

import re
from core.rules.base import Rule

_RECIPE_RE = re.compile(r"(\S+\.bb(?:append)?)\b")
_HEX_RE = re.compile(r"\b([0-9a-f]{32}|[0-9a-f]{64})\b")


def _find_recipe_file(lines: list, idx: int) -> list:
    """Walk back from the failure line to find the recipe (.bb/.bbappend) it belongs to."""
    for j in range(idx, max(-1, idx - 300), -1):
        m = _RECIPE_RE.search(lines[j])
        if m:
            return [m.group(1)]
    return []


def _build_checksum_fix(lines: list, idx: int):
    """
    BitBake checksum-mismatch messages vary by version but always print both
    the value currently in the recipe and the value that was actually
    downloaded, near each other and near hex-digest-looking tokens. Scan a
    window around the match for two hex strings of the same length and infer
    which is "wrong" (in the recipe, to be replaced) vs "correct" (actual,
    the replacement) from nearby keywords. If that's ambiguous, bail out —
    the category hint still reaches the Diagnostician, just without a
    zero-LLM-call short circuit.
    """
    window = lines[max(0, idx - 3): idx + 8]
    text = "\n".join(window)
    hexes = _HEX_RE.findall(text)
    if len(hexes) < 2:
        return None

    lower = text.lower()
    wrong_kw = ("wrong", "actual", "got", "downloaded", "computed")
    correct_kw = ("correct", "expected", "should", "recipe", "wanted")

    def _nearest_keyword(hexval: str, keywords: tuple) -> bool:
        pos = lower.find(hexval.lower())
        if pos == -1:
            return False
        window_text = lower[max(0, pos - 60): pos]
        return any(kw in window_text for kw in keywords)

    old_sum, new_sum = None, None
    for h in dict.fromkeys(hexes):
        if _nearest_keyword(h, wrong_kw) and old_sum is None:
            new_sum = h  # the "wrong"/actual value is what the recipe must be UPDATED TO
        elif _nearest_keyword(h, correct_kw) and old_sum is None:
            old_sum = h  # the "correct"/expected value is what's currently IN the recipe

    if not old_sum or not new_sum or old_sum == new_sum:
        return None

    sum_type = "sha256sum" if len(new_sum) == 64 else "md5sum"
    return {
        "type": "checksum_substitution",
        "old_sum": old_sum,
        "new_sum": new_sum,
        "sum_type": sum_type,
    }


RULES = [
    # Checksum mismatches are technically raised inside do_fetch and often echo
    # "Fetcher failure" too — must be checked BEFORE the generic fetch rule below,
    # or every checksum mismatch would get miscategorized as a plain fetch error.
    Rule(
        pattern=r"(?i)(md5|sha256)sum.*(mismatch|does not match|not correct)",
        category="checksum",
        deterministic=True,
        file_from_context=_find_recipe_file,
        fix_builder=_build_checksum_fix,
    ),
    Rule(
        pattern=r"(?i)Fetcher failure.*|Failed to fetch URL|ERROR:.*do_fetch",
        category="fetch",
        file_from_context=_find_recipe_file,
    ),
    Rule(
        pattern=r"Nothing (R?)PROVIDES|ERROR:.*Required build target.*has no buildable providers|DEPENDS.*(not found|not available)",
        category="dependency",
        file_from_context=_find_recipe_file,
    ),
    Rule(
        pattern=r"undefined reference to",
        category="linker",
    ),
    Rule(
        pattern=r"(?P<file>\S+\.c(?:pp|c|xx)?):\d+:\d*:?\s*(fatal )?error:",
        category="compile",
        file_group="file",
    ),
    Rule(
        pattern=r"fatal error: (?P<file>\S+\.h): No such file or directory",
        category="missing_include",
        file_group="file",
    ),
    Rule(
        pattern=r"ERROR:.*do_configure.*|configure: error:",
        category="configure",
    ),
    Rule(
        pattern=r"ERROR:.*do_\w+:.*",
        category="task",
    ),
]
