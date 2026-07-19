"""FastAPI console: serves the single-page app and its JSON/WebSocket API.

A single run executes at a time in a child process; its progress events are
drained off a queue by a background thread and broadcast to every connected
WebSocket. All episode data is read live from the pipeline's output files.
"""
from __future__ import annotations

import asyncio
import queue as queuelib
import threading
from collections import deque
from contextlib import asynccontextmanager
from multiprocessing import get_context
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..config import ANCHOR, PATHS, WEATHER
from ..events import STAGE_KEYS, STAGES
from ..models import Script, Turn
from . import audio, config_io, health, state
from .runner import _worker

_STATIC = Path(__file__).resolve().parent / "static"
_CTX = get_context("spawn")


class RunManager:
    """Owns the active run process, its live status, and WS broadcast."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[WebSocket] = set()
        self.logs: deque[str] = deque(maxlen=300)
        self.proc = None
        self._drain: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status = self._idle_status()

    @staticmethod
    def _idle_status() -> dict:
        return {"running": False, "mode": None, "result": None, "message": None,
                "started": None, "finished": None, "substage": None,
                "stages": {k: {"status": "idle"} for k in STAGE_KEYS}}

    # --- lifecycle ---------------------------------------------------------
    def start(self, mode: str) -> tuple[bool, str]:
        with self._lock:
            if self.status["running"]:
                return False, "a run is already in progress"
            active = ["synth", "publish"] if mode == "synth" else STAGE_KEYS
            self.status = {
                "running": True, "mode": mode, "result": None, "message": None,
                "started": _now(), "finished": None, "substage": None,
                "stages": {k: {"status": "pending" if k in active else "skipped"}
                           for k in STAGE_KEYS},
            }
            self.logs.clear()
            q = _CTX.Queue()
            self.proc = _CTX.Process(target=_worker, args=(q, mode), daemon=True)
            self.proc.start()
            self._drain = threading.Thread(target=self._drain_queue, args=(q,),
                                           daemon=True)
            self._drain.start()
        self._push({"type": "run_start", "mode": mode})
        return True, "started"

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            if not self.status["running"] or not self.proc:
                return False, "nothing is running"
            self.proc.terminate()
            self.status["result"] = "stopped"
        return True, "stopping"

    # --- queue draining (background thread) --------------------------------
    def _drain_queue(self, q) -> None:
        proc = self.proc
        while True:
            try:
                ev = q.get(timeout=0.5)
            except queuelib.Empty:
                if proc and not proc.is_alive():
                    break
                continue
            if ev.get("type") == "_end":
                break
            self._apply(ev)
            self._push(ev)
        if proc:
            proc.join(timeout=5)
        self._finalize()

    def _apply(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "stage":
            self.status["stages"][ev["key"]] = {
                "status": ev["status"], "detail": ev.get("detail"),
                "elapsed": ev.get("elapsed"),
                "sub": self.status["stages"].get(ev["key"], {}).get("sub"),
            }
        elif t == "substage":
            self.status["substage"] = ev
            st = self.status["stages"].get(ev["key"], {})
            st["sub"] = ev["message"]
            self.status["stages"][ev["key"]] = st
        elif t == "log":
            self.logs.append(ev["line"])
        elif t == "run_done":
            self.status.update(running=False, result="ok", finished=_now())
        elif t == "run_error":
            self.status.update(running=False, result="error",
                               message=ev.get("message"), finished=_now())

    def _finalize(self) -> None:
        if self.status["running"]:
            self.status.update(running=False, finished=_now(),
                               result=self.status["result"] or "stopped")
        self._push({"type": "run_end", "status": self.status})

    # --- websocket fan-out -------------------------------------------------
    def _push(self, ev: dict) -> None:
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._broadcast(ev), self.loop)

    async def _broadcast(self, ev: dict) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_json(ev)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def snapshot(self) -> dict:
        return {"type": "snapshot", "run": self.status, "logs": list(self.logs)}


def _now() -> float:
    return __import__("time").time()


manager = RunManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Bulletin Desk", lifespan=lifespan)


# --- API -------------------------------------------------------------------
@app.get("/api/stages")
def api_stages():
    return [{"key": k, "label": lb, "desc": d} for k, lb, d in STAGES]


@app.get("/api/health")
def api_health():
    return health.check()


@app.get("/api/state")
def api_state():
    return {**state.build_state(), "run": manager.status, "logs": list(manager.logs)}


@app.get("/api/config")
def api_config_get():
    return config_io.read_config()


@app.patch("/api/config")
async def api_config_patch(updates: dict):
    return config_io.write_config(updates)


class ScriptPayload(BaseModel):
    turns: list[Turn]


@app.put("/api/script")
def api_script_put(payload: ScriptPayload):
    valid = {ANCHOR.name, WEATHER.name}
    turns = [Turn(speaker=t.speaker if t.speaker in valid else ANCHOR.name,
                  text=t.text) for t in payload.turns if t.text.strip()]
    if not turns:
        return JSONResponse({"error": "script is empty"}, status_code=400)
    PATHS.ensure()
    PATHS.script.write_text(Script(turns=turns).model_dump_json(indent=2))
    return {"ok": True, "turns": len(turns)}


@app.post("/api/run")
def api_run():
    ok, msg = manager.start("full")
    return JSONResponse({"ok": ok, "message": msg}, status_code=202 if ok else 409)


@app.post("/api/synth")
def api_synth():
    if not PATHS.script.exists():
        return JSONResponse({"ok": False, "message": "no script to voice"},
                            status_code=409)
    ok, msg = manager.start("synth")
    return JSONResponse({"ok": ok, "message": msg}, status_code=202 if ok else 409)


@app.post("/api/stop")
def api_stop():
    ok, msg = manager.stop()
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 409)


@app.get("/api/audio")
def api_audio():
    if not PATHS.audio.exists():
        return JSONResponse({"error": "no episode yet"}, status_code=404)
    return FileResponse(str(PATHS.audio), media_type="audio/wav",
                        filename="episode.wav")


@app.get("/api/waveform")
def api_waveform():
    return {"peaks": audio.waveform()}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    manager.clients.add(ws)
    await ws.send_json(manager.snapshot())
    try:
        while True:
            await ws.receive_text()  # client sends nothing; this detects close
    except WebSocketDisconnect:
        pass
    finally:
        manager.clients.discard(ws)


# --- static single-page app (mounted last so /api and /ws win) -------------
@app.get("/")
def index():
    return FileResponse(str(_STATIC / "index.html"))


app.mount("/", StaticFiles(directory=str(_STATIC)), name="static")
