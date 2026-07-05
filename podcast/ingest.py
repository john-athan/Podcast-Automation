"""Fetch RSS feeds concurrently -> Article list."""
from __future__ import annotations

import asyncio
import json

import feedparser
import httpx

from .config import ENTRIES_PER_FEED, PATHS, RSS_FEEDS
from .models import Article


async def _fetch_feed(client: httpx.AsyncClient, domain: str, url: str) -> list[Article]:
    try:
        resp = await client.get(url, timeout=15.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:  # one dead feed shouldn't kill the run
        print(f"  ! skip {url}: {exc}")
        return []

    feed = feedparser.parse(resp.content)
    out: list[Article] = []
    for entry in feed.entries[:ENTRIES_PER_FEED]:
        body = entry.get("content", [{"value": entry.get("summary", "")}])[0]["value"]
        out.append(Article(
            domain=domain,
            title=entry.get("title", "").strip(),
            content=body,
            link=entry.get("link", ""),
        ))
    return out


async def _gather() -> list[Article]:
    headers = {"User-Agent": "podcast-automation/2.0 (+local)"}
    async with httpx.AsyncClient(headers=headers) as client:
        tasks = [
            _fetch_feed(client, domain, url)
            for domain, urls in RSS_FEEDS.items()
            for url in urls
        ]
        results = await asyncio.gather(*tasks)
    return [a for batch in results for a in batch if a.title]


def fetch_content() -> list[Article]:
    print("Fetching content (parallel)...")
    articles = asyncio.run(_gather())
    PATHS.ensure()
    PATHS.content.write_text(
        json.dumps([a.model_dump() for a in articles], indent=2)
    )
    print(f"  {len(articles)} articles from {sum(len(v) for v in RSS_FEEDS.values())} feeds")
    return articles


if __name__ == "__main__":
    for a in fetch_content():
        print(f"[{a.domain}] {a.title}")
