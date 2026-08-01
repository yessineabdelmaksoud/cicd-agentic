"""
MinIO Client — Object storage for build logs and artifacts.
"""

import os
import structlog
from minio import Minio
from minio.error import S3Error

log = structlog.get_logger()

_minio_client: Minio | None = None


def get_minio_client() -> Minio:
    """Return the singleton MinIO client."""
    global _minio_client
    if _minio_client is None:
        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        # Strip http:// or https:// prefix (Minio SDK expects host:port)
        endpoint = endpoint.replace("http://", "").replace("https://", "")
        secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

        _minio_client = Minio(
            endpoint=endpoint,
            access_key=os.getenv("MINIO_ROOT_USER", "admin"),
            secret_key=os.getenv("MINIO_ROOT_PASSWORD", "password123"),
            secure=secure,
        )
        log.info("minio.client_created", endpoint=endpoint)
    return _minio_client


def upload_result(pipeline_id: int, content: str, filename: str = "agent-result.json") -> str:
    """Upload agent result JSON to the agent-results bucket."""
    import io
    client = get_minio_client()
    bucket = "agent-results"
    object_name = f"pipeline-{pipeline_id}/{filename}"

    data = content.encode("utf-8")
    client.put_object(
        bucket,
        object_name,
        data=io.BytesIO(data),
        length=len(data),
        content_type="application/json",
    )

    log.info("minio.upload_result", bucket=bucket, object=object_name)
    return object_name
