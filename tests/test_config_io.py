"""Console config writes: values that would corrupt .env or fail the next run
are rejected before anything is written.

    uv run python tests/test_config_io.py
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from podcast.web import config_io

checks = 0


def check(name, condition):
    global checks
    assert condition, name
    checks += 1
    print(f"  ok {name}")


def rejected(updates):
    try:
        config_io.write_config(updates)
    except ValueError:
        return True
    return False


with tempfile.TemporaryDirectory() as d:
    config_io._ENV_PATH = Path(d) / ".env"
    check("a newline cannot smuggle a second variable into .env",
          rejected({"weather_city": "Munich\nLMSTUDIO_BASE_URL=http://evil"}))
    check("nothing was written by the rejected update", not config_io._ENV_PATH.exists())
    check("tempo outside atempo's range is rejected", rejected({"tempo_anchor": "3"}))
    check("a zero speed is rejected", rejected({"speed_weather": 0}))
    check("NaN is rejected", rejected({"weather_lat": "nan"}))
    check("latitude beyond the poles is rejected", rejected({"weather_lat": 91}))
    check("an unknown voice is rejected", rejected({"anchor_voice": "xx_nobody"}))
    check("JSON null is a rejection, not a crash", rejected({"weather_city": None}))
    check("a Unicode line separator is rejected", rejected({"weather_city": "a\u2028b"}))
    config_io.write_config({"weather_city": "Berlin", "tempo_anchor": "1.2"})
    check("a valid update is written", "WEATHER_CITY=Berlin" in config_io._ENV_PATH.read_text())

print(f"{checks} checks passed")
