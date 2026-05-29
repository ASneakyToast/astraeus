"""S3-compatible storage backend using boto3. Supports GCS, Cloudflare R2, and AWS S3."""

from __future__ import annotations

from mediakit.config import MediakitConfig


class S3CompatibleBackend:
    """boto3-based storage backend. Configured via MediakitConfig."""

    def __init__(self, config: MediakitConfig) -> None:
        self.config = config
        self._client = None  # initialised lazily

    def _get_client(self):
        if self._client is None:
            import boto3
            kwargs = {
                "service_name": "s3",
                "region_name": self.config.region_name,
            }
            if self.config.endpoint_url:
                kwargs["endpoint_url"] = self.config.endpoint_url
            if self.config.aws_access_key_id:
                kwargs["aws_access_key_id"] = self.config.aws_access_key_id
                kwargs["aws_secret_access_key"] = self.config.aws_secret_access_key
            self._client = boto3.client(**kwargs)
        return self._client

    async def prepare_upload(self, key: str, content_type: str, expires_in: int = 900) -> dict:
        # TODO: implement presigned PUT URL generation
        raise NotImplementedError

    async def confirm_exists(self, key: str) -> bool:
        # TODO: implement head_object check
        raise NotImplementedError

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        # TODO: implement presigned GET or public URL
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        # TODO: implement delete_object
        raise NotImplementedError

    async def list_objects(self, prefix: str = "", max_keys: int = 1000) -> list[dict]:
        # TODO: implement list_objects_v2
        raise NotImplementedError
