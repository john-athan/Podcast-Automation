"""Fact-check pass: audit the draft bulletin against the source briefs and
strip or correct any claim the sources don't support (anti-fabrication guard)."""
from __future__ import annotations

from .config import ANCHOR, PATHS, WEATHER
from .events import Emitter, noop, substage
from .llm import structured
from .models import FactCheck, Script

SYSTEM = f"""You are a strict fact-checker for a news bulletin.
You get the SOURCE MATERIAL and a DRAFT bulletin.

For every sentence in the draft, verify it against the source material:
- If a claim (a number, name, cause, effect, or fact) is NOT supported by the
  sources, delete that claim or rewrite the sentence to only what IS supported.
- Never add new facts. Never soften a correct fact.
- Keep the running order and the exact speaker tags ("{ANCHOR.name}"/"{WEATHER.name}").
- Weather and market figures are ground truth — keep them as given.

Return the corrected turns, plus a short note for each claim you removed or fixed."""


def fact_check(script: Script, brief: str, emit: Emitter = noop) -> Script:
    print("Fact-checking against sources...")
    # Snapshot the pre-check draft so the console can diff it against the
    # corrected turns and show exactly what was struck out, per story.
    PATHS.ensure()
    PATHS.draft.write_text(script.model_dump_json(indent=2))
    draft = "\n".join(f"{t.speaker}: {t.text}" for t in script.turns)
    result = structured(
        SYSTEM,
        f"SOURCE MATERIAL:\n{brief}\n\n---\n\nDRAFT BULLETIN:\n{draft}",
        FactCheck, temperature=0.1,
    )
    valid = {ANCHOR.name, WEATHER.name}
    for t in result.turns:
        if t.speaker not in valid:
            t.speaker = ANCHOR.name

    corrected = Script(turns=[t for t in result.turns if t.text.strip()])
    result.removed = [n for n in result.removed if n.strip().lower() not in ("none", "n/a", "")]
    if result.removed:
        print(f"  {len(result.removed)} claims cut/corrected:")
        for note in result.removed[:12]:
            print(f"    - {note}")
        emit(substage("verify", f"{len(result.removed)} claim(s) cut/corrected"))
    else:
        print("  no unsupported claims found")
        emit(substage("verify", "no unsupported claims found"))

    # Persist the corrected turns + the removal notes so the console can render
    # the fact-check outcome (chips, notes) without re-running the model.
    PATHS.factcheck.write_text(FactCheck(
        turns=corrected.turns, removed=result.removed).model_dump_json(indent=2))
    PATHS.script.write_text(corrected.model_dump_json(indent=2))
    return corrected
