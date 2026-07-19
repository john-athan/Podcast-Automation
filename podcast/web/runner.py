"""Child-process entry points for a pipeline run.

Each run executes in its own process (spawned) so that (a) the heavy MLX / LLM
memory is fully reclaimed when it exits, and (b) it reloads `.env`, so config
edits made in the console apply to the next run. Progress is pushed as event
dicts onto a multiprocessing.Queue the web server drains.
"""
from __future__ import annotations

import sys
import time
import traceback
from multiprocessing import Queue

from ..events import STAGE_KEYS, stage


class _LogTee:
    """Forward stdout lines to the event queue (and the real stdout too)."""

    def __init__(self, queue: "Queue", stream):
        self.queue, self.stream, self._buf = queue, stream, ""

    def write(self, s: str) -> int:
        self.stream.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.queue.put({"type": "log", "line": line.rstrip()})
        return len(s)

    def flush(self):
        self.stream.flush()


def _worker(queue: "Queue", mode: str) -> None:
    def emit(ev: dict) -> None:
        queue.put(ev)

    sys.stdout = _LogTee(queue, sys.__stdout__)
    sys.stderr = _LogTee(queue, sys.__stderr__)

    t0 = time.perf_counter()
    synth_only = mode == "synth"
    emit({"type": "run_start", "mode": mode,
          "stages": ["synth", "publish"] if synth_only else STAGE_KEYS})
    try:
        if synth_only:
            _run_synth(emit)
        else:
            from ..pipeline import run
            run(emit)
        emit({"type": "run_done", "ok": True, "mode": mode,
              "elapsed": round(time.perf_counter() - t0, 1)})
    except Exception as exc:  # report, don't crash silently
        traceback.print_exc()
        emit({"type": "run_error", "message": str(exc)[:300],
              "elapsed": round(time.perf_counter() - t0, 1)})
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        queue.put({"type": "_end"})


def _run_synth(emit) -> None:
    """Re-voice the current (possibly hand-edited) script.json, nothing else."""
    from ..llm import unload_all
    from ..synth import generate_audio

    unload_all()  # make room for the TTS model
    emit(stage("synth", "running"))
    s = time.perf_counter()
    try:
        generate_audio(None, emit)
    except Exception as exc:
        emit(stage("synth", "error", detail=str(exc)[:200],
                   elapsed=time.perf_counter() - s))
        raise
    emit(stage("synth", "done", elapsed=time.perf_counter() - s))
    emit({"type": "artifact", "which": "audio"})

    from ..publish import publish
    emit(stage("publish", "running"))
    s = time.perf_counter()
    publish()
    emit(stage("publish", "done", elapsed=time.perf_counter() - s))
