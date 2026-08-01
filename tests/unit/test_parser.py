"""
Unit tests for the parse_error node + rules-first classification layer.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agent"))

from core.nodes.parse_error import parse_error
from core.rules.yocto_rules import _build_checksum_fix


def _state(raw_log: str, build_type: str = "yocto", task_log: str = "") -> dict:
    return {
        "build_type": build_type,
        "raw_log": raw_log,
        "task_log": task_log,
    }


def run(state: dict) -> dict:
    return asyncio.run(parse_error(state))


# ---------------------------------------------------------------------------
# Yocto
# ---------------------------------------------------------------------------
class TestYoctoParser:
    def test_fetch_error(self):
        log = (
            "Build Configuration:\n"
            "  BB_VERSION = '2.0.0'\n"
            "ERROR: libfoo-2.1-r0 do_fetch: Fetcher failure for URL: "
            "'https://example.com/libfoo.tar.gz'. Exception: SSL error\n"
            "ERROR: libfoo-2.1-r0 do_fetch: Bitbake Fetcher Error\n"
        )
        result = run(_state(log))
        ctx = result["error_context"]
        assert ctx != {}
        assert ctx["matched_category"] == "fetch"

    def test_checksum_mismatch_is_deterministic(self):
        log = (
            "ERROR: libfoo-2.1-r0 do_fetch: Fetcher failure: sha256sum mismatch!\n"
            "The wrong sha256sum was computed: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
            "The correct expected sha256sum should be: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
            "recipes-demo/libfoo/libfoo_2.1.bb\n"
        )
        result = run(_state(log))
        ctx = result["error_context"]
        assert ctx["matched_category"] == "checksum"
        assert ctx["deterministic"] is True
        assert ctx["rule_fix"]["type"] == "checksum_substitution"
        assert ctx["rule_fix"]["old_sum"] == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        assert ctx["rule_fix"]["new_sum"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    def test_prefers_task_log_over_summary(self):
        summary = "ERROR: opencv-4.5.1-r0 do_compile: oe_runmake failed\n" * 3
        task_log = (
            "gcc -c src/main.c -o main.o\n"
            "src/main.c:42:5: error: use of undeclared identifier 'foo'\n"
            "make: *** [main.o] Error 1\n"
        )
        result = run(_state(summary, task_log=task_log))
        ctx = result["error_context"]
        assert "undeclared identifier" in ctx["error_line"]
        assert ctx["used_task_log"] is True
        assert ctx["failing_recipe"] == "opencv-4.5.1-r0"
        assert ctx["failing_task"] == "do_compile"

    def test_no_error_routes_to_no_match(self):
        result = run(_state("Build completed successfully.\nAll tasks passed.\n"))
        assert result["error_context"] == {}
        assert result.get("error_message")

    def test_empty_log_routes_to_no_match(self):
        result = run(_state(""))
        assert result["error_context"] == {}


# ---------------------------------------------------------------------------
# Zephyr
# ---------------------------------------------------------------------------
class TestZephyrParser:
    def test_undefined_reference(self):
        log = "undefined reference to 'k_thread_create'\nninja: build stopped: subcommand failed.\n"
        result = run(_state(log, build_type="zephyr"))
        ctx = result["error_context"]
        assert ctx["matched_category"] == "linker"

    def test_compile_error_extracts_file(self):
        log = "app/src/main.c:10:5: error: expected expression\n"
        result = run(_state(log, build_type="zephyr"))
        ctx = result["error_context"]
        assert ctx["matched_category"] == "compile"
        assert "app/src/main.c" in ctx["extracted_files"]


# ---------------------------------------------------------------------------
# QNX
# ---------------------------------------------------------------------------
class TestQNXParser:
    def test_make_error(self):
        log = "make[2]: *** [Makefile:45: driver.o] Error 1\n"
        result = run(_state(log, build_type="qnx"))
        assert result["error_context"]["matched_category"] == "make"


# ---------------------------------------------------------------------------
# Rules engine
# ---------------------------------------------------------------------------
class TestRulesEngine:
    def test_no_rule_match_sets_low_structural_confidence(self):
        log = "some totally unrecognized failure that matches nothing structured\n"
        # generic_error still anchors a span, but no rule table entry matches
        result = run(_state("error: something weird happened\n"))
        ctx = result["error_context"]
        assert ctx["matched_category"] == "unknown"
        assert ctx["structural_confidence"] == "low"

    def test_checksum_fix_builder_handles_ambiguous_input(self):
        # Only one hex value present — must not fabricate a fix
        assert _build_checksum_fix(["sha256sum mismatch: abc123"], 0) is None
