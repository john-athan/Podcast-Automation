"""A host carries two separate numbers: Kokoro's own generation speed and a
post-synthesis tempo, applied only when it differs from 1.0. This checks the
shipped defaults (each voice at the pacing it was approved at: Heart as anchor
at native speed with a tempo bump, Michael as weather at a faster native speed
with no atempo pass) and _atempo's no-op guard.

    uv run python tests/test_host_speed.py
"""
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.config import ANCHOR, WEATHER
from podcast.synth import _atempo

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


check("the anchor is Heart", ANCHOR.voice == "af_heart")
check("anchor runs at Kokoro's native speed", ANCHOR.speed == 1.0)
check("anchor keeps the post-synthesis tempo bump", ANCHOR.tempo == 1.10)
check("the weather is Michael", WEATHER.voice == "am_michael")
check("weather speed is Kokoro's own pacing knob, not a post-synthesis stretch",
      WEATHER.speed == 1.10)
check("weather tempo is 1.0: no atempo pass over the weather's audio",
      WEATHER.tempo == 1.0)

audio = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
check("_atempo is a no-op at the weather's tempo (1.0), same array back",
      _atempo(audio, WEATHER.tempo) is audio)

if shutil.which("ffmpeg"):
    check("_atempo does not no-op at the anchor's tempo (1.10)",
          _atempo(audio, ANCHOR.tempo) is not audio)
else:
    print("\nffmpeg not on PATH, skipping the anchor-tempo end-to-end check")

print(f"\n{checks} checks passed")
