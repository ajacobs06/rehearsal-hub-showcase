import logging
import os
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)


class DocStore(Protocol):
    """One Cosmos container, or an in-memory stand-in. `partition` defaults to the doc id (pk /id)."""

    def get(self, doc_id: str, partition: str | None = None) -> dict | None: ...
    def find(self, field: str, value: str) -> list[dict]: ...
    def list_all(self) -> list[dict]: ...
    def upsert(self, doc: dict) -> None: ...
    def delete(self, doc_id: str, partition: str | None = None) -> None: ...


class InMemoryStore:
    """Used by tests, and locally when COSMOS_ENDPOINT is not set."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def get(self, doc_id: str, partition: str | None = None) -> dict | None:
        doc = self.docs.get(doc_id)
        return dict(doc) if doc else None

    def find(self, field: str, value: str) -> list[dict]:
        return [dict(d) for d in self.docs.values() if d.get(field) == value]

    def list_all(self) -> list[dict]:
        return [dict(d) for d in self.docs.values()]

    def upsert(self, doc: dict) -> None:
        self.docs[doc["id"]] = dict(doc)

    def delete(self, doc_id: str, partition: str | None = None) -> None:
        self.docs.pop(doc_id, None)


class CosmosStore:
    def __init__(self, endpoint: str, database: str, container: str) -> None:
        from azure.cosmos import CosmosClient

        client = CosmosClient(endpoint, credential=azure_credential())
        self.container = client.get_database_client(database).get_container_client(container)

    def get(self, doc_id: str, partition: str | None = None) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return _strip(self.container.read_item(doc_id, partition_key=partition or doc_id))
        except CosmosResourceNotFoundError:
            return None

    def find(self, field: str, value: str) -> list[dict]:
        if not field.isidentifier():
            raise ValueError(f"bad field name: {field}")
        items = self.container.query_items(
            f"SELECT * FROM c WHERE c.{field} = @value",
            parameters=[{"name": "@value", "value": value}],
            enable_cross_partition_query=True,
        )
        return [_strip(i) for i in items]

    def list_all(self) -> list[dict]:
        return [_strip(i) for i in self.container.read_all_items()]

    def upsert(self, doc: dict) -> None:
        self.container.upsert_item(doc)

    def delete(self, doc_id: str, partition: str | None = None) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self.container.delete_item(doc_id, partition_key=partition or doc_id)
        except CosmosResourceNotFoundError:
            pass


def _strip(item: dict) -> dict:
    """Drop Cosmos system properties (_rid, _etag, ...)."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def on_app_service() -> bool:
    return bool(os.environ.get("WEBSITE_SITE_NAME"))


@lru_cache
def azure_credential():
    from azure.identity import AzureCliCredential, ManagedIdentityCredential

    # On App Service use the web app's managed identity; locally, your `az login`.
    return ManagedIdentityCredential() if on_app_service() else AzureCliCredential()


def _make_store(container: str) -> DocStore:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if endpoint:
        return CosmosStore(endpoint, os.environ.get("COSMOS_DATABASE", "rehearsal-hub-dev"), container)
    if on_app_service():
        raise RuntimeError("COSMOS_ENDPOINT is not set")
    log.warning("COSMOS_ENDPOINT not set: using an in-memory %s store (data is lost on restart)", container)
    return InMemoryStore()


@lru_cache
def get_store() -> DocStore:
    """The members container."""
    return _make_store("members")


@lru_cache
def get_song_store() -> DocStore:
    return _make_store("songs")


@lru_cache
def get_progress_store() -> DocStore:
    """Per member per song (pk /songId, id "<memberId>:<songId>"): part override, later learned state."""
    return _make_store("progress")
