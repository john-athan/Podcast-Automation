"""End-to-end orchestrator. Stages run sequentially; the LLM is unloaded
before TTS so VibeVoice has room on a 24GB machine.

An optional `emit` callback receives progress events (see podcast.events). The
CLI passes the default no-op; the web console passes an emitter that streams
stage progress to the browser. Both drive the exact same stage functions.
"""
from __future__ import annotations

import time

from .config import PATHS
from .curate import curate
from .events import Emitter, artifact, noop, stage
from .extras import fetch_markets, fetch_weather
from .hydrate import hydrate
from .ingest import fetch_content
from .llm import unload_all
from .publish import publish
from .synth import generate_audio
from .verify import fact_check
from .write import assemble, generate_news


def run(emit: Emitter = noop) -> None:
    t0 = time.perf_counter()
    PATHS.ensure()

    def _stage(key: str, fn, detail_fn=None):
        emit(stage(key, "running"))
        s = time.perf_counter()
        try:
            result = fn()
        except Exception as exc:  # surface the failing stage, then re-raise
            emit(stage(key, "error", detail=str(exc)[:200],
                       elapsed=time.perf_counter() - s))
            raise
        emit(stage(key, "done",
                   detail=detail_fn(result) if detail_fn else None,
                   elapsed=time.perf_counter() - s))
        return result

    articles = _stage("ingest", fetch_content,
                      lambda a: f"{len(a)} items")
    curation, chosen = _stage("curate", lambda: curate(articles, emit),
                              lambda r: f"{len(r[0].picks)} picks")
    emit(artifact("curation"))
    emit(artifact("stories"))
    chosen = _stage("hydrate", lambda: hydrate(chosen),
                    lambda c: f"{sum(len(a.content.split()) for a in c)} words")
    news, brief = _stage("write", lambda: generate_news(curation, chosen, emit),
                         lambda r: f"{len(r[0].turns)} turns")
    news = _stage("verify", lambda: fact_check(news, brief, emit))
    emit(artifact("factcheck"))
    _stage("assemble",
           lambda: assemble(news, fetch_markets(), fetch_weather()),
           lambda s: f"{len(s.turns)} turns")
    emit(artifact("script"))

    unload_all()  # free RAM: writer model out, TTS model in

    script = None  # assemble() persisted script.json; synth reloads it
    _stage("synth", lambda: generate_audio(script, emit))
    emit(artifact("audio"))

    _stage("publish", publish)

    dt = time.perf_counter() - t0
    print(f"\nDone in {dt:.0f}s -> {PATHS.audio}")


def main() -> None:  # console-script entrypoint
    run()


if __name__ == "__main__":
    main()
