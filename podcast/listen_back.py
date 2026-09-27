"""Post-synthesis check: transcribe each turn's own audio back and diff it
against the text that was actually sent to the TTS, so a mispronunciation or a
dropped phrase shows up as a number instead of requiring someone to listen to
the whole bulletin by ear.

Runs after the TTS model is released (see synth.generate_audio): 24GB is
shared with everything else on this Mac, so the TTS and ASR models can't both
be resident.
"""
from __future__ import annotations

import json
import re
import time

import numpy as np

from .config import ASR_MODEL, LISTEN_BACK_WER_MAX, PATHS, SAMPLE_RATE
from .events import Emitter, noop, substage
from .models import Turn

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]
_SCALES = ["", "thousand", "million", "billion", "trillion"]


def _chunk_to_words(n: int) -> str:
    """Read a 0-999 chunk (NeMo/Whisper-style ASR emit numbers as spoken
    words, not digits, so the sent text's digits need the same treatment)."""
    words = []
    if n >= 100:
        words.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        if n % 10:
            words.append(_ONES[n % 10])
    elif n > 0:
        words.append(_ONES[n])
    return " ".join(words)


def _int_to_words(n: int) -> str:
    if n == 0:
        return "zero"
    parts = []
    scale = 0
    while n > 0:
        n, chunk = divmod(n, 1000)
        if chunk:
            piece = _chunk_to_words(chunk)
            if scale:
                piece += f" {_SCALES[scale]}"
            parts.append(piece)
        scale += 1
    return " ".join(reversed(parts))


def _num_to_words(token: str) -> str:
    """Spell out a decimal the way it would be spoken: whole part as a
    cardinal, fractional digits one at a time after 'point'."""
    token = token.replace(",", "")
    if "." in token:
        whole, frac = token.split(".", 1)
        whole_words = _int_to_words(int(whole)) if whole else "zero"
        frac_words = " ".join(_ONES[int(d)] for d in frac)
        return f"{whole_words} point {frac_words}"
    return _int_to_words(int(token))


_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize_for_wer(text: str) -> list[str]:
    """Lowercase, spell out digits, drop punctuation. Applied identically to
    the sent text and the transcript so '5.28' vs 'five point two eight'
    doesn't register as a wrong turn.
    """
    t = _NUMBER_RE.sub(lambda m: _num_to_words(m.group(0)), text.lower())
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return t.split()


def _align(ref: list[str], hyp: list[str]) -> list[dict]:
    """Levenshtein backtrace over words; returns only the differing ops so a
    report can show which words changed, not the whole alignment."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    ops: list[dict] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1]:
            i, j = i - 1, j - 1
            continue
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            ops.append({"op": "sub", "ref": ref[i - 1], "hyp": hyp[j - 1]})
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append({"op": "del", "ref": ref[i - 1], "hyp": None})
            i -= 1
        else:
            ops.append({"op": "ins", "ref": None, "hyp": hyp[j - 1]})
            j -= 1
    ops.reverse()
    return ops


def word_error_rate(ref: list[str], hyp: list[str]) -> tuple[float, list[dict]]:
    """Word-level WER (substitutions + deletions + insertions, over len(ref)),
    plus the alignment ops for the differing words. An empty reference has no
    rate to speak of; an empty hypothesis against a real reference is total
    loss, which falls out of the formula on its own.
    """
    ops = _align(ref, hyp)
    if not ref:
        return (0.0 if not hyp else 1.0), ops
    return len(ops) / len(ref), ops


def _load_asr_model():
    from mlx_audio.stt.utils import load_model
    return load_model(ASR_MODEL)


def run(segments: list[np.ndarray], turns: list[Turn], sent_texts: list[str],
        emit: Emitter = noop) -> list[dict]:
    """Transcribe each already-synthesized turn and diff it against what was
    sent to the TTS. Records a WER per turn; never re-synthesizes or stops
    the pipeline, that's a decision for later.
    """
    import mlx.core as mx
    from mlx_audio.stt.utils import resample_audio

    n = len(segments)
    print(f"Listening back to {n} turns ({ASR_MODEL.split('/')[-1]})...")
    emit(substage("synth", f"loading {ASR_MODEL.split('/')[-1]}"))
    model = _load_asr_model()
    target_sr = getattr(model.preprocessor_config, "sample_rate", 16_000)

    results: list[dict] = []
    t0 = time.perf_counter()
    for i, (seg, turn, sent) in enumerate(zip(segments, turns, sent_texts)):
        emit(substage("synth", f"listen-back, turn {i + 1}/{n}", i=i + 1, n=n))
        audio = resample_audio(np.asarray(seg, dtype=np.float32), SAMPLE_RATE, target_sr)
        transcript = model.generate(mx.array(audio, dtype=mx.float32)).text
        ref, hyp = normalize_for_wer(sent), normalize_for_wer(transcript)
        wer, ops = word_error_rate(ref, hyp)
        results.append({
            "index": i, "speaker": turn.speaker, "wer": round(wer, 4),
            "flagged": wer > LISTEN_BACK_WER_MAX,
            "sent_text": sent, "transcript": transcript,
            "differences": ops,
        })
    el = time.perf_counter() - t0

    flagged = sum(1 for r in results if r["flagged"])
    print(f"listen-back: {flagged} of {n} turns above {LISTEN_BACK_WER_MAX:.0%} WER "
          f"({el:.1f}s ASR)")

    PATHS.ensure()
    PATHS.listen_back.write_text(json.dumps(results, indent=2))
    return results
