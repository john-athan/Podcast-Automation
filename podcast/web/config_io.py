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


# Bounds for the float fields. The console writes straight into .env, which the
# pipeline trusts: ffmpeg's atempo only accepts 0.5 to 2.0, a zero or negative
# Kokoro speed makes it fail mid-run, and coordinates outside the globe make
# Open-Meteo answer 400, which the weather fetch then reports as "unavailable".
_RANGES = {
    "weather_lat": (-90.0, 90.0), "weather_lon": (-180.0, 180.0),
    "speed_anchor": (0.1, 3.0), "speed_weather": (0.1, 3.0),
    "tempo_anchor": (0.5, 2.0), "tempo_weather": (0.5, 2.0),
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
        _check(key, kind, coerced)
        if kind == "bool":
            to_set[var] = "1" if coerced else "0"
        else:
            to_set[var] = str(coerced)
    _upsert_env(to_set)
    return read_config()


def _check(key: str, kind: str, value) -> None:
    """Reject values that would corrupt .env or fail the next run."""
    if kind == "float":
        lo, hi = _RANGES.get(key, (float("-inf"), float("inf")))
        if not (lo <= value <= hi):  # also false for NaN
            raise ValueError(f"{key} must be between {lo} and {hi}")
    elif kind in ("str", "voice"):
        # A newline here would write a second line into .env, i.e. set any
        # variable (LMSTUDIO_BASE_URL, SMTP_SERVER, ...) from a PATCH body.
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"{key} must be a non-empty single line")
        if kind == "voice" and value not in VOICES:
            raise ValueError(f"{key} must be one of the offered voices")


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
