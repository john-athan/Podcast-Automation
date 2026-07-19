"""Integration test: drive the REAL pipeline.run() orchestration with the stage
functions monkeypatched to fast fakes (no LM Studio / MLX needed). Verifies the
event stream, stage ordering, and that the console's output artifacts are
persisted (draft.json, stories.json, factcheck.json, extras.json, script.json).

Run:  .venv/bin/python scripts/test_pipeline_events.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast import config, curate, extras, hydrate, ingest, llm, pipeline, publish, synth, verify, write
from podcast.events import STAGE_KEYS
from podcast.models import Article, Curation, MarketQuote, Script, Selection, Turn, Weather


def _fake_articles():
    return [
        Article(domain="tech", title="Chip node delays to Q1", content="A chipmaker said its two nanometer node slipped to the first quarter, citing yield problems at its lead fab. Analysts see a rare opening for rivals.", link="https://arstechnica.com/chip"),
        Article(domain="business", title="ECB holds rates steady", content="Investors positioned ahead of the central bank meeting; most economists expect no change. Markets see rates on hold.", link="https://marketwatch.com/ecb"),
        Article(domain="science", title="Nearest rogue planet found", content="Astronomers reported the nearest free floating planet yet, about twenty light years away, spotted via gravitational microlensing.", link="https://newscientist.com/rogue"),
    ]


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    config.PATHS.out = tmp  # redirect all output to a scratch dir

    arts = _fake_articles()
    picks = [Selection(domain=a.domain, title=a.title, reason="newsworthy") for a in arts]

    # --- monkeypatch every stage to a deterministic fake -------------------
    ingest.fetch_content = lambda: arts
    pipeline.fetch_content = ingest.fetch_content
    curate.curate = lambda articles=None, emit=None: (Curation(picks=picks), arts)
    pipeline.curate = curate.curate
    hydrate.hydrate = lambda a: a
    pipeline.hydrate = hydrate.hydrate

    # write.generate_news: real persist_stories + a canned draft (with an
    # unsupported claim we expect verify to strike).
    def fake_generate_news(curation, articles, emit=None):
        write.persist_stories(curation, articles)
        draft = Script(turns=[
            Turn(speaker="Anchor", text="Good evening. It is Sunday."),
            Turn(speaker="Anchor", text="Our top stories tonight: chips, rates, and a rogue planet."),
            Turn(speaker="Anchor", text="A chipmaker said its two nanometer node slipped to the first quarter."),
            Turn(speaker="Anchor", text="Investors expect no change. A fifty basis point cut is fully priced in."),
            Turn(speaker="Anchor", text="Astronomers reported the nearest free floating planet yet."),
        ])
        config.PATHS.script.write_text(draft.model_dump_json(indent=2))
        return draft, "BRIEF"
    write.generate_news = fake_generate_news
    pipeline.generate_news = write.generate_news

    # verify.fact_check: real function, but stub the LLM call it depends on.
    from podcast.models import FactCheck
    def fake_structured(system, user, schema, temperature=0.7, max_tokens=8192):
        return FactCheck(
            turns=[
                Turn(speaker="Anchor", text="Good evening. It is Sunday."),
                Turn(speaker="Anchor", text="Our top stories tonight: chips, rates, and a rogue planet."),
                Turn(speaker="Anchor", text="A chipmaker said its two nanometer node slipped to the first quarter."),
                Turn(speaker="Anchor", text="Investors expect no change."),
                Turn(speaker="Anchor", text="Astronomers reported the nearest free floating planet yet."),
            ],
            removed=["Cut 'fifty basis point cut is fully priced in' - source says rates on hold."],
        )
    verify.structured = fake_structured
    pipeline.fact_check = verify.fact_check  # real, uses patched structured

    extras.fetch_markets = lambda: [MarketQuote(label="the DAX", price=18412.6, change_pct=0.62)]
    extras.fetch_weather = lambda: Weather(city="Munich", now_c=16, high_c=24, low_c=13, conditions="partly cloudy", wind_kmh=11)
    pipeline.fetch_markets = extras.fetch_markets
    pipeline.fetch_weather = extras.fetch_weather

    llm.unload_all = lambda: None
    pipeline.unload_all = llm.unload_all

    def fake_generate_audio(script=None, emit=None):
        if emit:
            emit({"type": "substage", "key": "synth", "message": "voicing 8 turns", "i": 8, "n": 8})
        import numpy as np
        import soundfile as sf
        sf.write(str(config.PATHS.audio), np.zeros(24000, dtype="float32"), 24000)
        return config.PATHS.audio
    synth.generate_audio = fake_generate_audio
    pipeline.generate_audio = synth.generate_audio
    publish.publish = lambda: print("Publish skipped.")
    pipeline.publish = publish.publish

    # --- run with a capturing emitter --------------------------------------
    events: list[dict] = []
    pipeline.run(emit=events.append)

    # --- assertions --------------------------------------------------------
    stage_done = [e["key"] for e in events if e["type"] == "stage" and e["status"] == "done"]
    assert stage_done == STAGE_KEYS, f"stage order/done mismatch: {stage_done}"

    subs = [e for e in events if e["type"] == "substage"]
    assert any(e["key"] == "verify" and "cut" in e["message"] for e in subs), "no verify substage"
    assert any(e["key"] == "synth" for e in subs), "no synth substage"

    arts_written = [e["which"] for e in events if e["type"] == "artifact"]
    for w in ("curation", "stories", "factcheck", "script", "audio"):
        assert w in arts_written, f"missing artifact event: {w}"

    for f in (config.PATHS.stories, config.PATHS.draft, config.PATHS.factcheck,
              config.PATHS.extras, config.PATHS.script, config.PATHS.audio):
        assert f.exists(), f"missing output file: {f.name}"

    # the fact-check must have persisted the removal note + a draft to diff from
    import json
    fc = json.loads(config.PATHS.factcheck.read_text())
    assert fc["removed"], "factcheck removed notes empty"
    draft = json.loads(config.PATHS.draft.read_text())
    assert len(draft["turns"]) == 5, "draft not snapshotted"

    # now exercise the state builder end-to-end on these artifacts
    from podcast.web import state
    saved = config.PATHS.out
    st = state.build_state()
    cut_segs = [s for s in st["segments"] if s["cut_count"] > 0]
    assert cut_segs, "state builder found no struck-out claims"
    assert any(s["source"] for s in st["segments"] if s["kind"] == "story"), "no story sources"

    print(f"stages done: {stage_done}")
    print(f"artifacts:   {arts_written}")
    print(f"substages:   {[e['message'] for e in subs]}")
    print(f"struck segment: idx={cut_segs[0]['index']} cut_count={cut_segs[0]['cut_count']}"
          f" diff_cut='{' '.join(s['text'] for s in cut_segs[0]['diff'] if s['cut'])}'")
    print(f"notes on segment: {cut_segs[0]['notes']}")
    print("\nALL PIPELINE-EVENT ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
