"""Blob Storage for tracks and scores.

Audio and PDFs never pass through the API. The API hands the browser a per-blob SAS link that
expires in 15 minutes, signed with a user delegation key from the app's managed identity (the
storage account has shared keys disabled).
"""

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Protocol

from store import azure_credential, on_app_service

SAS_LIFETIME = timedelta(minutes=15)


@dataclass(frozen=True)
class BlobInfo:
    size: int


class TrackStore(Protocol):
    def upload_url(self, path: str, content_type: str) -> tuple[str, datetime]: ...
    def read_url(self, path: str, content_type: str, download_name: str | None) -> tuple[str, datetime]: ...
    def info(self, path: str) -> BlobInfo | None: ...
    def first_bytes(self, path: str, n: int) -> bytes: ...
    def delete(self, path: str) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...


class AzureTrackStore:
    def __init__(self, account_url: str, container: str) -> None:
        from azure.storage.blob import BlobServiceClient

        self.service = BlobServiceClient(account_url, credential=azure_credential())
        self.container = self.service.get_container_client(container)
        self.container_name = container
        self._key = None
        self._key_expiry = datetime.min.replace(tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def _delegation_key(self):
        # One key signs many links; refresh it well before it expires.
        now = datetime.now(timezone.utc)
        with self._lock:
            if self._key is None or self._key_expiry - now < timedelta(minutes=30):
                self._key_expiry = now + timedelta(hours=2)
                self._key = self.service.get_user_delegation_key(now - timedelta(minutes=5), self._key_expiry)
            return self._key

    def _sas_url(self, path: str, permission, **overrides) -> tuple[str, datetime]:
        from urllib.parse import quote

        from azure.storage.blob import generate_blob_sas

        now = datetime.now(timezone.utc)
        expiry = now + SAS_LIFETIME
        sas = generate_blob_sas(
            account_name=self.service.account_name,
            container_name=self.container_name,
            blob_name=path,
            user_delegation_key=self._delegation_key(),
            permission=permission,
            start=now - timedelta(minutes=5),  # tolerate clock skew
            expiry=expiry,
            protocol="https",
            **overrides,
        )
        return f"{self.container.url}/{quote(path)}?{sas}", expiry

    def upload_url(self, path: str, content_type: str) -> tuple[str, datetime]:
        from azure.storage.blob import BlobSasPermissions

        return self._sas_url(path, BlobSasPermissions(create=True, write=True))

    def read_url(self, path: str, content_type: str, download_name: str | None) -> tuple[str, datetime]:
        from azure.storage.blob import BlobSasPermissions

        # Force the response type (and, for downloads, the filename) whatever was uploaded.
        disposition = f'attachment; filename="{download_name}"' if download_name else "inline"
        return self._sas_url(
            path, BlobSasPermissions(read=True), content_type=content_type, content_disposition=disposition
        )

    def info(self, path: str) -> BlobInfo | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            props = self.container.get_blob_client(path).get_blob_properties()
        except ResourceNotFoundError:
            return None
        return BlobInfo(size=props.size)

    def first_bytes(self, path: str, n: int) -> bytes:
        return self.container.get_blob_client(path).download_blob(offset=0, length=n).readall()

    def delete(self, path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self.container.delete_blob(path)
        except ResourceNotFoundError:
            pass

    def delete_prefix(self, prefix: str) -> None:
        for blob in self.container.list_blobs(name_starts_with=prefix):
            self.delete(blob.name)


class InMemoryTrackStore:
    """Used by tests, and locally when STORAGE_ACCOUNT_URL is not set (links won't work)."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def upload_url(self, path: str, content_type: str) -> tuple[str, datetime]:
        return f"https://storage.invalid/{path}?sig=write", datetime.now(timezone.utc) + SAS_LIFETIME

    def read_url(self, path: str, content_type: str, download_name: str | None) -> tuple[str, datetime]:
        return f"https://storage.invalid/{path}?sig=read", datetime.now(timezone.utc) + SAS_LIFETIME

    def info(self, path: str) -> BlobInfo | None:
        return BlobInfo(size=len(self.blobs[path])) if path in self.blobs else None

    def first_bytes(self, path: str, n: int) -> bytes:
        return self.blobs[path][:n]

    def delete(self, path: str) -> None:
        self.blobs.pop(path, None)

    def delete_prefix(self, prefix: str) -> None:
        for path in [p for p in self.blobs if p.startswith(prefix)]:
            del self.blobs[path]


@lru_cache
def get_track_store() -> TrackStore:
    url = os.environ.get("STORAGE_ACCOUNT_URL")
    if url:
        return AzureTrackStore(url, os.environ.get("TRACKS_CONTAINER", "tracks-dev"))
    if on_app_service():
        raise RuntimeError("STORAGE_ACCOUNT_URL is not set")
    return InMemoryTrackStore()
