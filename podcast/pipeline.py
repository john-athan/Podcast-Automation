"""End-to-end orchestrator. Stages run sequentially; the LLM is unloaded
before TTS so VibeVoice has room on a 24GB machine."""
from __future__ import annotations

import time

from .config import PATHS
from .curate import curate
from .extras import fetch_markets, fetch_weather
from .hydrate import hydrate
from .ingest import fetch_content
from .llm import unload_all
from .publish import publish
from .synth import generate_audio
from .verify import fact_check
from .write import assemble, generate_news


def run() -> None:
    t0 = time.perf_counter()
    PATHS.ensure()

    articles = fetch_content()
    curation, chosen = curate(articles)
    chosen = hydrate(chosen)              # full article text for the picks
    news, brief = generate_news(curation, chosen)
    news = fact_check(news, brief)        # strip unsupported claims (news only)
    script = assemble(news, fetch_markets(), fetch_weather())  # exact markets + weather

    unload_all()  # free RAM: writer model out, TTS model in
    generate_audio(script)

    publish()
    print(f"\nDone in {time.perf_counter() - t0:.0f}s -> {PATHS.audio}")


def main() -> None:  # console-script entrypoint
    run()


if __name__ == "__main__":
    main()
