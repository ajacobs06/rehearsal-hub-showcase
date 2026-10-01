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


# Replies reach the committee rather than the unattended DoNotReply sender.
SOCIETY_CONTACT = "barbershopsingingsociety@gmail.com"
SOCIETY_URL = "https://www.guildofstudents.com/organisation/bss/"


def invite_message(sender: str, app_url: str, to: str, name: str, invited_by: str) -> dict:
    """The invite email. It comes from a generic Azure address with a link to an azurewebsites.net
    site, which is what phishing looks like, so it says plainly who sent it and why, gives a human
    to reply to, and never asks for a password by email."""
    body = (
        f"Hi {name},\n\n"
        f"{invited_by} from the committee has added you to Rehearsal Hub, the University of Birmingham "
        "Barbershop Singing Society's members' site for scores, learning tracks and the rehearsal schedule.\n\n"
        f"To use it, open {app_url} and sign in with this address ({to}):\n"
        "- For a Gmail or Google account, choose Sign in with Google.\n"
        "- For any other address, choose Sign in with email and create an account the first time.\n"
        "Either way reaches the same account.\n\n"
        "Not sure this is genuine? Reply to this email to reach the committee, or ask us at rehearsal. "
        f"About the society: {SOCIETY_URL}\n\n"
        "If you weren't expecting this, you can ignore it."
    )
    return {
        "senderAddress": sender,
        "recipients": {"to": [{"address": to}]},
        "replyTo": [{"address": SOCIETY_CONTACT, "displayName": "Barbershop Singing Society committee"}],
        "content": {
            "subject": f"{invited_by} added you to the Barbershop Singing Society's Rehearsal Hub",
            "plainText": body,
        },
    }


class AcsMailer:
    def __init__(self, connection_string: str, sender: str, app_url: str) -> None:
        from azure.communication.email import EmailClient

        self.client = EmailClient.from_connection_string(connection_string)
        self.sender = sender
        self.app_url = app_url

    def send_invite(self, to: str, name: str, invited_by: str) -> bool:
        try:
            poller = self.client.begin_send(invite_message(self.sender, self.app_url, to, name, invited_by))
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
