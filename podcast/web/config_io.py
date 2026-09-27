"""Read and edit the run configuration from the console.

Editable settings are persisted to the project `.env` (the pipeline's source of
truth). Because each run executes in a fresh child process that reloads `.env`,
edits take effect on the very next run with no server restart.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

from .. import config as cfg

_ENV_PATH = Path(cfg.__file__).resolve().parent.parent / ".env"

# Kokoro American-English voice packs (lang_code "a", from config.py) offered
# in the voice pickers.
VOICES = ["af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore",
          "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
          "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael",
          "am_onyx", "am_puck", "am_santa"]

# key -> (env var, label, kind, default-from-config)
FIELDS: dict[str, tuple[str, str, str, object]] = {
    "weather_city":  ("WEATHER_CITY",  "Weather city",   "str",   cfg.WEATHER_CITY),
    "weather_lat":   ("WEATHER_LAT",   "Latitude",       "float", cfg.WEATHER_LAT),
    "weather_lon":   ("WEATHER_LON",   "Longitude",      "float", cfg.WEATHER_LON),
    "writer_model":  ("WRITER_MODEL",  "Writer model",   "str",   cfg.WRITER_MODEL),
    "anchor_voice":  ("ANCHOR_VOICE",  "Anchor voice",   "voice", cfg.ANCHOR.voice),
    "weather_voice": ("WEATHER_VOICE", "Weather voice",  "voice", cfg.WEATHER.voice),
    "speed_anchor":  ("SPEED_ANCHOR",  "Anchor speed",   "float", cfg.ANCHOR.speed),
    "speed_weather": ("SPEED_WEATHER", "Weather speed",  "float", cfg.WEATHER.speed),
    "tempo_anchor":  ("TEMPO_ANCHOR",  "Anchor tempo",   "float", cfg.ANCHOR.tempo),
    "tempo_weather": ("TEMPO_WEATHER", "Weather tempo",  "float", cfg.WEATHER.tempo),
    "publish":       ("PUBLISH",       "Publish (Drive + email)", "bool", False),
}


def _coerce(kind: str, raw):
    if raw is None:
        return None
    if kind == "int":
        return int(float(raw))
    if kind == "float":
        return float(raw)
    if kind == "bool":
        return str(raw).strip() in ("1", "true", "True", "on", "yes")
    return str(raw)


def read_config() -> dict:
    """Effective values (project .env override, else config default) + feeds."""
    env = dotenv_values(_ENV_PATH) if _ENV_PATH.exists() else {}
    fields = []
    for key, (var, label, kind, default) in FIELDS.items():
        raw = env.get(var)
        value = _coerce(kind, raw) if raw not in (None, "") else (
            _coerce(kind, default) if kind == "bool" else default)
        fields.append({"key": key, "var": var, "label": label,
                       "kind": kind, "value": value})
    feeds = [{"domain": d, "count": len(urls)} for d, urls in cfg.RSS_FEEDS.items()]
    return {"fields": fields, "voices": VOICES, "feeds": feeds}


def write_config(updates: dict[str, object]) -> dict:
    """Upsert the given editable keys into the project `.env`, then re-read."""
    to_set: dict[str, str] = {}
    for key, val in updates.items():
        if key not in FIELDS:
            continue
        var, _label, kind, _default = FIELDS[key]
        coerced = _coerce(kind, val)
        if kind == "bool":
            to_set[var] = "1" if coerced else "0"
        else:
            to_set[var] = str(coerced)
    _upsert_env(to_set)
    return read_config()


def _upsert_env(pairs: dict[str, str]) -> None:
    lines = _ENV_PATH.read_text().splitlines() if _ENV_PATH.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in pairs:
                out.append(f"{k}={pairs[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in pairs.items():
        if k not in seen:
            out.append(f"{k}={v}")
    _ENV_PATH.write_text("\n".join(out) + "\n")
