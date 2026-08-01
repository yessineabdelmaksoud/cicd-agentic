"""
Pydantic schemas for API endpoints.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class WebhookPayload(BaseModel):
    """Payload received from GitLab CI's `notify` job when a build fails (v5 §8.1)."""

    pipeline_id: int = Field(..., description="GitLab Pipeline ID")
    project_id: int = Field(..., description="GitLab Project ID")
    commit_sha: str = Field(..., description="Git commit SHA that triggered the build")
    branch: str = Field(..., description="Git branch name")
    build_type: Literal["yocto", "zephyr", "qnx"] = Field(..., description="Type of embedded build")
    failed_job_id: int = Field(..., description="GitLab Job ID that failed")
    failed_job_name: Optional[str] = Field(None, description="GitLab Job name that failed")
    log_path: Optional[str] = Field(None, description="MinIO path to the build log (auto-generated if not provided)")
    task_log_path: Optional[str] = Field(
        None, description="MinIO path to the per-task log (e.g. log.do_compile for Yocto), if uploaded"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "pipeline_id": 42,
                "project_id": 1,
                "commit_sha": "abc123def456",
                "branch": "main",
                "build_type": "yocto",
                "failed_job_id": 101,
            }
        }


class WebhookResponse(BaseModel):
    """Immediate 202 response to acknowledge the webhook."""

    status: str = "accepted"
    job_id: str
    message: str


class CallbackPayload(BaseModel):
    """Callback from validate.yml on the sandbox branch (v5 §8.4)."""

    sandbox_pipeline_id: int
    sandbox_branch: str
    status: Literal["success", "failed", "canceled"]
    build_type: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    models: dict
    redis: str
    minio: str
    queue_depth: Optional[int] = None
