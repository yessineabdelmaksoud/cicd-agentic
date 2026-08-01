"""
Unit tests for evaluate_gate — the objective, non-LLM-confidence gate
(fix.md FIX-6). The key property under test: a hallucinated path or a
no-op / out-of-scope patch is rejected BEFORE any sandbox build, regardless
of how confident the reviewer claims to be.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agent"))

from core.nodes.evaluate_gate import evaluate_gate


def run(state: dict) -> dict:
    return asyncio.run(evaluate_gate(state))


def _base_state(**overrides) -> dict:
    state = {
        "patch_proposal": {
            "files_to_modify": [
                {"path": "recipes-demo/libfoo/libfoo_2.1.bb", "operation": "modify", "new_content": "SRC_URI = \"new\"\n"}
            ],
        },
        "review_verdict": {"approved": True, "confidence": 0.9},
        "error_context": {"matched_category": "fetch", "extracted_files": ["recipes-demo/libfoo/libfoo_2.1.bb"]},
        "diagnosis": {"candidate_files": []},
        "repo_context": {"recipes-demo/libfoo/libfoo_2.1.bb": "SRC_URI = \"old\"\n"},
        "existing_files": ["recipes-demo/libfoo/libfoo_2.1.bb"],
        "missing_files": [],
    }
    state.update(overrides)
    return state


def test_passing_patch_gates_through():
    result = run(_base_state())
    gate = result["gate_decision"]
    assert gate["passed"] is True
    assert gate["mr_type"] in ("draft", "normal")
    assert gate["failed_checks"] == []


def test_hallucinated_path_is_hard_rejected():
    """A path that was never fetched (doesn't exist in repo_context/existing_files)
    must be rejected before a sandbox build is ever spent — this is exactly the
    case the old confidence-only gate could not catch."""
    state = _base_state(
        patch_proposal={
            "files_to_modify": [
                {"path": "made/up/path.bb", "operation": "modify", "new_content": "whatever\n"}
            ],
        },
    )
    result = run(state)
    gate = result["gate_decision"]
    assert gate["passed"] is False
    assert "paths_exist" in gate["failed_checks"] or "diff_confined" in gate["failed_checks"]


def test_noop_patch_is_hard_rejected():
    """new_content identical to the real fetched content means the model didn't
    actually change anything — that's a failure mode, not a fix."""
    state = _base_state(
        patch_proposal={
            "files_to_modify": [
                {"path": "recipes-demo/libfoo/libfoo_2.1.bb", "operation": "modify", "new_content": "SRC_URI = \"old\"\n"}
            ],
        },
    )
    result = run(state)
    assert result["gate_decision"]["passed"] is False
    assert "content_changed" in result["gate_decision"]["failed_checks"]


def test_reviewer_rejection_is_hard_blocking_regardless_of_confidence():
    """Even a high self-reported confidence from the reviewer can't override
    approved=False — reviewer_approved is a hard check, confidence is never
    the sole authorization (fix.md FIX-6)."""
    state = _base_state(review_verdict={"approved": False, "confidence": 0.99})
    result = run(state)
    assert result["gate_decision"]["passed"] is False
    assert "reviewer_approved" in result["gate_decision"]["failed_checks"]


def test_unknown_category_and_large_diff_forces_draft():
    big_content = "\n".join(f"line {i}" for i in range(100))
    state = _base_state(
        error_context={"matched_category": "unknown", "extracted_files": ["recipes-demo/libfoo/libfoo_2.1.bb"]},
        patch_proposal={
            "files_to_modify": [
                {"path": "recipes-demo/libfoo/libfoo_2.1.bb", "operation": "modify", "new_content": big_content}
            ],
        },
    )
    result = run(state)
    gate = result["gate_decision"]
    assert gate["passed"] is True
    assert gate["mr_type"] == "draft"
