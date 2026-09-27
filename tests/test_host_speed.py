"""A host carries two separate numbers now: Kokoro's own generation speed and
a post-synthesis tempo, applied only when it differs from 1.0. This checks
the shipped defaults (anchor: fast native speed, no atempo pass; weather:
native speed, atempo bump, matching the pre-Kokoro tempo) and _atempo's
no-op guard, which is what keeps the anchor untouched by ffmpeg.

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


check("anchor speed is Kokoro's own pacing knob, not a post-synthesis stretch",
      ANCHOR.speed == 1.10)
check("anchor tempo is 1.0: no atempo pass over the anchor's audio",
      ANCHOR.tempo == 1.0)
check("weather runs at Kokoro's native speed",
      WEATHER.speed == 1.0)
check("weather keeps the post-synthesis tempo bump",
      WEATHER.tempo == 1.10)

audio = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
check("_atempo is a no-op at the anchor's tempo (1.0), same array back",
      _atempo(audio, ANCHOR.tempo) is audio)

if shutil.which("ffmpeg"):
    check("_atempo does not no-op at the weather's tempo (1.10)",
          _atempo(audio, WEATHER.tempo) is not audio)
else:
    print("\nffmpeg not on PATH, skipping the weather-tempo end-to-end check")

print(f"\n{checks} checks passed")
