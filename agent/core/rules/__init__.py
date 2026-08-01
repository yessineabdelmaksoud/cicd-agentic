"""
Rules-first classification layer.
Deterministic signature tables per build type — matched before any LLM call.
See core/rules/base.py for the shared matching engine.
"""

from core.rules.base import Rule, RuleMatch, match_rules
from core.rules import yocto_rules, zephyr_rules, qnx_rules

RULES_BY_BUILD_TYPE = {
    "yocto": yocto_rules.RULES,
    "zephyr": zephyr_rules.RULES,
    "qnx": qnx_rules.RULES,
}

__all__ = ["Rule", "RuleMatch", "match_rules", "RULES_BY_BUILD_TYPE"]
