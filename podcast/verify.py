"""Fact-check pass: audit the draft bulletin against the source briefs and
strip or correct any claim the sources don't support (anti-fabrication guard)."""
from __future__ import annotations

from .config import ANCHOR, PATHS, WEATHER
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


def fact_check(script: Script, brief: str) -> Script:
    print("Fact-checking against sources...")
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
    else:
        print("  no unsupported claims found")

    PATHS.script.write_text(corrected.model_dump_json(indent=2))
    return corrected
