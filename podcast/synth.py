"""VibeVoice (MLX) turn-by-turn synthesis -> single loudness-normalized WAV."""
from __future__ import annotations

import gc
import io
import json
import re
import shutil
import subprocess
import time

import numpy as np
import soundfile as sf

from . import listen_back
from .config import (
    HOSTS,
    LISTEN_BACK,
    LUFS_TARGET,
    MARKETS_LEAD,
    PATHS,
    SAMPLE_RATE,
    TTS_CFG_SCALE,
    TTS_DDPM_STEPS,
    TTS_MODEL,
    WEATHER,
)
from .events import Emitter, noop, substage
from .models import Script, Turn

# Pause between turns, tuned by ear. Turn.speaker/text carry no segment type
# (see models.Turn), so _turn_kind below infers one from position and content,
# the same signals write.py's assemble() used to build the script in the first
# place: greeting and teaser are always first, sign-off is always last, weather
# is the only Weather-voiced turn, and markets is the only turn built with
# MARKETS_LEAD. Everything else between the teaser and the closing segments is
# a story.
GAP_SAME_KIND_MS = 350     # story to story
GAP_SECTION_CHANGE_MS = 600  # greeting/teaser to first story, story to markets, markets to weather
GAP_BEFORE_SIGNOFF_MS = 800
FADE_MS = 10
# A turn already near zero at the boundary doesn't need a fade; forcing one
# in would just spend 10ms ramping silence into more silence.
FADE_SILENCE_THRESHOLD = 1e-3


def sanitize_for_tts(text: str) -> str:
    """Make text speak cleanly: expand symbols, drop extraction artifacts.

    VibeVoice mangles bare symbols (& $ %) and stray glyphs. Whisper diff traced
    the 'JUST&T' garble and the mangled dollar figure here.
    """
    t = text
    t = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion|trillion)",
               r"\1 \2 dollars", t, flags=re.IGNORECASE)   # $5.28 million -> 5.28 million dollars
    t = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)", r"\1 dollars", t)  # $1,000 -> 1,000 dollars
    t = t.replace("%", " percent")
    t = t.replace("&", " and ")
    t = t.replace("ppm", "parts per million")
    t = re.sub(r"[\"“”„'‘’()\[\]*_#]", " ", t)      # stray quotes/brackets/markdown
    t = re.sub(r"\s+([.,!?;:])", r"\1", t)           # tidy spacing before punctuation
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def _atempo(audio: np.ndarray, factor: float) -> np.ndarray:
    """Time-stretch a segment (pitch-preserving) via ffmpeg. No-op if ~1.0."""
    if abs(factor - 1.0) < 0.01 or not shutil.which("ffmpeg"):
        return audio
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-af", f"atempo={factor:.3f}", "-f", "wav", "pipe:1"],
        input=buf.getvalue(), capture_output=True, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return audio
    out, _ = sf.read(io.BytesIO(proc.stdout))
    return out.astype(np.float32)


def _turn_kind(turns: list[Turn], i: int) -> str:
    """Which segment turn i belongs to (see the module docstring above)."""
    if i == len(turns) - 1:
        return "sign_off"
    if i == 0:
        return "greeting"
    if i == 1:
        return "teaser"
    if turns[i].speaker == WEATHER.name:
        return "weather"
    if turns[i].text.startswith(MARKETS_LEAD):
        return "markets"
    return "story"


def _gap_ms(prev_kind: str, kind: str) -> int:
    """Pause length for the boundary into `kind`, coming from `prev_kind`."""
    if kind == "sign_off":
        return GAP_BEFORE_SIGNOFF_MS
    if kind == prev_kind:
        return GAP_SAME_KIND_MS
    return GAP_SECTION_CHANGE_MS


def _fade_edges(seg: np.ndarray, fade_in: bool, fade_out: bool) -> np.ndarray:
    """Ramp a turn's edges so the silence spliced in next to it doesn't click."""
    n = min(int(SAMPLE_RATE * FADE_MS / 1000), len(seg))
    if n <= 0:
        return seg
    out = seg.copy()
    if fade_in and abs(out[0]) > FADE_SILENCE_THRESHOLD:
        out[:n] *= np.linspace(0.0, 1.0, n, dtype=out.dtype)
    if fade_out and abs(out[-1]) > FADE_SILENCE_THRESHOLD:
        out[-n:] *= np.linspace(1.0, 0.0, n, dtype=out.dtype)
    return out


def join_turns(segments: list[np.ndarray], turns: list[Turn]) -> np.ndarray:
    """Concatenate turns with real silence between them, sized by section change.

    No pause before the first turn or after the last, so the only silence
    added beyond what synthesis produced is the inserted gaps.
    """
    if not segments:
        return np.zeros(1, dtype=np.float32)
    if len(segments) == 1:
        return segments[0]

    kinds = [_turn_kind(turns, i) for i in range(len(turns))]
    last = len(segments) - 1
    pieces: list[np.ndarray] = []
    for i, seg in enumerate(segments):
        pieces.append(_fade_edges(seg, fade_in=i > 0, fade_out=i < last))
        if i < last:
            gap_ms = _gap_ms(kinds[i], kinds[i + 1])
            pieces.append(np.zeros(int(SAMPLE_RATE * gap_ms / 1000), dtype=seg.dtype))
    return np.concatenate(pieces)


def _measure_loudness(path) -> dict[str, str]:
    """Pass 1: measure real input loudness so pass 2 can normalize with linear=true.

    Without measured_* values loudnorm falls back to a dynamic, per-frame
    estimate that can land a full LU or more off target; feeding its own
    measurement back in gets pass 2 within a fraction of a LU.
    """
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"loudnorm=I={LUFS_TARGET}:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, check=False, text=True,
    )
    return parse_loudnorm_json(proc.stderr)


def parse_loudnorm_json(stderr: str) -> dict[str, str]:
    """Pull loudnorm's JSON block out of ffmpeg's stderr.

    Split out from _measure_loudness so the parser is testable against a
    captured stderr fixture without running ffmpeg.
    """
    match = re.search(r"\{[^{}]*\}", stderr, re.DOTALL)
    if not match:
        tail = "\n".join(stderr.splitlines()[-20:])
        raise ValueError(f"loudnorm pass 1: no JSON block in ffmpeg output\n{tail}")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        tail = "\n".join(stderr.splitlines()[-20:])
        raise ValueError(f"loudnorm pass 1: unparseable JSON ({exc})\n{tail}") from exc


def _loudnorm(path) -> None:
    """Two-pass loudnorm to broadcast target, if ffmpeg is available."""
    if not shutil.which("ffmpeg"):
        return
    measured = _measure_loudness(path)
    tmp = path.with_suffix(".norm.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path),
         "-af", (f"loudnorm=I={LUFS_TARGET}:TP=-1.5:LRA=11:"
                 f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                 f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                 f"offset={measured['target_offset']}:linear=true:print_format=summary"),
         "-ar", str(SAMPLE_RATE), str(tmp)],
        check=False, capture_output=True,
    )
    if tmp.exists():
        tmp.replace(path)


def generate_audio(script: Script | None = None, emit: Emitter = noop):
    if script is None:
        script = Script.model_validate_json(PATHS.script.read_text())

    # Import here so the heavy MLX load happens only after the LLM is unloaded.
    from mlx_audio.tts.utils import load_model

    print(f"Loading {TTS_MODEL} ...")
    emit(substage("synth", f"loading {TTS_MODEL.split('/')[-1]}"))
    model = load_model(TTS_MODEL)

    n = len(script.turns)
    print(f"Synthesizing {n} turns...")
    emit(substage("synth", f"voicing {n} turns", i=0, n=n))
    t0 = time.perf_counter()
    segments: list[np.ndarray] = []
    sent_texts: list[str] = []
    for i, turn in enumerate(script.turns):
        host = HOSTS[turn.speaker]
        print(f"  {i + 1}/{len(script.turns)} {host.name}")
        emit(substage("synth", f"turn {i + 1}/{n} · {host.name}", i=i + 1, n=n))
        # One turn at a time so each host's tempo can be applied to its own audio.
        sent = sanitize_for_tts(turn.text)
        sent_texts.append(sent)
        parts = [
            np.asarray(r.audio)
            for r in model.generate(
                text=[sent], voice=[host.voice],
                cfg_scale=TTS_CFG_SCALE, ddpm_steps=TTS_DDPM_STEPS,
                max_tokens=1200, verbose=False,
            )
        ]
        segments.append(_atempo(np.concatenate(parts), host.speed))
    synth_elapsed = time.perf_counter() - t0

    if LISTEN_BACK:
        # Free the TTS model's weights before the ASR model loads; 24GB is
        # shared with everything else on this Mac (see listen_back module doc).
        del model
        gc.collect()
        try:
            import mlx.core as mx
            mx.clear_cache()
        except ImportError:
            pass
        listen_back.run(segments, script.turns, sent_texts, emit)

    audio = join_turns(segments, script.turns)
    PATHS.ensure()
    sf.write(str(PATHS.audio), audio, SAMPLE_RATE)
    _loudnorm(PATHS.audio)

    dur = len(audio) / SAMPLE_RATE
    print(f"  {dur:.1f}s audio in {synth_elapsed:.1f}s "
          f"({synth_elapsed/dur:.2f}x RT) -> {PATHS.audio}")
    return PATHS.audio


if __name__ == "__main__":
    generate_audio()
