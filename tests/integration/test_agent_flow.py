"""
Integration tests for the Run A / Run B graph split (fix.md FIX-7).
LLM, GitLab API, and MinIO are mocked. Redis-backed idempotency
(try_claim_mr_opened) is mocked too — these tests don't need a live Redis.
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../agent"))

from core.graph import get_run_a_graph, get_run_b_graph, run_graph_job
from services.openrouter_client import OpenRouterClient

# Each node module does `from services.xxx_client import get_xxx_client`, which
# binds the FUNCTION object into that node's namespace at import time — patching
# `services.xxx_client.get_xxx_client` afterwards would not affect those already
# bound references. Instead, seed the module-level singleton these factories
# return so every node's call to its own imported get_xxx_client() function
# resolves to the same mock, regardless of where it was imported.


def sample_payload(sha: str = "abc123def456", pipeline_id: int = 42) -> dict:
    return {
        "job_id": "test-job-001",
        "pipeline_id": pipeline_id,
        "project_id": 1,
        "commit_sha": sha,
        "branch": "main",
        "build_type": "yocto",
        "failed_job_id": 101,
        "log_path": "build-logs/pipeline-42-job-101.log",
        "task_log_path": None,
        "raw_log": "",
        "task_log": "",
        "error_context": {},
        "diagnosis": {},
        "repo_context": {},
        "existing_files": [],
        "missing_files": [],
        "patch_proposal": {},
        "review_verdict": {},
        "gate_decision": {},
        "sandbox_branch": "",
        "sandbox_pipeline_id": 0,
        "sandbox_outcome": "",
        "outcome": "",
        "attempt_count": 1,
        "repair_retry_count": 0,
        "repair_feedback": None,
        "error_message": None,
    }


def _mock_minio(log_bytes: bytes):
    mock_minio = MagicMock()
    mock_response = MagicMock()
    mock_response.read.return_value = log_bytes
    mock_response.close = MagicMock()
    mock_response.release_conn = MagicMock()
    mock_minio.get_object.return_value = mock_response
    return mock_minio


# ---------------------------------------------------------------------------
# Test: Happy Path — real fetched content, LLM patch, gate passes, MR opened
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_grounds_patch_in_real_content_and_opens_mr():
    recipe_path = "recipes-core/libfoo/libfoo_2.1.bb"
    real_content = 'SRC_URI = "https://bad-url.com/libfoo-2.1.tar.gz"\nLICENSE = "MIT"\n'
    fixed_content = 'SRC_URI = "https://github.com/libfoo/libfoo/archive/v2.1.tar.gz"\nLICENSE = "MIT"\n'

    mock_minio = _mock_minio(
        f"ERROR: libfoo-2.1-r0 do_fetch: Fetcher failure\nFailed to fetch URL: https://bad-url.com/libfoo-2.1.tar.gz\nSee {recipe_path}\n".encode()
    )

    async def mock_llm_call(self, agent_role, messages, schema):
        if agent_role == "diagnostician":
            return schema(root_cause="SRC_URI points to a dead tarball", fix_type="fetch", confidence=0.9, candidate_files=[recipe_path])
        if agent_role == "patch_generator":
            return schema(files_to_modify=[{"path": recipe_path, "operation": "modify", "new_content": fixed_content}], confidence=0.88, explanation="Updated SRC_URI to the real GitHub release")
        if agent_role == "reviewer":
            return schema(approved=True, confidence=0.93, concerns="", retryable=False)
        raise AssertionError(f"unexpected role {agent_role}")

    mock_gitlab = MagicMock()
    mock_gitlab.get_raw_file.return_value = real_content
    mock_gitlab.create_branch.return_value = {"name": "ai-fix/42"}
    mock_gitlab.trigger_pipeline.return_value = {"id": 99}
    mock_gitlab.create_merge_request.return_value = {"iid": 1, "web_url": "http://gitlab/mr/1"}

    with patch("services.minio_client._minio_client", mock_minio), \
         patch("services.openrouter_client.OpenRouterClient.call", mock_llm_call), \
         patch("services.openrouter_client._client_instance", OpenRouterClient("test-key")), \
         patch("services.gitlab_client._gitlab_client", mock_gitlab), \
         patch("core.nodes.open_mr.try_claim_mr_opened", return_value=True):

        run_a = get_run_a_graph()
        state_after_a = await run_a.ainvoke(sample_payload())

        assert state_after_a["sandbox_branch"] == "ai-fix/42"
        assert state_after_a["sandbox_pipeline_id"] == 99
        assert state_after_a["gate_decision"]["passed"] is True

        # The committed content must be exactly what generate_patch produced
        # from the REAL fetched content — never a hallucinated original.
        mock_gitlab.update_file.assert_called_once()
        _, kwargs = mock_gitlab.update_file.call_args
        assert kwargs["content"] == fixed_content

        # Run B: validate.yml calls back with success
        state_after_a["sandbox_outcome"] = "pass"
        run_b = get_run_b_graph()
        final_state = await run_b.ainvoke(state_after_a)

        assert final_state["outcome"] == "pass"
        assert mock_gitlab.create_merge_request.called


# ---------------------------------------------------------------------------
# Test: hallucinated candidate file — gate/context never spends a sandbox build
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_candidate_file_routes_to_post_comment_without_llm_patch():
    mock_minio = _mock_minio(b"ERROR: weirdpkg-1.0-r0 do_compile: something obscure failed\n")

    patch_generator_called = False

    async def mock_llm_call(self, agent_role, messages, schema):
        nonlocal patch_generator_called
        if agent_role == "diagnostician":
            return schema(root_cause="Unclear failure", fix_type="generic", confidence=0.4, candidate_files=["made/up/nonexistent.bb"])
        if agent_role == "patch_generator":
            patch_generator_called = True
            raise AssertionError("patch_generator must never be called when no candidate file exists")
        raise AssertionError(f"unexpected role {agent_role}")

    mock_gitlab = MagicMock()
    mock_gitlab.get_raw_file.return_value = None  # doesn't exist at this commit
    mock_gitlab.post_commit_comment.return_value = {}

    with patch("services.minio_client._minio_client", mock_minio), \
         patch("services.openrouter_client.OpenRouterClient.call", mock_llm_call), \
         patch("services.openrouter_client._client_instance", OpenRouterClient("test-key")), \
         patch("services.gitlab_client._gitlab_client", mock_gitlab):

        run_a = get_run_a_graph()
        final_state = await run_a.ainvoke(sample_payload(pipeline_id=43))

        assert final_state["outcome"] == "manual_review"
        assert not patch_generator_called
        assert mock_gitlab.post_commit_comment.called
        assert not mock_gitlab.create_branch.called


# ---------------------------------------------------------------------------
# Test: rules-first deterministic checksum fix — zero LLM calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_deterministic_checksum_fix_never_calls_any_llm():
    recipe_path = "recipes-demo/libfoo/libfoo_2.1.bb"
    old_sum = "b" * 64
    new_sum = "a" * 64
    real_content = f'SRC_URI[sha256sum] = "{old_sum}"\n'

    log = (
        f"ERROR: libfoo-2.1-r0 do_fetch: sha256sum mismatch!\n"
        f"The wrong sha256sum was computed: {new_sum}\n"
        f"The correct expected sha256sum should be: {old_sum}\n"
        f"{recipe_path}\n"
    )
    mock_minio = _mock_minio(log.encode())

    async def mock_llm_call(self, agent_role, messages, schema):
        raise AssertionError(f"no LLM call expected for a deterministic rule fix, got role={agent_role}")

    mock_gitlab = MagicMock()
    mock_gitlab.get_raw_file.return_value = real_content
    mock_gitlab.create_branch.return_value = {"name": "ai-fix/44"}
    mock_gitlab.trigger_pipeline.return_value = {"id": 100}

    with patch("services.minio_client._minio_client", mock_minio), \
         patch("services.openrouter_client.OpenRouterClient.call", mock_llm_call), \
         patch("services.openrouter_client._client_instance", OpenRouterClient("test-key")), \
         patch("services.gitlab_client._gitlab_client", mock_gitlab):

        run_a = get_run_a_graph()
        final_state = await run_a.ainvoke(sample_payload(pipeline_id=44))

        assert final_state["gate_decision"]["passed"] is True
        assert final_state["review_verdict"].get("auto_approved") is True
        mock_gitlab.update_file.assert_called_once()
        _, kwargs = mock_gitlab.update_file.call_args
        assert old_sum not in kwargs["content"]
        assert new_sum in kwargs["content"]


# ---------------------------------------------------------------------------
# Test: reviewer rejects, not retryable — routes to post_comment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reviewer_reject_not_retryable_routes_to_post_comment():
    recipe_path = "recipes-core/weird/weird_1.0.bb"
    mock_minio = _mock_minio(b"ERROR: weird-1.0-r0 do_compile: some obscure build error\n")

    async def mock_llm_call(self, agent_role, messages, schema):
        if agent_role == "diagnostician":
            return schema(root_cause="Unknown, possibly hardware-related", fix_type="generic", confidence=0.45, candidate_files=[recipe_path])
        if agent_role == "patch_generator":
            return schema(files_to_modify=[{"path": recipe_path, "operation": "modify", "new_content": "changed\n"}], confidence=0.4, explanation="best guess")
        if agent_role == "reviewer":
            return schema(approved=False, confidence=0.35, concerns="Diagnosis too uncertain", retryable=False)
        raise AssertionError(f"unexpected role {agent_role}")

    mock_gitlab = MagicMock()
    mock_gitlab.get_raw_file.return_value = "original content\n"
    mock_gitlab.post_commit_comment.return_value = {}

    with patch("services.minio_client._minio_client", mock_minio), \
         patch("services.openrouter_client.OpenRouterClient.call", mock_llm_call), \
         patch("services.openrouter_client._client_instance", OpenRouterClient("test-key")), \
         patch("services.gitlab_client._gitlab_client", mock_gitlab):

        run_a = get_run_a_graph()
        final_state = await run_a.ainvoke(sample_payload(pipeline_id=45))

        assert final_state["outcome"] == "low_confidence"
        assert mock_gitlab.post_commit_comment.called
        assert not mock_gitlab.create_branch.called


# ---------------------------------------------------------------------------
# Test: every configured LLM fails (primary + paid fallback both down) —
# run_graph_job must never crash silently, always post_comment (found live:
# OpenRouter free-tier 429 + paid-fallback 402 with no credits)
# ---------------------------------------------------------------------------

def test_total_llm_outage_falls_back_to_post_comment_not_a_crash():
    mock_minio = _mock_minio(b"ERROR: somepkg-1.0-r0 do_compile: Fetcher failure\nFailed to fetch URL: https://dead.example/x.tar.gz\nrecipes/somepkg/somepkg_1.0.bb\n")

    async def mock_llm_call(self, agent_role, messages, schema):
        raise RuntimeError("simulated total LLM outage (429 primary, 402 fallback)")

    mock_gitlab = MagicMock()
    mock_gitlab.post_commit_comment.return_value = {}

    payload = {
        "job_id": "test-crash-001",
        "pipeline_id": 46,
        "project_id": 1,
        "commit_sha": "deadbeef",
        "branch": "main",
        "build_type": "yocto",
        "failed_job_id": 999,
        "log_path": "build-logs/pipeline-46-job-999.log",
    }

    with patch("services.minio_client._minio_client", mock_minio), \
         patch("services.openrouter_client.OpenRouterClient.call", mock_llm_call), \
         patch("services.openrouter_client._client_instance", OpenRouterClient("test-key")), \
         patch("services.gitlab_client._gitlab_client", mock_gitlab):

        final_state = run_graph_job(payload)

        assert final_state["outcome"] == "manual_review"
        assert mock_gitlab.post_commit_comment.called
        assert not mock_gitlab.create_branch.called
