"""Optional distribution: Google Drive upload + email link.

Both are opt-in (env-gated) and fixed vs. the legacy code:
 - Drive auth is lazy (no browser popup on import).
 - email_link takes the real link (legacy called it with no args -> crash).
Not LLM/model related; pure file hosting + notification.
"""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from .config import PATHS


def _drive():
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    return GoogleDrive(gauth)


def upload_to_drive(*files: Path) -> dict[str, str]:
    drive = _drive()
    links: dict[str, str] = {}
    for fp in files:
        f = drive.CreateFile({"title": fp.name})
        f.SetContentFile(str(fp))
        f.Upload()
        links[fp.name] = f["id"]
        print(f"  uploaded {fp.name}: {f['id']}")
    return links


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
