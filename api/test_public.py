"""What strangers and scanners see: real 404s for made-up paths, an invite email that
doesn't read like phishing, and a manifest that lets members install the site."""

import json
import struct
from pathlib import Path

import pytest
from fastapi.responses import FileResponse

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


PUBLIC = Path(__file__).parent.parent / "app" / "public"


def png_size(path: Path) -> tuple[int, int]:
    width, height = struct.unpack(">II", path.read_bytes()[16:24])
    return width, height


def test_manifest_makes_the_site_installable() -> None:
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text())
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["short_name"] == "Rehearsal Hub"
    index = (PUBLIC.parent / "index.html").read_text()
    assert f'content="{manifest["description"]}"' in index
    assert '<link rel="manifest" href="/manifest.webmanifest" />' in index
    sizes = {icon["sizes"] for icon in manifest["icons"]}
    assert {"192x192", "500x500"} <= sizes
    for icon in manifest["icons"]:
        # The logo is never cropped, so no maskable icon.
        assert icon["purpose"] == "any"
        width, height = map(int, icon["sizes"].split("x"))
        assert png_size(PUBLIC / icon["src"].lstrip("/")) == (width, height)


def test_manifest_is_served_as_a_manifest() -> None:
    # Responses carry nosniff, so a wrong content type would stop the browser using it.
    assert FileResponse(PUBLIC / "manifest.webmanifest").media_type == "application/manifest+json"
