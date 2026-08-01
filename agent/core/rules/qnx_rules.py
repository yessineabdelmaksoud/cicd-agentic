"""
QNX-substitute (cross-compiled Makefile C project) rule signatures.
Mirrors gcc/make/ld failure shapes so the same rules apply once real QNX SDP
is swapped in later.
"""

from core.rules.base import Rule

RULES = [
    Rule(
        pattern=r"(?P<file>\S+\.c(?:pp)?):\d+:\s*(fatal )?error:",
        category="compile",
        file_group="file",
    ),
    Rule(
        pattern=r"fatal error: (?P<file>\S+\.h): No such file or directory",
        category="missing_include",
        file_group="file",
    ),
    Rule(
        pattern=r"undefined reference to",
        category="linker",
    ),
    Rule(
        pattern=r"ld:.*(error|cannot find)",
        category="linker",
    ),
    Rule(
        pattern=r"make(\[\d+\])?:.*(Error \d+|\*\*\*.*Stop)",
        category="make",
    ),
    Rule(
        pattern=r"No rule to make target",
        category="make",
    ),
]
