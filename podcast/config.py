"""Central config. Everything local — no cloud LLM/TTS."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load token/creds from project .env then fall back to ~/.env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv(Path.home() / ".env")

OUT_DIR = Path(os.getenv("PODCAST_OUT", "output"))

# --- LM Studio (local script writer) ---------------------------------------
LMSTUDIO_BASE_URL = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
LMSTUDIO_API_TOKEN = os.getenv("LMSTUDIO_API_TOKEN", "lm-studio")
# qwen3.5-9b (MLX, reasoning) gives the cleanest structured output + best dialogue
# on 24GB. gpt-oss-20b degenerates under strict JSON; qwen3.5-4b is the light fallback.
WRITER_MODEL = os.getenv("WRITER_MODEL", "qwen3.5-9b-mlx")

# --- VibeVoice (local MLX TTS) ---------------------------------------------
TTS_MODEL = os.getenv("TTS_MODEL", "mlx-community/VibeVoice-Realtime-0.5B-fp16")
SAMPLE_RATE = 24_000
# Higher diffusion steps + cfg = better quality, slower. Quality-first defaults.
TTS_DDPM_STEPS = int(os.getenv("TTS_DDPM_STEPS", "20"))
TTS_CFG_SCALE = float(os.getenv("TTS_CFG_SCALE", "1.5"))
LUFS_TARGET = -16.0  # podcast loudness standard


@dataclass(frozen=True)
class Host:
    name: str          # role label the writer uses as the speaker tag
    voice: str         # VibeVoice voice-cache id
    speed: float = 1.0  # post-synthesis tempo (pitch-preserving); >1 = faster


# Tagesschau-style: one authoritative anchor for the news, a second voice for weather.
# Bundled voices: en-Frank_man, en-Davis_man, en-Carter_man, en-Mike_man,
#                 en-Grace_woman, en-Emma_woman.
# Measured base rates: Frank ~196 wpm (brisk), Emma ~159 wpm (calm).
# These tempos land both near a clear ~180 wpm news-anchor pace.
ANCHOR = Host(name="Anchor", voice=os.getenv("ANCHOR_VOICE", "en-Frank_man"),
              speed=float(os.getenv("SPEED_ANCHOR", "0.92")))
WEATHER = Host(name="Weather", voice=os.getenv("WEATHER_VOICE", "en-Emma_woman"),
               speed=float(os.getenv("SPEED_WEATHER", "1.10")))
HOSTS: dict[str, Host] = {ANCHOR.name: ANCHOR, WEATHER.name: WEATHER}

# --- Local extras -----------------------------------------------------------
# Munich weather (Open-Meteo, keyless).
WEATHER_LAT = float(os.getenv("WEATHER_LAT", "48.137"))
WEATHER_LON = float(os.getenv("WEATHER_LON", "11.575"))
WEATHER_CITY = os.getenv("WEATHER_CITY", "Munich")
# Markets brief (Yahoo Finance chart API, keyless). (label, symbol)
MARKET_SYMBOLS: list[tuple[str, str]] = [
    ("the DAX", "^GDAXI"),
    ("the S&P 500", "^GSPC"),
    ("the euro against the dollar", "EURUSD=X"),
]

# --- Content sources --------------------------------------------------------
RSS_FEEDS: dict[str, list[str]] = {
    "tech": [
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://www.wired.com/feed/rss",
        "https://www.theverge.com/rss/index.xml",
    ],
    "business": [
        "https://feeds.content.dowjones.io/public/rss/mw_topstories",
        "https://feeds.marketwatch.com/marketwatch/topstories/",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    ],
    "science": [
        "https://www.newscientist.com/feed/home/",
        "http://rss.sciam.com/ScientificAmerican-Global",
        "https://www.sciencealert.com/feed",
    ],
}
ENTRIES_PER_FEED = 4


@dataclass
class Paths:
    out: Path = field(default_factory=lambda: OUT_DIR)

    @property
    def content(self) -> Path: return self.out / "content.json"
    @property
    def curation(self) -> Path: return self.out / "curation.json"
    @property
    def stories(self) -> Path: return self.out / "stories.json"
    @property
    def script(self) -> Path: return self.out / "script.json"
    @property
    def draft(self) -> Path: return self.out / "draft.json"
    @property
    def factcheck(self) -> Path: return self.out / "factcheck.json"
    @property
    def extras(self) -> Path: return self.out / "extras.json"
    @property
    def audio(self) -> Path: return self.out / "episode.wav"

    def ensure(self) -> "Paths":
        self.out.mkdir(parents=True, exist_ok=True)
        return self


PATHS = Paths()
