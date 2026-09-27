"""The writer retries an empty or near-empty draft and gives up loudly, and the
fact-check refuses an empty draft and keeps every turn on the anchor. The
model call is replaced by a stub, so no LLM is needed.

    uv run python tests/test_writer_guard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tempfile

from podcast import config, verify, write
from podcast.models import FactCheck, Script, Turn

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


def turns(n, speaker="Anchor"):
    return [Turn(speaker=speaker, text=f"Line {i}.") for i in range(n)]


def stub(replies):
    calls = []

    def structured(system, user, schema, **kw):
        calls.append(schema)
        return replies[len(calls) - 1]
    return structured, calls


config.PATHS.out = Path(tempfile.mkdtemp())  # both stages save their scripts
write.build_brief = lambda curation, articles: "brief"
write.persist_stories = lambda curation, articles: None

write.structured, calls = stub([Script(turns=[]), Script(turns=turns(5))])
script, _ = write.generate_news(None, [])
check("an empty draft is retried and the retry is used", len(calls) == 2 and len(script.turns) == 5)

write.structured, calls = stub([Script(turns=turns(1))] * write.WRITER_ATTEMPTS)
try:
    write.generate_news(None, [])
    gave_up = False
except RuntimeError:
    gave_up = True
check("after every attempt comes back short, the writer stops instead of continuing",
      gave_up and len(calls) == write.WRITER_ATTEMPTS)

try:
    verify.fact_check(Script(turns=[]), "brief")
    refused = False
except ValueError:
    refused = True
check("the fact-check refuses an empty draft", refused)

verify.structured, _ = stub([FactCheck(turns=turns(2) + turns(1, "Weather"), removed=[])])
out = verify.fact_check(Script(turns=turns(3)), "brief")
check("a Weather tag from the fact-check is put back on the anchor",
      [t.speaker for t in out.turns] == ["Anchor"] * 3)

print(f"\n{checks} checks passed")
