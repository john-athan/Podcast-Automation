"""Audio introspection for the console: duration, size, waveform peaks, and
measured loudness. All read the finished episode.wav; results are cached by
file mtime so the browser can poll cheaply."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from ..config import LUFS_TARGET, PATHS, SAMPLE_RATE

_WAVE_BUCKETS = 96
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, mtime: float, compute):
    hit = _cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    val = compute()
    _cache[key] = (mtime, val)
    return val


def audio_meta() -> dict:
    """Duration / size / sample rate / measured LUFS for episode.wav."""
    p: Path = PATHS.audio
    if not p.exists():
        return {"exists": False}
    st = p.stat()
    try:
        info = sf.info(str(p))
    except Exception:
        # A truncated/invalid WAV (e.g. synth killed mid-write) shouldn't 500.
        return {"exists": False, "error": "unreadable audio"}

    def compute():
        return {
            "exists": True,
            "duration_s": round(info.duration, 2),
            "size_bytes": st.st_size,
            "samplerate": info.samplerate,
            "channels": info.channels,
            "mtime": st.st_mtime,
            "lufs_target": LUFS_TARGET,
            "lufs_measured": _measure_lufs(p),
        }

    return _cached("meta", st.st_mtime, compute)


def waveform() -> list[float]:
    """Downsample the episode to `_WAVE_BUCKETS` peak magnitudes in [0, 1]."""
    p: Path = PATHS.audio
    if not p.exists():
        return []
    mtime = p.stat().st_mtime

    def compute():
        try:
            data, _ = sf.read(str(p), dtype="float32")
        except Exception:
            return []
        if data.ndim > 1:
            data = data.mean(axis=1)
        if len(data) == 0:
            return []
        # RMS energy per bucket -> a speech envelope that actually varies
        # (peak-per-bucket saturates near full scale on every chunk).
        buckets = np.array_split(data, _WAVE_BUCKETS)
        rms = np.array([float(np.sqrt(np.mean(b ** 2))) if b.size else 0.0
                        for b in buckets])
        top = rms.max() or 1.0
        return [round(float(v / top), 3) for v in rms]

    return _cached("wave", mtime, compute)


def _measure_lufs(path: Path) -> float | None:
    """Integrated loudness via ffmpeg's ebur128 filter (None if unavailable)."""
    if not shutil.which("ffmpeg"):
        return None
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
             "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    # The summary block prints "    I:         -15.9 LUFS"
    matches = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", proc.stderr)
    return float(matches[-1]) if matches else None
