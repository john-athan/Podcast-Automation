"""The join between turns: real silence at the right length, no clicks.

Turn.speaker/text carry no segment type, so synth.py infers one from position
and content the same way write.py's assemble() built the script in the first
place. This checks that inference against a small synthetic bulletin, and
checks the fade only touches a boundary that was not already near zero.

    uv run python tests/test_synth_pauses.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.config import SAMPLE_RATE
from podcast.models import Turn
from podcast.synth import (
    FADE_MS,
    GAP_BEFORE_SIGNOFF_MS,
    GAP_SAME_KIND_MS,
    GAP_SECTION_CHANGE_MS,
    _fade_edges,
    _gap_ms,
    _turn_kind,
    join_turns,
)

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


# A small synthetic bulletin covering every segment kind synth.py recognizes:
# greeting, teaser, two stories, markets, weather, sign-off.
TURNS = [
    Turn(speaker="Anchor", text="Good evening."),
    Turn(speaker="Anchor", text="Our top stories tonight."),
    Turn(speaker="Anchor", text="Story one."),
    Turn(speaker="Anchor", text="Story two."),
    Turn(speaker="Anchor", text="Now to the markets. Stuff."),
    Turn(speaker="Weather", text="Weather stuff."),
    Turn(speaker="Anchor", text="That is tonight's bulletin. Good night."),
]
KINDS = ["greeting", "teaser", "story", "story", "markets", "weather", "sign_off"]

check("segment kinds are inferred in order",
      [_turn_kind(TURNS, i) for i in range(len(TURNS))] == KINDS)

check("story to story is the same-kind gap",
      _gap_ms("story", "story") == GAP_SAME_KIND_MS == 350)
check("teaser to story is a section change",
      _gap_ms("teaser", "story") == GAP_SECTION_CHANGE_MS == 600)
check("story to markets is a section change (markets doesn't fit the pair list, 600ms)",
      _gap_ms("story", "markets") == GAP_SECTION_CHANGE_MS)
check("anything into sign-off is the sign-off gap, even from the same kind",
      _gap_ms("sign_off", "sign_off") == GAP_BEFORE_SIGNOFF_MS == 800)

# Turns of equal length so the expected silence is the only length delta.
TURN_SAMPLES = 100
segments = [np.ones(TURN_SAMPLES, dtype=np.float32) * 0.5 for _ in TURNS]
out = join_turns(segments, TURNS)
expected_gap_samples = sum(
    int(SAMPLE_RATE * _gap_ms(KINDS[i], KINDS[i + 1]) / 1000)
    for i in range(len(TURNS) - 1)
)
expected_len = len(TURNS) * TURN_SAMPLES + expected_gap_samples
check("joined length is turns plus the expected gaps", len(out) == expected_len)

check("a single turn passes through untouched (no gap, no fade)",
      join_turns([segments[0]], [TURNS[0]]) is segments[0])

check("no turn added before the first or after the last",
      out[0] == segments[0][0] and out[-1] == segments[-1][-1])

# Fades: only touch a boundary that isn't already near zero.
fade_n = int(SAMPLE_RATE * FADE_MS / 1000)
loud = np.ones(TURN_SAMPLES, dtype=np.float32) * 0.8
already_quiet = np.concatenate(
    [np.zeros(5, dtype=np.float32), np.ones(TURN_SAMPLES - 10, dtype=np.float32) * 0.8,
     np.zeros(5, dtype=np.float32)]
)

faded = _fade_edges(loud, fade_in=True, fade_out=True)
check("a loud edge is faded to (near) zero",
      abs(faded[0]) < 1e-6 and abs(faded[-1]) < 1e-6)
check("the fade leaves the turn's middle alone",
      np.allclose(faded[fade_n:-fade_n], 0.8))

untouched = _fade_edges(already_quiet, fade_in=True, fade_out=True)
check("an edge already near zero is left alone, unchanged",
      np.array_equal(untouched, already_quiet))

print(f"\n{checks} checks passed")
