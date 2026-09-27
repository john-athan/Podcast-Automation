"""Two-pass loudnorm: the pass-1 parser against a real ffmpeg run, the error
path against garbage, and (if ffmpeg is on PATH) an end-to-end check that a
generated clip actually lands at the -16 LUFS / -1.5 dBTP target.

    uv run python tests/test_synth_loudnorm.py
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.config import SAMPLE_RATE
from podcast.synth import _loudnorm, parse_loudnorm_json

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


FIXTURE = Path(__file__).parent / "fixtures" / "loudnorm_pass1_stderr.txt"

data = parse_loudnorm_json(FIXTURE.read_text())
check("pass-1 JSON parses off a real captured ffmpeg stderr", data["input_i"] == "-21.75")
check("every field pass 2 needs is present",
      {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"} <= data.keys())

try:
    parse_loudnorm_json("ffmpeg printed nothing usable, no braces at all")
    raised = False
except ValueError as exc:
    raised = "no JSON block" in str(exc)
check("garbage output raises instead of silently skipping to a one-pass normalize", raised)

try:
    parse_loudnorm_json("here is { not: valid json at all }")
    raised = False
except ValueError:
    raised = True
check("a brace block that isn't valid JSON also raises", raised)

if not shutil.which("ffmpeg"):
    print("\nffmpeg not on PATH, skipping the end-to-end normalize check")
else:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "clip.wav"
        # Sine + noise: quiet single-tone sine alone can measure gate-limited
        # (LRA/threshold degenerate), so a bit of noise gives loudnorm real
        # dynamics to measure, closer to actual speech.
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=220:duration=10",
             "-f", "lavfi", "-i", "anoisesrc=duration=10:color=pink:amplitude=0.05",
             "-filter_complex", "amix=inputs=2:duration=first",
             "-ar", str(SAMPLE_RATE), str(wav)],
            check=True,
        )
        _loudnorm(wav)

        measured = parse_loudnorm_json(subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav),
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
             "-f", "null", "-"],
            capture_output=True, text=True, check=False,
        ).stderr)
        integrated = float(measured["input_i"])
        true_peak = float(measured["input_tp"])
        print(f"  measured: integrated {integrated:.2f} LUFS, true peak {true_peak:.2f} dBTP")
        check("integrated loudness lands within 0.5 LU of -16",
              abs(integrated - (-16.0)) <= 0.5)
        check("true peak stays at or below -1.5 dBTP", true_peak <= -1.5 + 0.1)

print(f"\n{checks} checks passed")
