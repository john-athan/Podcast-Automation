"""Assemble the console's view of the current episode from the output files.

Everything here is derived from real artifacts the pipeline writes:
  script.json    final assembled bulletin (source of the running order)
  draft.json     pre-fact-check news turns (to show what was struck out)
  factcheck.json corrected news turns + removal notes
  stories.json   the source article behind each pick
  extras.json    exact market quotes + weather figures

Missing files degrade gracefully (an older run without them still renders).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from ..config import ANCHOR, PATHS, WEATHER, WEATHER_CITY
from ..models import Script
from . import audio

# Reference base speaking rates for the bundled voices (from config.py notes).
_WPM = {"en-Frank_man": 196, "en-Emma_woman": 159, "en-Davis_man": 190,
        "en-Grace_woman": 165, "en-Carter_man": 185, "en-Mike_man": 188}
_SIGNOFF = "That is tonight's bulletin. Good night."


def _load(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower())


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _word_diff(old: str, new: str) -> list[dict]:
    """Inline diff old->new as spans. cut=True marks removed words."""
    a, b = old.split(), new.split()
    spans: list[dict] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            spans.append({"text": " ".join(a[i1:i2]), "cut": False})
        elif tag == "delete":
            spans.append({"text": " ".join(a[i1:i2]), "cut": True})
        elif tag == "replace":
            spans.append({"text": " ".join(a[i1:i2]), "cut": True})
            spans.append({"text": " ".join(b[j1:j2]), "cut": False})
        elif tag == "insert":
            spans.append({"text": " ".join(b[j1:j2]), "cut": False})
    return [s for s in spans if s["text"].strip()]


def _classify(i: int, turn, n: int) -> str:
    text = turn.text.strip()
    if turn.speaker == WEATHER.name:
        return "weather"
    if text.startswith("Now to the markets"):
        return "markets"
    if text == _SIGNOFF or (i == n - 1 and text.lower().startswith("that is")):
        return "signoff"
    if i == 0:
        return "greeting"
    if i == 1 and re.search(r"top stor|coming up|headline", text, re.I):
        return "teasers"
    return "story"


def _build_diffs(script: Script) -> dict[int, dict]:
    """Map final-turn index -> {diff, cut_count, notes} from the fact-check pass.

    Corrected news turns are fuzzily aligned to draft turns (robust to drops),
    then diffed. Removal notes are attached to the turn whose cut text they best
    match; the rest are returned under index -1 as episode-level notes.
    """
    draft_raw = _load(PATHS.draft)
    fc_raw = _load(PATHS.factcheck)
    if not draft_raw or not fc_raw:
        return {}
    draft = [t for t in draft_raw.get("turns", [])]
    corrected = [t for t in fc_raw.get("turns", [])]
    notes = [n for n in fc_raw.get("removed", []) if n.strip()]
    final_by_text = {t.text.strip(): idx for idx, t in enumerate(script.turns)}

    out: dict[int, dict] = {}
    per_turn_cut: list[tuple[int, str]] = []  # (final_idx, removed_text)
    for c in corrected:
        ctext = c["text"].strip()
        fidx = final_by_text.get(ctext)
        if fidx is None:
            continue  # this corrected turn was edited later; skip its diff
        d = max(draft, key=lambda t: _ratio(c["text"], t["text"]), default=None)
        if not d:
            continue
        diff = _word_diff(d["text"], c["text"])
        cut_text = " ".join(s["text"] for s in diff if s["cut"])
        cut_count = sum(1 for s in diff if s["cut"])
        out[fidx] = {"diff": diff, "cut_count": cut_count, "notes": []}
        if cut_text:
            per_turn_cut.append((fidx, cut_text))

    # Attach each removal note to the best-matching cut turn; leftovers global.
    leftover: list[str] = []
    for note in notes:
        best_idx, best_r = None, 0.18
        for fidx, cut_text in per_turn_cut:
            r = _ratio(note, cut_text)
            if r > best_r:
                best_idx, best_r = fidx, r
        if best_idx is not None:
            out[best_idx]["notes"].append(note)
        else:
            leftover.append(note)
    out[-1] = {"notes": leftover, "total_cut": len(notes)}
    return out


_STOP = set(
    "the a an and or of to in for on with is are was were be by from at as it its "
    "into this that these those has have had will would can could their they them "
    "our we you your news today tonight story stories report reports said says also "
    "more most some such other".split())


def _toks(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower())
            if len(w) >= 4 and w not in _STOP}


def _topic_score(turn: str, story: dict) -> float:
    """Set-cosine of significant words shared between a turn and a pick's
    title+reason. Rewards shared named entities (T-Mobile, NASA, $10 million)."""
    tt = _toks(turn)
    pt = _toks(f"{story.get('title', '')} {story.get('reason', '')}")
    if not tt or not pt:
        return 0.0
    return len(tt & pt) / (len(tt) ** 0.5 * len(pt) ** 0.5)


def _align_stories(texts: list[str], stories: list[dict]) -> list[int]:
    """Assign each story turn to a pick, monotonically (assignments never go
    backwards). The writer emits stories in pick order and may split one story
    across consecutive turns, so a monotonic DP over topic scores recovers the
    mapping even when the turn count exceeds the pick count.
    """
    m, k = len(texts), len(stories)
    if m == 0 or k == 0:
        return [-1] * m
    sc = [[_topic_score(texts[i], stories[j]) for j in range(k)] for i in range(m)]
    NEG = float("-inf")
    dp = [[NEG] * k for _ in range(m)]
    par = [[-1] * k for _ in range(m)]
    for j in range(k):
        dp[0][j] = sc[0][j]
    for i in range(1, m):
        for j in range(k):
            best_j, best_v = -1, NEG
            for jp in range(j + 1):          # non-decreasing assignment
                if dp[i - 1][jp] > best_v:
                    best_v, best_j = dp[i - 1][jp], jp
            dp[i][j] = sc[i][j] + best_v
            par[i][j] = best_j
    j = max(range(k), key=lambda x: dp[m - 1][x])
    path = [0] * m
    for i in range(m - 1, -1, -1):
        path[i] = j
        if i > 0:
            j = par[i][j]
    return path


def build_state() -> dict:
    raw = _load(PATHS.script)
    if not raw:
        return {"episode": None, "segments": [], "voices": _voices(),
                "output": audio.audio_meta(), "fact_check": None}
    script = Script.model_validate(raw)
    turns = script.turns
    n = len(turns)
    stories = _load(PATHS.stories) or []
    extras = _load(PATHS.extras) or {}
    diffs = _build_diffs(script)

    kinds = [_classify(i, t, n) for i, t in enumerate(turns)]
    story_idx = [i for i, k in enumerate(kinds) if k == "story"]
    alignment = _align_stories([turns[i].text for i in story_idx], stories)
    story_pick = {ti: alignment[pos] for pos, ti in enumerate(story_idx)}

    segments: list[dict] = []
    pick_to_no: dict[int, int] = {}   # pick index -> distinct story number
    prev_pick = None
    total_words = 0
    for i, t in enumerate(turns):
        kind = kinds[i]
        total_words += len(t.text.split())
        seg: dict = {
            "index": i, "kind": kind, "speaker": t.speaker,
            "text": t.text, "diff": None, "cut_count": 0, "notes": [],
            "source": None, "markets": None, "weather": None, "data": False,
        }
        d = diffs.get(i)
        if d:
            seg["diff"] = d["diff"]
            seg["cut_count"] = d["cut_count"]
            seg["notes"] = d["notes"]

        if kind == "greeting":
            seg["label"], seg["sublabel"] = "Greeting", "Cold open"
        elif kind == "teasers":
            seg["label"], seg["sublabel"] = "Headline teasers", "Top-stories rundown"
        elif kind == "story":
            pick = story_pick.get(i, -1)
            src = None
            if 0 <= pick < len(stories):
                s = stories[pick]
                src = {k: s.get(k) for k in
                       ("domain", "title", "reason", "link", "source_host", "words")}
            seg["source"] = src
            continued = pick == prev_pick and pick != -1
            if pick in pick_to_no:
                no = pick_to_no[pick]
            else:
                no = pick_to_no[pick] = len(pick_to_no) + 1
            seg["label"] = (src["title"] if src else f"Story {no}")
            if continued:
                seg["sublabel"] = f"Story {no} · continued"
            else:
                seg["sublabel"] = "Lead story" if no == 1 else f"Story {no}"
            prev_pick = pick
        elif kind == "markets":
            seg["label"], seg["sublabel"] = "Markets brief", "Deterministic · live data"
            seg["markets"] = extras.get("markets") or None
            seg["data"] = True
        elif kind == "weather":
            city = (extras.get("weather") or {}).get("city", WEATHER_CITY)
            seg["label"], seg["sublabel"] = f"Weather — {city}", "Deterministic · Open-Meteo"
            seg["weather"] = extras.get("weather")
            seg["data"] = True
        else:  # signoff
            seg["label"], seg["sublabel"] = "Sign-off", "Close"
        segments.append(seg)

    meta = audio.audio_meta()
    est = meta["duration_s"] if meta.get("exists") else round(total_words / 2.5, 0)
    mtime = PATHS.script.stat().st_mtime
    ep_date = datetime.fromtimestamp(mtime)
    fc = diffs.get(-1)
    return {
        "episode": {
            "id": ep_date.strftime("%Y-%m-%d"),
            "turns": n,
            "words": total_words,
            "est_seconds": est,
            "stories": len(pick_to_no) or sum(1 for k in kinds if k == "story"),
            "updated": mtime,
        },
        "segments": segments,
        "voices": _voices(),
        "output": meta,
        "fact_check": {
            "total_cut": fc.get("total_cut", 0) if fc else 0,
            "other_notes": fc.get("notes", []) if fc else [],
        },
    }


def _voices() -> list[dict]:
    out = []
    for role, host in (("Anchor", ANCHOR), ("Weather", WEATHER)):
        out.append({
            "role": role, "name": host.name, "voice": host.voice,
            "speed": host.speed, "wpm": _WPM.get(host.voice),
        })
    return out
