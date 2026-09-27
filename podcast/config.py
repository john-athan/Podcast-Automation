"""Central config. Everything local, no cloud LLM/TTS."""
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

# --- Kokoro (local MLX TTS) -------------------------------------------------
TTS_MODEL = os.getenv("TTS_MODEL", "mlx-community/Kokoro-82M-bf16")
TTS_LANG_CODE = "a"  # American English, for both misaki's G2P and the voice packs below
SAMPLE_RATE = 24_000  # Kokoro's native output rate; synth.py resamples only if this stops matching
LUFS_TARGET = -16.0  # podcast loudness standard

# --- Listen-back (post-synthesis ASR check) ---------------------------------
# mlx_audio.stt bundled models: parakeet-tdt-0.6b-v2 is the English-only TDT
# checkpoint (v3 trades English accuracy for 25-language coverage we don't
# need); it decodes far faster than whisper-large-v3-turbo on this Mac.
ASR_MODEL = os.getenv("ASR_MODEL", "mlx-community/parakeet-tdt-0.6b-v2")
LISTEN_BACK = os.getenv("LISTEN_BACK", "1") not in ("0", "false", "False")
LISTEN_BACK_WER_MAX = float(os.getenv("LISTEN_BACK_WER_MAX", "0.15"))

# The exact lead sentence write.py gives the markets turn. Shared with synth.py,
# which has no stored segment type and tells the markets turn apart from a
# story turn by matching this prefix.
MARKETS_LEAD = "Now to the markets."


@dataclass(frozen=True)
class Host:
    name: str          # role label the writer uses as the speaker tag
    voice: str         # Kokoro voice id
    speed: float = 1.0  # Kokoro's own generation-time pacing knob
    tempo: float = 1.0  # post-synthesis ffmpeg atempo (pitch-preserving); applied only if != 1.0


# Tagesschau-style: one authoritative anchor for the news, a second voice for weather.
# Voice + speed picked in a blind A/B listening trial against the VibeVoice
# incumbent. The anchor's pace comes entirely from Kokoro's own generation
# speed (no post-synthesis stretch); the weather voice keeps the tempo bump
# that VibeVoice also used.
ANCHOR = Host(name="Anchor", voice=os.getenv("ANCHOR_VOICE", "am_michael"),
              speed=float(os.getenv("SPEED_ANCHOR", "1.10")),
              tempo=float(os.getenv("TEMPO_ANCHOR", "1.0")))
WEATHER = Host(name="Weather", voice=os.getenv("WEATHER_VOICE", "af_heart"),
               speed=float(os.getenv("SPEED_WEATHER", "1.0")),
               tempo=float(os.getenv("TEMPO_WEATHER", "1.10")))
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
    @property
    def listen_back(self) -> Path: return self.out / "listen_back.json"

    def ensure(self) -> Paths:
        self.out.mkdir(parents=True, exist_ok=True)
        return self


PATHS = Paths()
