"""Environment health for the console: is the local writer LLM (LM Studio)
reachable, is the writer model loaded, is ffmpeg present. Surfaced so the UI
can explain a failed run instead of showing a bare 'Connection error.'"""
from __future__ import annotations

import shutil

import httpx

from ..config import LMSTUDIO_API_TOKEN, LMSTUDIO_BASE_URL, WRITER_MODEL


def _writer_matches(model_id: str) -> bool:
    a = model_id.lower()
    b = WRITER_MODEL.lower()
    return a == b or b in a or a in b


def check() -> dict:
    """Probe LM Studio + ffmpeg. Fast (3s timeout), never raises."""
    lm: dict = {
        "url": LMSTUDIO_BASE_URL,
        "writer": WRITER_MODEL,
        "ok": False,
        "models": [],
        "writer_loaded": False,
        "error": None,
    }
    try:
        resp = httpx.get(
            LMSTUDIO_BASE_URL.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {LMSTUDIO_API_TOKEN}"},
            timeout=3.0,
        )
        resp.raise_for_status()
        ids = [m.get("id", "") for m in resp.json().get("data", [])]
        lm["ok"] = True
        lm["models"] = ids
        lm["writer_loaded"] = any(_writer_matches(i) for i in ids)
    except Exception as exc:  # unreachable, refused, timeout, bad status
        lm["error"] = f"{type(exc).__name__}"
    return {"lmstudio": lm, "ffmpeg": bool(shutil.which("ffmpeg"))}
