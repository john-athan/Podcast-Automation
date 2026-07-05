"""VibeVoice (MLX) turn-by-turn synthesis -> single loudness-normalized WAV."""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import time

import numpy as np
import soundfile as sf

from .config import (HOSTS, LUFS_TARGET, PATHS, SAMPLE_RATE, TTS_CFG_SCALE,
                     TTS_DDPM_STEPS, TTS_MODEL)
from .models import Script


def sanitize_for_tts(text: str) -> str:
    """Make text speak cleanly: expand symbols, drop extraction artifacts.

    VibeVoice mangles bare symbols (& $ %) and stray glyphs. Whisper diff traced
    the 'JUST&T' garble and the mangled dollar figure here.
    """
    t = text
    t = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)\s*(million|billion|trillion)",
               r"\1 \2 dollars", t, flags=re.I)   # $5.28 million -> 5.28 million dollars
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


def _loudnorm(path) -> None:
    """Normalize to broadcast loudness if ffmpeg is available."""
    if not shutil.which("ffmpeg"):
        return
    tmp = path.with_suffix(".norm.wav")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path),
         "-af", f"loudnorm=I={LUFS_TARGET}:TP=-1.5:LRA=11",
         "-ar", str(SAMPLE_RATE), str(tmp)],
        check=False, capture_output=True,
    )
    if tmp.exists():
        tmp.replace(path)


def generate_audio(script: Script | None = None):
    if script is None:
        script = Script.model_validate_json(PATHS.script.read_text())

    # Import here so the heavy MLX load happens only after the LLM is unloaded.
    from mlx_audio.tts.utils import load_model

    print(f"Loading {TTS_MODEL} ...")
    model = load_model(TTS_MODEL)

    print(f"Synthesizing {len(script.turns)} turns...")
    t0 = time.perf_counter()
    segments: list[np.ndarray] = []
    for i, turn in enumerate(script.turns):
        host = HOSTS[turn.speaker]
        print(f"  {i + 1}/{len(script.turns)} {host.name}")
        # One turn at a time so each host's tempo can be applied to its own audio.
        parts = [
            np.asarray(r.audio)
            for r in model.generate(
                text=[sanitize_for_tts(turn.text)], voice=[host.voice],
                cfg_scale=TTS_CFG_SCALE, ddpm_steps=TTS_DDPM_STEPS,
                max_tokens=1200, verbose=False,
            )
        ]
        segments.append(_atempo(np.concatenate(parts), host.speed))

    audio = np.concatenate(segments) if segments else np.zeros(1, dtype=np.float32)
    PATHS.ensure()
    sf.write(str(PATHS.audio), audio, SAMPLE_RATE)
    _loudnorm(PATHS.audio)

    dur = len(audio) / SAMPLE_RATE
    el = time.perf_counter() - t0
    print(f"  {dur:.1f}s audio in {el:.1f}s ({el/dur:.2f}x RT) -> {PATHS.audio}")
    return PATHS.audio


if __name__ == "__main__":
    generate_audio()
