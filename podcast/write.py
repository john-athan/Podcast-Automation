"""Write the bulletin.

The LLM writes only the editorial content (greeting, headline teasers, story
reads). The markets brief and the Munich weather are assembled deterministically
from the real figures, so those numbers are always exact and never hallucinated.
"""
from __future__ import annotations

from datetime import date

from .config import ANCHOR, PATHS, WEATHER
from .llm import structured
from .models import Article, Curation, MarketQuote, Script, Turn, Weather

SYSTEM = f"""You write an evening TV news bulletin in the style of Tagesschau:
authoritative, concise, neutral, factual. A single anchor reads everything.

Every turn's speaker must be exactly "{ANCHOR.name}".

Produce, in order:
1. A one-sentence formal greeting that states today's date.
2. A short "Our top stories tonight" headline teaser — one clause per story.
3. EVERY story, each as its own turn, 2-4 tight sentences: lead with the news,
   then the key facts and consequence. You MUST write one turn for every story in
   the briefs — do not stop early, do not merge stories. Neutral register.

Do NOT write a markets segment, a weather segment, or a sign-off — those are
added separately.

STRICT FACT RULES:
- Use ONLY facts stated in the provided story briefs.
- Do NOT invent numbers, names, causes, or implications not in the source text.
- If a brief is thin, keep that story to a single sentence rather than padding.
- No banter, no opinion, no stage directions, no markdown.

SPOKEN-NUMBER RULES (this is read aloud):
- Round money to a natural spoken amount: "about 5.3 million dollars", never exact
  cents or long figures like 5,288,398.45.
- Write symbols as words: "dollars", "percent", "and" — never $, %, &.
- Avoid quoting on-screen graphics or slogans verbatim if they contain odd
  punctuation; describe them instead."""


def build_brief(curation: Curation, articles: list[Article]) -> str:
    by_title = {a.title: a for a in articles}
    n = sum(1 for p in curation.picks if p.title in by_title)
    parts = [f"TODAY: {date.today():%A, %B %d, %Y}", "",
             f"Write one story turn for EACH of these {n} stories (priority order):"]
    for i, p in enumerate(curation.picks, 1):
        art = by_title.get(p.title)
        if art:
            parts.append(f"\n[{i}] ({art.domain}) {art.title}\n{art.content[:2500]}")
    return "\n".join(parts)


def generate_news(curation: Curation, articles: list[Article]) -> tuple[Script, str]:
    print("Writing bulletin...")
    brief = build_brief(curation, articles)
    script = structured(SYSTEM, brief, Script, temperature=0.6)
    for t in script.turns:
        t.speaker = ANCHOR.name  # anchor-only section
    PATHS.script.write_text(script.model_dump_json(indent=2))
    words = sum(len(t.text.split()) for t in script.turns)
    print(f"  {len(script.turns)} news turns, ~{words} words")
    return script, brief


# --- deterministic segments -------------------------------------------------
def _markets_turn(quotes: list[MarketQuote]) -> Turn | None:
    if not quotes:
        return None
    bits = []
    for q in quotes:
        price = f"{q.price:,.2f}".rstrip("0").rstrip(".") if q.price < 100 else f"{q.price:,.0f}"
        if abs(q.change_pct) < 0.05:
            bits.append(f"{q.label} was little changed at {price}")
        else:
            dir_ = "up" if q.change_pct > 0 else "down"
            bits.append(f"{q.label} closed {dir_} {abs(q.change_pct):.1f} percent at {price}")
    return Turn(speaker=ANCHOR.name, text="Now to the markets. " + ". ".join(
        b[0].upper() + b[1:] for b in bits) + ".")


def _weather_turn(w: Weather | None) -> Turn | None:
    if not w:
        return None
    return Turn(speaker=WEATHER.name, text=(
        f"And now the weather in {w.city}. It is currently "
        f"{w.now_c:.0f} degrees with {w.conditions}. "
        f"Today's high is {w.high_c:.0f} degrees, the low {w.low_c:.0f}, "
        f"with winds around {w.wind_kmh:.0f} kilometers per hour."
    ))


def assemble(news: Script, quotes: list[MarketQuote], weather: Weather | None) -> Script:
    turns = list(news.turns)
    for extra in (_markets_turn(quotes), _weather_turn(weather)):
        if extra:
            turns.append(extra)
    turns.append(Turn(speaker=ANCHOR.name, text="That is tonight's bulletin. Good night."))
    final = Script(turns=turns)
    PATHS.script.write_text(final.model_dump_json(indent=2))
    words = sum(len(t.text.split()) for t in final.turns)
    print(f"  bulletin: {len(final.turns)} turns, ~{words} words (~{words/150:.1f} min)")
    return final


if __name__ == "__main__":
    from .curate import curate
    from .extras import fetch_markets, fetch_weather
    from .verify import fact_check
    cur, arts = curate()
    news, brief = generate_news(cur, arts)
    news = fact_check(news, brief)
    final = assemble(news, fetch_markets(), fetch_weather())
    for t in final.turns:
        print(f"{t.speaker}: {t.text}")
