"""S3-compatible storage backend using obstore.

Supports AWS S3, Cloudflare R2 (via S3-compatible endpoint), and Google Cloud Storage.
See ADR 011 for the rationale for choosing obstore over boto3.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from mediakit.config import MediakitConfig

if TYPE_CHECKING:
    import obstore.store as obs


class S3CompatibleBackend:
    """obstore-based storage backend.

    Covers AWS S3 and any S3-compatible endpoint (Cloudflare R2, MinIO, etc.)
    when ``config.endpoint_url`` is set, and GCS when ``config.provider == "gcs"``.

    Implements the ``StorageBackend`` protocol defined in ``mediakit.storage.backend``.
    """

    def __init__(self, config: MediakitConfig) -> None:
        self.config = config
        self._store: obs.S3Store | obs.GCSStore | None = None

    def _get_store(self) -> obs.S3Store | obs.GCSStore:
        if self._store is None:
            import obstore.store as obs_store

            if self.config.provider == "gcs":
                self._store = obs_store.GCSStore.from_url(
                    f"gs://{self.config.bucket}/",
                )
            else:
                # AWS S3 or any S3-compatible endpoint (R2, MinIO, etc.)
                store_config: dict[str, str] = {}
                if self.config.region_name:
                    store_config["AWS_REGION"] = self.config.region_name
                if self.config.endpoint_url:
                    store_config["AWS_ENDPOINT"] = self.config.endpoint_url
                if self.config.aws_access_key_id:
                    store_config["AWS_ACCESS_KEY_ID"] = self.config.aws_access_key_id
                if self.config.aws_secret_access_key:
                    store_config["AWS_SECRET_ACCESS_KEY"] = self.config.aws_secret_access_key
                self._store = obs_store.S3Store.from_url(
                    f"s3://{self.config.bucket}/",
                    config=store_config,
                )
        return self._store

    async def prepare_upload(self, key: str, content_type: str, expires_in: int = 900) -> dict:
        """Return a presigned PUT URL for direct browser-to-bucket upload.

        Returns ``{ "upload_url": str, "key": str, "expires_at": str }``.
        The browser PUTs directly to ``upload_url`` — mediakit never sees the bytes.
        """
        # TODO: implement — obstore.sign_async(store, "PUT", key, timedelta(seconds=expires_in))
        raise NotImplementedError

    async def confirm_exists(self, key: str) -> bool:
        """Return True if the object exists in the bucket."""
        # TODO: implement — obstore.head_async(store, key)
        raise NotImplementedError

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a presigned GET URL (or public URL if bucket is public-read).

        Used by the IIIF endpoint to issue a 302 redirect — the response bytes
        never flow through the application server.
        """
        # TODO: implement — obstore.sign_async(store, "GET", key, timedelta(seconds=expires_in))
        #                    or public URL construction when config.public_read is True
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """Delete the object from the bucket."""
        # TODO: implement — obstore.delete_async(store, key)
        raise NotImplementedError

    async def list_objects(self, prefix: str = "", max_keys: int = 1000) -> list[dict]:
        """List objects under the given prefix.

        Returns ``[{ "key": str, "size": int, "last_modified": str }, ...]``.
        Used by ``mediakit sync`` and ``mediakit gc``.
        """
        # TODO: implement — obstore.list_async(store, prefix=prefix)
        raise NotImplementedError
