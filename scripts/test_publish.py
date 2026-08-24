"""Offline test of the Drive publish path: no credentials, no network.

The upload itself can only be proven against a real Google account, so this
covers everything up to the API call instead: what gets sent, what comes back,
and that nothing reaches Google unless it is meant to. It exists because the
PyDrive2 -> google-api-python-client migration was made without an account to
test against, and this is the part of it that can be checked.

Run:  .venv/bin/python scripts/test_publish.py
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast import publish as P


def _fake_service(response: dict) -> tuple[MagicMock, dict]:
    """A stand-in Drive service that records the create() call it was given."""
    seen: dict = {}

    def create(body, media_body, fields):
        seen["body"], seen["fields"] = body, fields
        call = MagicMock()
        call.execute.return_value = response
        return call

    svc = MagicMock()
    svc.files.return_value.create.side_effect = create
    return svc, seen


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="publish-test-"))
    audio = tmp / "episode.wav"
    audio.write_bytes(b"RIFF" + b"\0" * 64)

    full = {"id": "FILEID123", "webViewLink": "https://drive.google.com/file/d/FILEID123/view"}

    # A shareable URL, not the bare file id the legacy code put in the email.
    svc, seen = _fake_service(full)
    with patch.object(P, "_drive", return_value=svc):
        os.environ.pop("GDRIVE_FOLDER_ID", None)
        links = P.upload_to_drive(audio)
    assert links["episode.wav"] == full["webViewLink"], links
    assert seen["fields"] == "id, webViewLink", seen["fields"]
    assert "parents" not in seen["body"], seen["body"]

    # An unset folder means My Drive root; a set one must be passed as parents.
    svc, seen = _fake_service(full)
    with patch.object(P, "_drive", return_value=svc), \
         patch.dict(os.environ, {"GDRIVE_FOLDER_ID": "FOLDER9"}):
        P.upload_to_drive(audio)
    assert seen["body"]["parents"] == ["FOLDER9"], seen["body"]

    # webViewLink is documented but not guaranteed, so the id fallback must hold.
    svc, _ = _fake_service({"id": "BARE1"})
    with patch.object(P, "_drive", return_value=svc):
        links = P.upload_to_drive(audio)
    assert links["episode.wav"] == "https://drive.google.com/file/d/BARE1/view", links

    # Without PUBLISH=1 nothing may touch Google at all.
    with patch.dict(os.environ, {"PUBLISH": "0"}), \
         patch.object(P, "upload_to_drive", side_effect=AssertionError("uploaded anyway")):
        P.publish()

    token = tmp / "token.json"
    token.write_text("{}")

    # A still-valid cached token must not reopen the browser.
    valid = MagicMock(valid=True)
    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=valid):
        P._TOKEN_FILE = token
        assert P._credentials() is valid

    # An expired one refreshes in place, and the rewritten token stays 0600:
    # it is a live credential.
    expired = MagicMock(valid=False, expired=True, refresh_token="rt")
    expired.to_json.return_value = json.dumps({"token": "new"})
    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=expired), \
         patch("google.auth.transport.requests.Request"):
        P._TOKEN_FILE = token
        P._credentials()
    assert expired.refresh.called, "expired token was not refreshed"
    assert json.loads(token.read_text())["token"] == "new"
    mode = stat.S_IMODE(token.stat().st_mode)
    assert mode == 0o600, f"token mode {oct(mode)}, expected 0o600"

    # Missing client secrets should say what to do, not raise from deep in the flow.
    P._TOKEN_FILE = tmp / "no-token.json"
    P._CLIENT_SECRETS = tmp / "no-secrets.json"
    try:
        P._credentials()
    except FileNotFoundError as exc:
        assert "Desktop app" in str(exc), str(exc)
    else:
        raise AssertionError("missing client_secrets did not raise")

    print("\nALL PUBLISH ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
