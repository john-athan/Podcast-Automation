"""Local LM Studio client + memory management.

Structured output via json_schema. The writer model is loaded on demand
(LM Studio JIT) and can be unloaded to free RAM before TTS runs.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

from .config import LMSTUDIO_API_TOKEN, LMSTUDIO_BASE_URL, WRITER_MODEL

T = TypeVar("T", bound=BaseModel)

_client = OpenAI(base_url=LMSTUDIO_BASE_URL, api_key=LMSTUDIO_API_TOKEN)
_LMS = shutil.which("lms") or f"{__import__('os').path.expanduser('~')}/.lmstudio/bin/lms"


def structured(system: str, user: str, schema: Type[T],
               temperature: float = 0.7, max_tokens: int = 8192) -> T:
    """One structured-output chat call, validated into `schema`.

    max_tokens is generous by default: the writer is a reasoning model, so the
    thinking tokens plus the full JSON output need headroom or the list truncates.
    """
    resp = _client.chat.completions.create(
        model=WRITER_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__.lower(),
                "strict": True,
                "schema": schema.model_json_schema(),
            },
        },
        temperature=temperature,
        max_tokens=max_tokens,
    )
    msg = resp.choices[0].message
    # Reasoning models (qwen3.5, ...) may emit the JSON into reasoning_content
    # with an empty `content`. Take whichever channel holds the payload.
    raw = (msg.content or "").strip() or (getattr(msg, "reasoning_content", "") or "").strip()
    raw = _extract_json(raw)
    return schema.model_validate_json(raw)


def _extract_json(text: str) -> str:
    """Strip markdown fences / prose and return the outermost JSON object."""
    if "```" in text:
        text = text.split("```", 2)[1].removeprefix("json").strip() if text.count("```") >= 2 else text
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"


def embed(texts: list[str]) -> list[list[float]]:
    """Local embeddings (for semantic dedup). Empty list on failure."""
    try:
        resp = _client.embeddings.create(model=EMBED_MODEL, input=texts)
        return [d.embedding for d in resp.data]
    except Exception:
        return []


def unload_all() -> None:
    """Free VRAM/RAM so VibeVoice has room. Best-effort."""
    try:
        subprocess.run([_LMS, "unload", "--all"], check=False,
                       capture_output=True, timeout=30)
    except Exception:
        pass
