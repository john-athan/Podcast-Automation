"""Live end-to-end test against a running console server (default :8765).

Exercises the mutation endpoints and the full run path (spawn -> queue ->
drain thread -> WebSocket broadcast), including graceful error surfacing when
LM Studio is down. Restores any files/.env it touches.

Run:  .venv/bin/python scripts/test_web_live.py [port]
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import websockets

BASE = f"http://127.0.0.1:{sys.argv[1] if len(sys.argv) > 1 else 8765}"
WS = BASE.replace("http", "ws") + "/ws"
ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=20) as c:
        # --- waveform now varies (RMS envelope) ---------------------------
        peaks = (await c.get("/api/waveform")).json()["peaks"]
        assert peaks and min(peaks) < 0.65, f"waveform not dynamic: min={min(peaks)}"
        print(f"waveform: {len(peaks)} peaks, range {min(peaks):.2f}-{max(peaks):.2f}  OK")

        # --- config PATCH round-trips (restore .env after) ----------------
        env_before = ENV.read_text() if ENV.exists() else None
        cfg = (await c.get("/api/config")).json()
        ddpm = next(f for f in cfg["fields"] if f["key"] == "ddpm_steps")["value"]
        new = (await c.patch("/api/config", json={"ddpm_steps": ddpm + 5})).json()
        got = next(f for f in new["fields"] if f["key"] == "ddpm_steps")["value"]
        assert got == ddpm + 5, f"config patch failed: {got}"
        assert f"TTS_DDPM_STEPS={ddpm + 5}" in ENV.read_text()
        print(f"config PATCH: ddpm {ddpm} -> {got}, persisted to .env  OK")
        if env_before is None:
            ENV.unlink()  # we created it
        else:
            ENV.write_text(env_before)

        # --- script PUT round-trips (write back verbatim, no content change)
        state = (await c.get("/api/state")).json()
        turns = [{"speaker": s["speaker"], "text": s["text"]} for s in state["segments"]]
        r = (await c.put("/api/script", json={"turns": turns})).json()
        assert r["ok"] and r["turns"] == len(turns), f"script put: {r}"
        print(f"script PUT: {r['turns']} turns saved  OK")

        # empty-script rejected
        rej = await c.put("/api/script", json={"turns": [{"speaker": "Anchor", "text": "  "}]})
        assert rej.status_code == 400, f"empty script not rejected: {rej.status_code}"
        print("script PUT: empty payload rejected 400  OK")

        # --- full run over WebSocket (LM Studio down -> graceful error) ----
        events = []
        async with websockets.connect(WS) as ws:
            snap = json.loads(await ws.recv())
            assert snap["type"] == "snapshot", snap
            print(f"ws snapshot: running={snap['run']['running']}  OK")

            r = await c.post("/api/run")
            assert r.status_code == 202, f"run not accepted: {r.status_code}"

            # a second run must be rejected while one is active
            busy = await c.post("/api/run")
            assert busy.status_code == 409, f"double-run not blocked: {busy.status_code}"
            print("run: started (202), concurrent run blocked (409)  OK")

            try:
                async with asyncio.timeout(90):
                    while True:
                        ev = json.loads(await ws.recv())
                        events.append(ev)
                        if ev["type"] in ("run_done", "run_error"):
                            print(f"  <- {ev['type']}: {ev.get('message', 'ok')}")
                        elif ev["type"] == "stage":
                            print(f"  <- stage {ev['key']}: {ev['status']}"
                                  + (f" ({ev['detail']})" if ev.get('detail') else ""))
                        if ev["type"] == "run_end":
                            break
            except (asyncio.TimeoutError, TimeoutError):
                print("  (timed out waiting for run_end)")

        types = [e["type"] for e in events]
        assert "run_start" in types, "no run_start"
        assert any(t in ("run_done", "run_error") for t in types), "run never resolved"
        assert "run_end" in types, "no run_end"
        # ingest should at least have started
        assert any(e["type"] == "stage" and e["key"] == "ingest" for e in events), "ingest never ran"

        # server must return to idle
        final = (await c.get("/api/state")).json()["run"]
        assert not final["running"], "run stuck as running"
        print(f"run resolved: result={final['result']}, server idle  OK")

    print("\nALL LIVE WEB ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
