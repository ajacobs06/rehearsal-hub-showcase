import logging
import os
from functools import lru_cache
from typing import Any, Protocol

Path = tuple[str, ...]

log = logging.getLogger(__name__)


class DocStore(Protocol):
    """One Cosmos container, or an in-memory stand-in. `partition` defaults to the doc id (pk /id)."""

    def get(self, doc_id: str, partition: str | None = None) -> dict | None: ...
    def find(self, field: str, value: str) -> list[dict]: ...
    def list_all(self) -> list[dict]: ...
    def upsert(self, doc: dict) -> None: ...
    def delete(self, doc_id: str, partition: str | None = None) -> None: ...
    def patch(
        self,
        doc_id: str,
        set_fields: dict[Path, Any] | None = None,
        remove_fields: list[Path] | None = None,
        partition: str | None = None,
    ) -> dict | None:
        """Atomically set/remove fields without rewriting the doc (so concurrent edits to other
        fields aren't lost). Removing a missing field is a no-op. Returns the doc, or None if absent."""
        ...


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

    def patch(self, doc_id, set_fields=None, remove_fields=None, partition=None):
        doc = self.docs.get(doc_id)
        if doc is None:
            return None
        for path, value in (set_fields or {}).items():
            target = doc
            for key in path[:-1]:
                target = target.setdefault(key, {})
            target[path[-1]] = value
        for path in remove_fields or []:
            target = doc
            for key in path[:-1]:
                target = target.get(key, {})
            target.pop(path[-1], None)
        return dict(doc)


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

    def patch(self, doc_id, set_fields=None, remove_fields=None, partition=None):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        pk = partition or doc_id
        ops = [{"op": "set", "path": _pointer(p), "value": v} for p, v in (set_fields or {}).items()]
        if remove_fields:
            # Cosmos rejects removing a path that doesn't exist, so only remove what is there.
            current = self.get(doc_id, partition=pk)
            if current is None:
                return None
            ops += [{"op": "remove", "path": _pointer(p)} for p in remove_fields if _get_path(current, p) is not None]
        if not ops:
            return self.get(doc_id, partition=pk)
        try:
            doc = None
            for i in range(0, len(ops), 10):  # Cosmos allows 10 operations per patch
                doc = self.container.patch_item(doc_id, partition_key=pk, patch_operations=ops[i : i + 10])
            return _strip(doc)
        except CosmosResourceNotFoundError:
            return None


def _pointer(path: Path) -> str:
    """JSON Pointer for a Cosmos patch op; escapes ~ and / inside keys."""
    return "".join("/" + k.replace("~", "~0").replace("/", "~1") for k in path)


def _get_path(doc: dict, path: Path) -> Any:
    for key in path:
        if not isinstance(doc, dict) or key not in doc:
            return None
        doc = doc[key]
    return doc


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


@lru_cache
def get_rehearsal_store() -> DocStore:
    return _make_store("rehearsals")


@lru_cache
def get_group_store() -> DocStore:
    """Groups added by admins, e.g. quartets (fixed groups live in code, see groups.py)."""
    return _make_store("groups")
