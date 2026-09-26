import logging
import os
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)


class MemberStore(Protocol):
    def get(self, member_id: str) -> dict | None: ...
    def find_by_email(self, email: str) -> list[dict]: ...
    def list_all(self) -> list[dict]: ...
    def upsert(self, doc: dict) -> None: ...
    def delete(self, member_id: str) -> None: ...


class InMemoryMemberStore:
    """Used by tests, and locally when COSMOS_ENDPOINT is not set."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {}

    def get(self, member_id: str) -> dict | None:
        return self.docs.get(member_id)

    def find_by_email(self, email: str) -> list[dict]:
        return [d for d in self.docs.values() if d["email"] == email]

    def list_all(self) -> list[dict]:
        return list(self.docs.values())

    def upsert(self, doc: dict) -> None:
        self.docs[doc["id"]] = dict(doc)

    def delete(self, member_id: str) -> None:
        self.docs.pop(member_id, None)


class CosmosMemberStore:
    def __init__(self, endpoint: str, database: str) -> None:
        from azure.cosmos import CosmosClient
        from azure.identity import AzureCliCredential, ManagedIdentityCredential

        # On App Service use the web app's managed identity; locally, your `az login`.
        credential = ManagedIdentityCredential() if on_app_service() else AzureCliCredential()
        client = CosmosClient(endpoint, credential=credential)
        self.container = client.get_database_client(database).get_container_client("members")

    def get(self, member_id: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return _strip(self.container.read_item(member_id, partition_key=member_id))
        except CosmosResourceNotFoundError:
            return None

    def find_by_email(self, email: str) -> list[dict]:
        items = self.container.query_items(
            "SELECT * FROM m WHERE m.email = @email",
            parameters=[{"name": "@email", "value": email}],
            enable_cross_partition_query=True,
        )
        return [_strip(i) for i in items]

    def list_all(self) -> list[dict]:
        return [_strip(i) for i in self.container.read_all_items()]

    def upsert(self, doc: dict) -> None:
        self.container.upsert_item(doc)

    def delete(self, member_id: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self.container.delete_item(member_id, partition_key=member_id)
        except CosmosResourceNotFoundError:
            pass


def _strip(item: dict) -> dict:
    """Drop Cosmos system properties (_rid, _etag, ...)."""
    return {k: v for k, v in item.items() if not k.startswith("_")}


def on_app_service() -> bool:
    return bool(os.environ.get("WEBSITE_SITE_NAME"))


@lru_cache
def get_store() -> MemberStore:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    if endpoint:
        return CosmosMemberStore(endpoint, os.environ.get("COSMOS_DATABASE", "rehearsal-hub-dev"))
    if on_app_service():
        raise RuntimeError("COSMOS_ENDPOINT is not set")
    log.warning("COSMOS_ENDPOINT not set: using an in-memory member store (data is lost on restart)")
    return InMemoryMemberStore()
