"""Rank the fetched articles and pick the bulletin's stories (one LLM call).

Picks are fuzzy-matched back to real article titles so a slightly reworded
title still resolves instead of being silently dropped to a fallback.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

from .config import PATHS
from .llm import embed, structured
from .models import Article, Curation, Selection

DEDUP_THRESHOLD = 0.82  # cosine above this = same story from two feeds

TARGET_PICKS = 6
SYSTEM = f"""You are the editor of a serious evening news bulletin.
From an unordered list of news articles across tech, business, and science,
choose the {TARGET_PICKS} strongest lead stories for today.
Rules:
- Roughly balance the three domains.
- Order them most newsworthy first (hard news over novelty).
- Reference each article by its title from the input.
- Favor concrete facts, stakes, and consequence over quirky filler."""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _match(title: str, articles: list[Article]) -> Article | None:
    """Snap a possibly-reworded pick title to the closest real article."""
    nt = _norm(title)
    best, score = None, 0.0
    for a in articles:
        r = SequenceMatcher(None, nt, _norm(a.title)).ratio()
        if r > score:
            best, score = a, r
    return best if score >= 0.6 else None


def _dedupe(articles: list[Article]) -> list[Article]:
    """Drop near-duplicate stories (same event from two feeds) via embeddings."""
    vecs = embed([f"{a.title}. {a.content[:200]}" for a in articles])
    if len(vecs) != len(articles):
        return articles  # embedder unavailable -> skip
    import math
    def cos(u, v):
        d = sum(x * y for x, y in zip(u, v))
        nu = math.sqrt(sum(x * x for x in u)); nv = math.sqrt(sum(y * y for y in v))
        return d / (nu * nv) if nu and nv else 0.0
    kept: list[Article] = []
    kept_vecs: list[list[float]] = []
    for art, v in zip(articles, vecs):
        if any(cos(v, kv) >= DEDUP_THRESHOLD for kv in kept_vecs):
            continue
        kept.append(art); kept_vecs.append(v)
    if len(kept) < len(articles):
        print(f"  deduped {len(articles) - len(kept)} near-duplicate story(ies)")
    return kept


def curate(articles: list[Article] | None = None) -> tuple[Curation, list[Article]]:
    if articles is None:
        articles = [Article(**a) for a in json.loads(PATHS.content.read_text())]

    articles = _dedupe(articles)
    catalogue = "\n".join(f"[{a.domain}] {a.title}" for a in articles)
    raw = structured(SYSTEM, catalogue, Curation, temperature=0.4)

    picks: list[Selection] = []
    chosen: list[Article] = []
    seen: set[str] = set()
    for p in raw.picks:
        art = _match(p.title, articles)
        if art and art.title not in seen:
            seen.add(art.title)
            picks.append(Selection(domain=art.domain, title=art.title, reason=p.reason))
            chosen.append(art)

    # Top up to a full bulletin if the model under-picked.
    if len(chosen) < TARGET_PICKS:
        for a in _first_per_domain(articles):
            if a.title not in seen:
                seen.add(a.title)
                picks.append(Selection(domain=a.domain, title=a.title,
                                       reason="editor's balance pick"))
                chosen.append(a)

    curation = Curation(picks=picks[:TARGET_PICKS])
    chosen = chosen[:TARGET_PICKS]
    PATHS.ensure()
    PATHS.curation.write_text(curation.model_dump_json(indent=2))
    print(f"Curated {len(curation.picks)} stories")
    return curation, chosen


def _first_per_domain(articles: list[Article]) -> list[Article]:
    seen: dict[str, Article] = {}
    for a in articles:
        seen.setdefault(a.domain, a)
    return list(seen.values())


if __name__ == "__main__":
    cur, _ = curate()
    for p in cur.picks:
        print(f"- [{p.domain}] {p.title} :: {p.reason}")
