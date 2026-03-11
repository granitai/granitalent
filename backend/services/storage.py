"""Storage service — abstracts file storage behind S3-compatible API.

Supports any S3-compatible provider:
- Cloudflare R2 (10GB free)
- Backblaze B2 (10GB free)
- AWS S3
- MinIO (self-hosted)

Configure via environment variables:
  S3_ENDPOINT_URL   — e.g. https://xxx.r2.cloudflarestorage.com
  S3_ACCESS_KEY_ID  — access key
  S3_SECRET_ACCESS_KEY — secret key
  S3_BUCKET_NAME    — bucket name
  S3_REGION         — region (default: auto)
  S3_PUBLIC_URL     — optional public base URL for serving files

Falls back to local filesystem if S3 is not configured.
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# S3 config from env
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_REGION = os.getenv("S3_REGION", "auto")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "")

_s3_client = None
_s3_enabled = False


def _get_s3_client():
    """Lazy-init S3 client."""
    global _s3_client, _s3_enabled
    if _s3_client is not None:
        return _s3_client

    if not all([S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_BUCKET_NAME]):
        logger.info("S3 not configured — using local filesystem storage")
        _s3_enabled = False
        return None

    try:
        import boto3
        from botocore.config import Config
        _s3_client = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=S3_ACCESS_KEY_ID,
            aws_secret_access_key=S3_SECRET_ACCESS_KEY,
            region_name=S3_REGION,
            config=Config(s3={"addressing_style": "path"}),
        )
        # Verify bucket access
        _s3_client.head_bucket(Bucket=S3_BUCKET_NAME)
        _s3_enabled = True
        logger.info(f"S3 storage enabled — bucket: {S3_BUCKET_NAME}")
        return _s3_client
    except ImportError:
        logger.warning("boto3 not installed — using local filesystem storage. Install with: pip install boto3")
        _s3_enabled = False
        return None
    except Exception as e:
        logger.warning(f"S3 connection failed — using local filesystem: {e}")
        _s3_enabled = False
        return None


def is_s3_enabled() -> bool:
    """Check if S3 storage is available."""
    _get_s3_client()
    return _s3_enabled


def upload_file(file_bytes: bytes, key: str, content_type: str = "application/octet-stream", local_dir: str = "") -> str:
    """Upload a file to S3 or local filesystem.

    Args:
        file_bytes: File content
        key: Storage key/path (e.g. "cvs/app_xxx.pdf")
        content_type: MIME type
        local_dir: Local uploads base directory (fallback)

    Returns:
        The storage key (same as input key)
    """
    client = _get_s3_client()

    if client and _s3_enabled:
        try:
            client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
            )
            logger.info(f"Uploaded to S3: {key} ({len(file_bytes)} bytes)")
            return key
        except Exception as e:
            logger.error(f"S3 upload failed for {key}: {e}")
            # Fall through to local storage
            logger.info("Falling back to local storage")

    # Local filesystem fallback
    if local_dir:
        full_path = os.path.join(local_dir, key)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_bytes)
        logger.info(f"Saved locally: {full_path} ({len(file_bytes)} bytes)")

    return key


def download_file(key: str, local_dir: str = "") -> Optional[bytes]:
    """Download a file from S3 or local filesystem.

    Args:
        key: Storage key/path
        local_dir: Local uploads base directory (fallback)

    Returns:
        File bytes, or None if not found
    """
    client = _get_s3_client()

    if client and _s3_enabled:
        try:
            response = client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
            data = response["Body"].read()
            logger.info(f"Downloaded from S3: {key} ({len(data)} bytes)")
            return data
        except client.exceptions.NoSuchKey:
            logger.warning(f"S3 key not found: {key}")
            # Fall through to local
        except Exception as e:
            logger.error(f"S3 download failed for {key}: {e}")

    # Local filesystem fallback
    if local_dir:
        full_path = os.path.join(local_dir, key)
        if os.path.exists(full_path):
            with open(full_path, "rb") as f:
                return f.read()

    return None


def get_presigned_url(key: str, expires_in: int = 3600) -> Optional[str]:
    """Generate a presigned URL for direct download.

    Args:
        key: Storage key/path
        expires_in: URL expiry in seconds (default 1 hour)

    Returns:
        Presigned URL string, or None if S3 not available
    """
    client = _get_s3_client()

    if client and _s3_enabled:
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET_NAME, "Key": key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {key}: {e}")

    return None


def delete_file(key: str, local_dir: str = "") -> bool:
    """Delete a file from S3 or local filesystem."""
    client = _get_s3_client()

    if client and _s3_enabled:
        try:
            client.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
            logger.info(f"Deleted from S3: {key}")
            return True
        except Exception as e:
            logger.error(f"S3 delete failed for {key}: {e}")

    if local_dir:
        full_path = os.path.join(local_dir, key)
        if os.path.exists(full_path):
            os.remove(full_path)
            return True

    return False


def file_exists(key: str, local_dir: str = "") -> bool:
    """Check if a file exists in S3 or local filesystem."""
    client = _get_s3_client()

    if client and _s3_enabled:
        try:
            client.head_object(Bucket=S3_BUCKET_NAME, Key=key)
            return True
        except Exception:
            return False

    if local_dir:
        return os.path.exists(os.path.join(local_dir, key))

    return False
