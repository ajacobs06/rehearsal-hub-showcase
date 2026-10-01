"""What strangers and scanners see: real 404s for made-up paths, and an invite email that
doesn't read like phishing."""

import pytest

from mailer import SOCIETY_CONTACT, invite_message
from main import is_app_route


@pytest.mark.parametrize(
    "path",
    ["", "privacy", "songs", "songs/abc123", "schedule", "rehearsals/abc123", "announcements", "announcements/abc",
     "feedback", "account", "members", "tracker", "admin", "admin/songs", "admin/songs/abc123", "songs/"],
)
def test_app_pages_are_routes(path: str) -> None:
    assert is_app_route(path)


@pytest.mark.parametrize(
    "path",
    ["wp-login.php", ".env", "login", "songs/abc/edit", "songs/../admin", "admin/../.env", "privacy.php", "rehearsals"],
)
def test_made_up_paths_are_not_routes(path: str) -> None:
    assert not is_app_route(path)


def test_invite_email_names_the_sender_and_gives_a_human_to_reply_to() -> None:
    msg = invite_message("DoNotReply@x.azurecomm.net", "https://hub.example", "jo@uni.ac.uk", "Jo", "Sam")
    text = msg["content"]["plainText"]
    assert msg["replyTo"][0]["address"] == SOCIETY_CONTACT
    assert "Sam" in msg["content"]["subject"] and "Barbershop Singing Society" in msg["content"]["subject"]
    assert "https://hub.example" in text and "jo@uni.ac.uk" in text
    assert "password" not in text.lower()
