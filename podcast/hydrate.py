"""Fetch FULL article text for the curated picks (fixes thin-RSS hallucination).

RSS summaries are often one sentence; the writer then invents to fill airtime.
We pull the real page and extract readable text with trafilatura.
"""
from __future__ import annotations

import asyncio

import httpx
import trafilatura

from .models import Article

_UA = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_CHARS = 4000


async def _hydrate_one(client: httpx.AsyncClient, art: Article) -> Article:
    if not art.link:
        return art
    try:
        resp = await client.get(art.link, timeout=20.0, follow_redirects=True)
        resp.raise_for_status()
        full = trafilatura.extract(resp.text, include_comments=False,
                                   include_tables=False)
    except Exception as exc:
        print(f"  ! full text failed ({art.title[:40]}...): {exc}")
        return art
    if full and len(full) > len(art.content):
        art = art.model_copy(update={"content": full[:MAX_CHARS]})
    return art


async def _gather(articles: list[Article]) -> list[Article]:
    async with httpx.AsyncClient(headers=_UA) as client:
        return await asyncio.gather(*(_hydrate_one(client, a) for a in articles))


def hydrate(articles: list[Article]) -> list[Article]:
    print(f"Fetching full text for {len(articles)} stories...")
    out = asyncio.run(_gather(articles))
    gained = sum(len(o.content) - len(a.content) for a, o in zip(articles, out))
    print(f"  +{gained} chars of real article text")
    return out
