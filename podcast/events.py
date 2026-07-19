"""Progress events for the pipeline.

The CLI ignores these (default emitter is a no-op); the web console threads a
real emitter through so it can render live stage progress. Events are plain
dicts so they cross a multiprocessing.Queue to the web server unchanged.
"""
from __future__ import annotations

from typing import Callable

# Canonical pipeline stages: (key, label, one-line description).
# The web tally is built from this list, so order here is the order shown.
STAGES: list[tuple[str, str, str]] = [
    ("ingest",   "Ingest",   "RSS feeds fetched in parallel"),
    ("curate",   "Curate",   "dedup + LLM picks the lead stories"),
    ("hydrate",  "Hydrate",  "full article text (trafilatura)"),
    ("write",    "Write",    "LLM writes greeting, teasers, reads"),
    ("verify",   "Verify",   "fact-check every claim vs sources"),
    ("assemble", "Assemble", "markets + weather built from live data"),
    ("synth",    "Synth",    "VibeVoice MLX voices each turn"),
    ("publish",  "Publish",  "optional Drive upload + email"),
]
STAGE_KEYS = [k for k, _, _ in STAGES]

# An emitter takes one event dict and does something with it (queue it, print
# it, drop it). `noop` is the default so the CLI path stays untouched.
Emitter = Callable[[dict], None]


def noop(_event: dict) -> None:
    return None


def stage(key: str, status: str, *, detail: str | None = None,
          elapsed: float | None = None) -> dict:
    """A pipeline stage changed state: running | done | error | pending."""
    return {"type": "stage", "key": key, "status": status,
            "detail": detail, "elapsed": elapsed}


def substage(key: str, message: str, *, i: int | None = None,
             n: int | None = None) -> dict:
    """Fine-grained progress inside a stage (e.g. synth turn 6/9)."""
    return {"type": "substage", "key": key, "message": message, "i": i, "n": n}


def log(line: str) -> dict:
    """A human-readable log line for the console's log tail."""
    return {"type": "log", "line": line}


def artifact(which: str) -> dict:
    """An output file was (re)written; the UI should refetch it."""
    return {"type": "artifact", "which": which}
