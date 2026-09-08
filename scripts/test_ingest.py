"""Offline test of RSS entry parsing: a malformed feed entry must not crash
the whole feed. No network, no credentials.

Run:  .venv/bin/python scripts/test_ingest.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.ingest import _parse_entry


def main() -> int:
    # normal case: feedparser sets "content" to a non-empty list
    a = _parse_entry("tech", {"title": "A", "content": [{"value": "body"}], "link": "http://x"})
    assert a.content == "body", a.content

    # no "content" key at all -> falls back to the summary
    b = _parse_entry("tech", {"title": "B", "summary": "sum", "link": "http://y"})
    assert b.content == "sum", b.content

    # "content" present but an empty list: this used to raise IndexError and
    # take the entire feed down with it.
    c = _parse_entry("tech", {"title": "C", "content": [], "summary": "sum3", "link": "http://z"})
    assert c.content == "sum3", c.content

    print("ALL INGEST ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
