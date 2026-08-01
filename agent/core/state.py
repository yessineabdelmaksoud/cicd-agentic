"""
AgentState — LangGraph shared state TypedDict.

Two runs share this state, joined by a callback (fix.md FIX-7):
  Run A: fetch_logs → parse_error → diagnose → fetch_repo_context →
         generate_patch → review_patch → evaluate_gate → apply_patch →
         trigger_rebuild   [worker ends here; state persisted to Redis]
  Run B: evaluate_result → open_mr / post_comment   [resumed by /callback]
"""

from typing import TypedDict, Literal, Optional


class AgentState(TypedDict):
    # --- Input (from webhook) ---
    job_id: str
    pipeline_id: int
    project_id: int
    commit_sha: str
    branch: str
    build_type: Literal["yocto", "zephyr", "qnx"]
    failed_job_id: int
    log_path: str
    task_log_path: Optional[str]

    # --- Node: fetch_logs ---
    raw_log: str
    task_log: str

    # --- Node: parse_error (rules-first classification) ---
    # {matched_category, rule_fix, deterministic, error_span, error_line,
    #  error_line_number, extracted_files, failing_task, failing_recipe,
    #  structural_confidence, build_type}
    error_context: dict

    # --- Node: diagnose ---
    # {root_cause, fix_type, confidence, candidate_files}
    diagnosis: dict

    # --- Node: fetch_repo_context (NEW — fix.md FIX-1) ---
    repo_context: dict       # {path: real_file_content}
    existing_files: list     # candidate paths that were fetched successfully
    missing_files: list      # candidate paths that don't exist at commit_sha

    # --- Node: generate_patch ---
    # {files_to_modify: [{path, new_content, operation}], confidence, explanation}
    patch_proposal: dict

    # --- Node: review_patch ---
    # {approved, confidence, concerns, auto_approved}
    review_verdict: dict

    # --- Node: evaluate_gate (NEW — fix.md FIX-6) ---
    # {passed, mr_type, failed_checks: [...], checks: {...}}
    gate_decision: dict

    # --- Node: apply_patch / trigger_rebuild ---
    sandbox_branch: str
    sandbox_pipeline_id: int

    # --- Node: evaluate_result (Run B) ---
    sandbox_outcome: Literal["pass", "fail", "timeout", ""]

    # --- Terminal outcome ---
    outcome: Literal["pass", "fail", "manual_review", "low_confidence", ""]

    # --- Retry / loop control ---
    attempt_count: int          # webhook-level attempt cap (Redis-backed, max 2)
    repair_retry_count: int     # in-graph review→generate_patch repair loop (max 1)
    repair_feedback: Optional[str]  # reviewer concerns fed back on a repair retry
    error_message: Optional[str]
