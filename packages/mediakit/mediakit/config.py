"""Mediakit configuration model."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class MediakitConfig(BaseModel):
    # Storage
    bucket: str
    endpoint_url: str | None = None        # None for AWS S3; set for GCS, R2
    aws_access_key_id: str | None = None   # falls back to AWS_ACCESS_KEY_ID env var
    aws_secret_access_key: str | None = None
    region_name: str = "auto"

    # Catalog
    catalog_path: str = "./media_catalog.db"

    # Processing
    max_dimension: int = 4096
    upload_format: str = "webp"
    upload_quality: int = 85
    strip_exif: bool = True

    # Auth
    api_key: str | None = None
    auth: Any | None = None                # callable (request) -> bool, or None

    # Serving
    public_read: bool = False
    presign_expires: int = 3600            # 1 hour
    upload_expires: int = 900              # 15 minutes

    # Paths
    mount_path: str = "/media"

    model_config = {"arbitrary_types_allowed": True}
