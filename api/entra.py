"""Deletes email-and-password accounts from the Entra External ID tenant.

Members who sign in with email and password have an account in our external tenant (their email,
name and password). Erasing a member must remove it too, and people who sign up without an invite
get theirs removed straight away. Google members have nothing there.

The web app authenticates without a secret: its user-assigned identity (id-rehearsal-hub-graph)
gets a token that the multitenant "Rehearsal Hub account cleanup" app trusts through a federated
credential, and that app holds only User.DeleteRestore.All in the external tenant.
"""

import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Protocol

from fastapi import HTTPException

log = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"


class EntraDeleteFailed(Exception):
    pass


class EntraDirectory(Protocol):
    def delete_user(self, object_id: str) -> None:
        """Delete the account. An account that is already gone counts as deleted. Raises
        EntraDeleteFailed otherwise."""
        ...


class NullDirectory:
    """Used when cleanup isn't configured (local dev, or before the Entra setup)."""

    def delete_user(self, object_id: str) -> None:
        log.warning("Entra cleanup is not configured: account %s was not deleted", object_id)


class GraphDirectory:
    def __init__(self, tenant_id: str, app_client_id: str, identity_client_id: str) -> None:
        from azure.identity import ClientAssertionCredential, ManagedIdentityCredential

        identity = ManagedIdentityCredential(client_id=identity_client_id)
        self.credential = ClientAssertionCredential(
            tenant_id,
            app_client_id,
            lambda: identity.get_token("api://AzureADTokenExchange/.default").token,
        )

    def delete_user(self, object_id: str) -> None:
        try:
            token = self.credential.get_token("https://graph.microsoft.com/.default").token
        except Exception as e:
            raise EntraDeleteFailed("could not get a Graph token") from e
        req = urllib.request.Request(
            f"{GRAPH}/users/{urllib.parse.quote(object_id)}",
            method="DELETE",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15):
                return
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return
            detail = e.read().decode(errors="replace")[:300]
            raise EntraDeleteFailed(f"Graph returned {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise EntraDeleteFailed("Graph could not be reached") from e


def entra_object_id(member_id: str) -> str | None:
    """The Entra object id of an email-and-password member ("aad:<oid>"), else None."""
    idp, _, user_id = member_id.partition(":")
    return user_id if idp == "aad" and user_id else None


@lru_cache
def get_directory() -> EntraDirectory:
    tenant = os.environ.get("ENTRA_TENANT_ID", "").strip()
    app_client = os.environ.get("ENTRA_CLEANUP_CLIENT_ID", "").strip()
    identity_client = os.environ.get("GRAPH_IDENTITY_CLIENT_ID", "").strip()
    if not (tenant and app_client and identity_client):
        return NullDirectory()
    return GraphDirectory(tenant, app_client, identity_client)


def delete_sign_in_accounts(member_ids: list[str], directory: EntraDirectory) -> None:
    """For erasure: delete the member's Entra account (their id or a linked login) before any of our
    data, so a failure leaves everything in place to retry rather than half-deleted."""
    for oid in filter(None, map(entra_object_id, member_ids)):
        try:
            directory.delete_user(oid)
        except EntraDeleteFailed as e:
            log.error("Deleting Entra account %s failed: %s", oid, e)
            raise HTTPException(502, detail={"reason": "sign_in_account_not_deleted"}) from e
