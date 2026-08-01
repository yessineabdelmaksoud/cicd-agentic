"""
Zephyr/west/CMake/ninja rule signatures — fix.md §FIX-4/7.3 table.
None of these are safely auto-fixable without reasoning about the source, so
none carry a fix_builder — they narrow the frame for the Diagnostician instead.
"""

from core.rules.base import Rule

RULES = [
    Rule(
        pattern=r"(?P<file>\S+\.c(?:pp)?):\d+:\d*:?\s*(fatal )?error:",
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
        pattern=r"CMake Error.*|ninja: error:.*",
        category="cmake",
    ),
    Rule(
        pattern=r"(?i)Kconfig.*error|warning: unmet direct dependencies",
        category="config",
    ),
]
