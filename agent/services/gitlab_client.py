"""
GitLab Client — Wrapper around GitLab REST API v4.
Covers: branches, files, pipelines, MRs, commit comments.
"""

import os
import base64
import structlog
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()

_gitlab_client: "GitLabClient | None" = None


class GitLabClient:
    """GitLab REST API v4 client."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v4{path}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def _get(self, path: str, **kwargs) -> dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(self._url(path), headers=self.headers, **kwargs)
            resp.raise_for_status()
            return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def _post(self, path: str, json: dict | None = None, **kwargs) -> dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self._url(path), headers=self.headers, json=json, **kwargs)
            resp.raise_for_status()
            return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def _put(self, path: str, json: dict | None = None, **kwargs) -> dict:
        with httpx.Client(timeout=30.0) as client:
            resp = client.put(self._url(path), headers=self.headers, json=json, **kwargs)
            resp.raise_for_status()
            return resp.json()

    def _delete(self, path: str, json: dict | None = None, **kwargs) -> None:
        with httpx.Client(timeout=30.0) as client:
            resp = client.delete(self._url(path), headers=self.headers, json=json, **kwargs)
            resp.raise_for_status()

    # -------------------------------------------------------------------------
    # Branch operations
    # -------------------------------------------------------------------------
    def create_branch(self, project_id: int, branch_name: str, ref: str) -> dict:
        return self._post(
            f"/projects/{project_id}/repository/branches",
            json={"branch": branch_name, "ref": ref},
        )

    def delete_branch(self, project_id: int, branch_name: str) -> None:
        self._delete(f"/projects/{project_id}/repository/branches/{branch_name}")

    # -------------------------------------------------------------------------
    # File operations
    # -------------------------------------------------------------------------
    def get_file_content(self, project_id: int, branch: str, file_path: str) -> str:
        """Get decoded file content from GitLab repository."""
        import urllib.parse
        encoded_path = urllib.parse.quote(file_path, safe="")
        data = self._get(
            f"/projects/{project_id}/repository/files/{encoded_path}",
            params={"ref": branch},
        )
        content = data.get("content", "")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            return base64.b64decode(content).decode("utf-8", errors="replace")
        return content

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    def get_raw_file(self, project_id: int, file_path: str, ref: str) -> str | None:
        """
        Fetch the REAL file content at a specific ref (commit SHA or branch) via
        the raw endpoint. Returns None if the file doesn't exist at that ref —
        callers must treat that as "this candidate file doesn't exist", never
        invent content for it (fix.md FIX-1).
        """
        import urllib.parse
        encoded_path = urllib.parse.quote(file_path, safe="")
        url = self._url(f"/projects/{project_id}/repository/files/{encoded_path}/raw")
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, headers=self.headers, params={"ref": ref})
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.text

    def create_file(self, project_id: int, branch: str, file_path: str, content: str, commit_message: str) -> dict:
        import urllib.parse
        encoded_path = urllib.parse.quote(file_path, safe="")
        return self._post(
            f"/projects/{project_id}/repository/files/{encoded_path}",
            json={
                "branch": branch,
                "content": content,
                "commit_message": commit_message,
                "encoding": "text",
            },
        )

    def update_file(self, project_id: int, branch: str, file_path: str, content: str, commit_message: str) -> dict:
        import urllib.parse
        encoded_path = urllib.parse.quote(file_path, safe="")
        return self._put(
            f"/projects/{project_id}/repository/files/{encoded_path}",
            json={
                "branch": branch,
                "content": content,
                "commit_message": commit_message,
                "encoding": "text",
            },
        )

    def delete_file(self, project_id: int, branch: str, file_path: str, commit_message: str) -> None:
        import urllib.parse
        encoded_path = urllib.parse.quote(file_path, safe="")
        self._delete(
            f"/projects/{project_id}/repository/files/{encoded_path}",
            json={"branch": branch, "commit_message": commit_message},
        )

    # -------------------------------------------------------------------------
    # Pipeline operations
    # -------------------------------------------------------------------------
    def trigger_pipeline(self, project_id: int, ref: str, variables: dict | None = None) -> dict:
        payload: dict = {"ref": ref}
        if variables:
            payload["variables"] = [
                {"key": k, "value": v} for k, v in variables.items()
            ]
        return self._post(f"/projects/{project_id}/pipeline", json=payload)

    def get_pipeline(self, project_id: int, pipeline_id: int) -> dict:
        return self._get(f"/projects/{project_id}/pipelines/{pipeline_id}")

    # -------------------------------------------------------------------------
    # Merge Request operations
    # -------------------------------------------------------------------------
    def create_merge_request(
        self,
        project_id: int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
        draft: bool = False,
    ) -> dict:
        payload = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": f"Draft: {title}" if draft else title,
            "description": description,
            "labels": ",".join(labels or []),
            "remove_source_branch": False,
            "squash": False,
        }
        return self._post(f"/projects/{project_id}/merge_requests", json=payload)

    # -------------------------------------------------------------------------
    # Commit comment operations
    # -------------------------------------------------------------------------
    def post_commit_comment(self, project_id: int, commit_sha: str, note: str) -> dict:
        return self._post(
            f"/projects/{project_id}/repository/commits/{commit_sha}/comments",
            json={"note": note},
        )

    # -------------------------------------------------------------------------
    # Health check
    # -------------------------------------------------------------------------
    def check_connection(self) -> bool:
        try:
            self._get("/version")
            return True
        except Exception:
            return False


def get_gitlab_client() -> GitLabClient:
    """Return singleton GitLab client."""
    global _gitlab_client
    if _gitlab_client is None:
        base_url = os.getenv("GITLAB_EXTERNAL_URL", "http://localhost")
        token = os.getenv("GITLAB_PROJECT_TOKEN", "")
        if not token:
            raise RuntimeError("GITLAB_PROJECT_TOKEN environment variable is not set")
        _gitlab_client = GitLabClient(base_url=base_url, token=token)
        log.info("gitlab.client_created", base_url=base_url)
    return _gitlab_client
