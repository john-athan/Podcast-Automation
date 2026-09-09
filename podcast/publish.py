"""Optional distribution: Google Drive upload + email link.

Both are opt-in (env-gated) and fixed vs. the legacy code:
 - Drive auth is lazy (no browser popup on import).
 - email_link takes the real link (legacy called it with no args -> crash).
Not LLM/model related; pure file hosting + notification.

Uses the Google API client directly rather than PyDrive2. PyDrive2 1.21.3 (its
final release) caps `cryptography<44` and `pyopenssl<=24.2.1`, which are exactly
the versions carrying PYSEC-2026-1284/2141/35/3553/3554 and PYSEC-2026-2268/2269
(the last a 9.8). Those caps made the advisories unfixable by upgrading, so the
dependency had to go; without it cryptography resolves current and pyopenssl
drops out of the graph entirely.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .config import PATHS

# Only files this app itself creates, rather than PyDrive2's default of full
# read/write over the whole Drive. Uploading is all this module ever does.
_SCOPES = ["https://www.googleapis.com/auth/drive.file"]

_CLIENT_SECRETS = Path(os.getenv("GOOGLE_CLIENT_SECRETS", "client_secrets.json"))
_TOKEN_FILE = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))


def _credentials():
    """Cached OAuth credentials, running the installed-app flow only when needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if _TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_FILE), _SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not _CLIENT_SECRETS.exists():
            raise FileNotFoundError(
                f"{_CLIENT_SECRETS} not found. Download an OAuth client (type "
                '"Desktop app") from the Google Cloud console, or point '
                "GOOGLE_CLIENT_SECRETS at it."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(_CLIENT_SECRETS), _SCOPES)
        # port=0 lets the OS pick, so a stale redirect port cannot wedge the flow.
        creds = flow.run_local_server(port=0)

    # Persisting the refresh token is what keeps this to one browser prompt ever;
    # 0o600 because the file is a live credential.
    _TOKEN_FILE.write_text(creds.to_json())
    _TOKEN_FILE.chmod(0o600)
    return creds


def _drive():
    from googleapiclient.discovery import build

    # cache_discovery=False: the file cache needs oauth2client, which is not a
    # dependency here and only emits a warning when missing.
    return build("drive", "v3", credentials=_credentials(), cache_discovery=False)


def upload_to_drive(*files: Path) -> dict[str, str]:
    """Upload each file, returning {filename: shareable link}."""
    from googleapiclient.http import MediaFileUpload

    drive = _drive()
    folder = os.getenv("GDRIVE_FOLDER_ID")
    links: dict[str, str] = {}

    for fp in files:
        body: dict[str, object] = {"name": fp.name}
        if folder:
            body["parents"] = [folder]
        # resumable: episode audio is large enough that a plain upload is a
        # single point of failure on a flaky connection.
        media = MediaFileUpload(str(fp), resumable=True)
        created = (
            drive.files()
            .create(body=body, media_body=media, fields="id, webViewLink")
            .execute()
        )
        # webViewLink is what a human can actually open; the legacy code put the
        # bare file id into the email, which was never a link.
        link = created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view"
        links[fp.name] = link
        print(f"  uploaded {fp.name}: {link}")
        _share_with_recipient(drive, created["id"])
    return links


def _share_with_recipient(drive, file_id: str) -> None:
    """Let the person the link is emailed to actually open it.

    A file created by this app is private to the Drive account that uploaded it,
    so a `webViewLink` sent to anyone else opens a request-access page. The
    episode arrives as a link they cannot use, and nothing says why.

    Granted to the one address in RECIPIENT_EMAIL, as a reader, and not by
    making the file link-visible. "Anyone with the link" would fix the same
    symptom by publishing the episode to whoever ever sees the URL, which is a
    larger thing to do than the problem asks for.

    Fails soft: the upload has already succeeded by this point, and a sharing
    error is worth a line on the console rather than losing the episode. Sharing
    with the owner's own address is one of the errors it swallows.
    """
    recipient = os.getenv("RECIPIENT_EMAIL")
    if not recipient:
        return
    try:
        drive.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": "reader", "emailAddress": recipient},
            sendNotificationEmail=False,
        ).execute()
        print(f"  shared with {recipient}")
    except Exception as e:  # a sharing failure must not lose the upload
        print(f"  could not share with {recipient}: {e}")


def email_link(link: str) -> None:
    sender = os.getenv("EMAIL")
    recipient = os.getenv("RECIPIENT_EMAIL")
    if not (sender and recipient):
        print("  email skipped (EMAIL/RECIPIENT_EMAIL unset)")
        return
    msg = MIMEMultipart()
    msg["From"], msg["To"] = sender, recipient
    msg["Subject"] = "Your Podcast Episode is Ready"
    msg.attach(MIMEText(f"Here is your episode: {link}", "plain"))

    with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT", "587"))) as server:
        server.starttls()
        server.login(sender, os.getenv("PASSWORD"))
        server.sendmail(sender, recipient, msg.as_string())
    print(f"  emailed link to {recipient}")


def publish() -> None:
    """Run only if PUBLISH=1; otherwise it's a no-op."""
    if os.getenv("PUBLISH") != "1":
        print("Publish skipped (set PUBLISH=1 to upload + email).")
        return
    links = upload_to_drive(PATHS.audio, PATHS.script)
    email_link(links.get(PATHS.audio.name, ""))
