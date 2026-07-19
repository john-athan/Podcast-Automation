# Podcast Automation v2

Fully-local, Tagesschau-style English news bulletin generator. Pulls fresh RSS,
has a local LLM curate and write the bulletin, grounds it in full article text,
fact-checks it, then a local MLX text-to-speech model voices it — **no cloud LLM
or TTS calls**. Built for Apple Silicon.

## Pipeline

```
ingest   -> RSS feeds fetched in parallel (async httpx)
curate   -> semantic dedup (local embeddings) + local LLM ranks/picks 6 stories
hydrate  -> full article text fetched + extracted (trafilatura) for the picks
write    -> local LLM writes greeting + headline teasers + one turn per story
verify   -> local LLM fact-checks every claim against sources, cuts unsupported
assemble -> markets brief + Munich weather built deterministically from real data
synth    -> VibeVoice (MLX): anchor voice + weather voice; ffmpeg loudnorm -16 LUFS
publish  -> (optional) Google Drive upload + email link
```

Structure: a single authoritative anchor reads the news; a second voice reads the
weather. Market figures and weather come straight from live data (never phrased by
the LLM), so those numbers are always exact. The writer LLM is unloaded before TTS
so everything fits in 24 GB.

## Stack

| Stage  | Tech |
|--------|------|
| Script | **qwen3.5-9b** via **LM Studio** (local, OpenAI-compatible server) |
| Dedup  | **nomic-embed** embeddings via LM Studio (drop same-event stories) |
| Full text | **trafilatura** (real article body, not thin RSS summaries) |
| Voice  | **VibeVoice-Realtime-0.5B** (MLX) — per-voice conditioning caches |
| Data   | Open-Meteo (Munich weather), Yahoo Finance (DAX / S&P / EUR-USD) — keyless |
| Glue   | async httpx, feedparser, pydantic, ffmpeg |

Anchor + weather voices map to bundled VibeVoice caches; swap voices/models/city
in `podcast/config.py` or via `.env`.

## Requirements

- Apple Silicon Mac, Python 3.14 (managed by `uv`)
- [LM Studio](https://lmstudio.ai) running its local server (port 1234) with a
  writer model downloaded (`qwen3.5-9b-mlx`), and an API token
- `ffmpeg` (for loudness normalization) — optional but recommended

## Setup

```sh
uv sync                        # creates .venv from uv.lock (Python 3.14)
cp .env.example .env           # set LMSTUDIO_API_TOKEN
```

Optional extras (web console, publishing):

```sh
uv sync --extra web            # local web console (FastAPI + uvicorn)
uv sync --extra publish        # Google Drive upload + email
```

## Run

```sh
uv run podcast                 # full pipeline -> output/episode.wav
```

Individual stages are runnable too:

```sh
uv run python -m podcast.ingest    # fetch RSS
uv run python -m podcast.curate    # dedup + pick stories
uv run python -m podcast.extras    # weather + markets probe
uv run python -m podcast.write     # curate -> write -> fact-check -> assemble
uv run python -m podcast.synth     # re-voice the current script.json
```

## Web console

A local control room for the pipeline — trigger runs, watch each stage live,
**review and edit the script before it's voiced**, tweak config without touching
`.env`, and play back the episode with a real waveform and loudness meter.

```sh
uv sync --extra web             # fastapi + uvicorn
uv run podcast-web              # -> http://127.0.0.1:8000  (WEB_HOST/WEB_PORT to override)
```

What it does:

- **Pipeline tally** — the eight stages with live status, timings, and sub-progress
  (dedup counts, claims cut, `synth` turn *i/n*), streamed over a WebSocket.
- **Running order** — every segment (greeting, teasers, each story, markets,
  weather, sign-off). Story turns are matched back to their **source article**
  (a monotonic alignment handles a story split across turns); the fact-check
  pass is shown inline as **struck-out claims** with the reviewer's note, diffed
  from the pre-check draft. Hit **Edit** to fix any read, **Save**, then
  **Re-synth from script** to re-voice just the edited bulletin.
- **Output** — waveform, measured integrated loudness (ffmpeg `ebur128`) against
  the −16 LUFS target, and a seekable player.
- **Run config** — city, writer model, DDPM steps, voices, speeds, publish —
  edited in place and written to `.env`; each run executes in a fresh child
  process so edits apply immediately with no restart.

Every run is a normal `podcast.pipeline.run` in a child process (so its RAM is
reclaimed on exit and `.env` is reloaded); the CLI and console share the exact
same stage code.

Two verification scripts cover the wiring without needing the local models:

```sh
uv run python scripts/test_pipeline_events.py   # orchestration + events + persistence (mocked stages)
uv run podcast-web &                             # then, against the running server:
uv run python scripts/test_web_live.py           # endpoints + WebSocket + run lifecycle
```

## Output

- `output/content.json`   — fetched articles
- `output/curation.json`  — chosen stories
- `output/stories.json`   — the source article behind each pick (for the console)
- `output/draft.json`     — pre-fact-check draft (diffed to show what was cut)
- `output/factcheck.json` — corrected turns + removal notes
- `output/extras.json`    — exact market quotes + weather figures
- `output/script.json`    — the bulletin script (anchor + weather turns)
- `output/episode.wav`    — the finished episode

## Publishing (optional)

Set `PUBLISH=1` plus Drive/SMTP vars in `.env` to upload the episode to Google
Drive and email the link.

## Config knobs (`.env`)

| Var | Default | Notes |
|-----|---------|-------|
| `WRITER_MODEL` | `qwen3.5-9b-mlx` | any LM Studio model; `qwen3.5-4b-mlx` is lighter |
| `TTS_MODEL` | `mlx-community/VibeVoice-Realtime-0.5B-fp16` | |
| `TTS_DDPM_STEPS` | `20` | higher = better quality, slower |
| `ANCHOR_VOICE` / `WEATHER_VOICE` | `en-Frank_man` / `en-Emma_woman` | bundled VibeVoice caches |
| `SPEED_ANCHOR` / `SPEED_WEATHER` | `0.92` / `1.10` | tempo, pitch-preserving; >1 = faster |
| `WEATHER_CITY` / `WEATHER_LAT` / `WEATHER_LON` | `Munich` / `48.137` / `11.575` | weather segment |

## Notes on model choice

- `gemma-4-26b` won't load on 24 GB (LM Studio guardrail) — too tight.
- `gpt-oss-20b` degenerates under strict JSON output; avoid for this task.
- `qwen3.5-9b` is a reasoning model — it emits structured output in the
  reasoning channel, which `podcast/llm.py` reads transparently.

## License

MIT — see [LICENSE](LICENSE). Note the local models carry their own licenses
(VibeVoice: MIT; Qwen3.5: Qwen license) and are not redistributed here.
