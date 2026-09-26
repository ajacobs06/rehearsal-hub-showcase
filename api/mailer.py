import logging
import os
from functools import lru_cache
from typing import Protocol

log = logging.getLogger(__name__)


class Mailer(Protocol):
    def send_invite(self, to: str, name: str, invited_by: str) -> bool: ...


class NullMailer:
    """Used when email isn't configured: invites still work as an allowlist."""

    def send_invite(self, to: str, name: str, invited_by: str) -> bool:
        return False


class AcsMailer:
    def __init__(self, connection_string: str, sender: str, app_url: str) -> None:
        from azure.communication.email import EmailClient

        self.client = EmailClient.from_connection_string(connection_string)
        self.sender = sender
        self.app_url = app_url

    def send_invite(self, to: str, name: str, invited_by: str) -> bool:
        body = (
            f"Hi {name},\n\n"
            f"{invited_by} has invited you to Rehearsal Hub, the UoB Barbershop Singing Society's "
            "members' site for learning tracks and the rehearsal schedule.\n\n"
            f"Sign in with Google, or with this email address and a password you create ({to}):\n{self.app_url}\n\n"
            "If you weren't expecting this, you can ignore it."
        )
        try:
            poller = self.client.begin_send(
                {
                    "senderAddress": self.sender,
                    "recipients": {"to": [{"address": to}]},
                    "content": {"subject": "You're invited to Rehearsal Hub", "plainText": body},
                }
            )
            return poller.result(timeout=60).get("status") == "Succeeded"
        except Exception:
            log.exception("Failed to send invite email to %s", to)
            return False


@lru_cache
def get_mailer() -> Mailer:
    conn = os.environ.get("ACS_CONNECTION_STRING", "")
    sender = os.environ.get("EMAIL_SENDER", "")
    # An unresolved Key Vault reference arrives as the literal "@Microsoft.KeyVault(...)" string.
    if not conn or conn.startswith("@Microsoft.KeyVault") or not sender:
        return NullMailer()
    return AcsMailer(conn, sender, os.environ.get("APP_URL", "http://localhost:5173"))
