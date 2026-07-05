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

- Apple Silicon Mac, Python 3.11+
- [LM Studio](https://lmstudio.ai) running its local server (port 1234) with a
  writer model downloaded (`qwen3.5-9b-mlx`), and an API token
- `ffmpeg` (for loudness normalization) — optional but recommended

## Setup

```sh
uv venv && source .venv/bin/activate
uv pip install -e .            # or: uv pip install -r <deps in pyproject>
cp .env.example .env           # set LMSTUDIO_API_TOKEN
```

## Run

```sh
python run.py                  # full pipeline -> output/episode.wav
```

Individual stages are runnable too:

```sh
python -m podcast.ingest
python -m podcast.curate
python -m podcast.write
python -m podcast.synth
```

## Output

- `output/content.json`   — fetched articles
- `output/curation.json`  — chosen stories
- `output/script.json`    — the dialogue
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
| `TARGET_MINUTES` | `6` | rough episode length |

## Notes on model choice

- `gemma-4-26b` won't load on 24 GB (LM Studio guardrail) — too tight.
- `gpt-oss-20b` degenerates under strict JSON output; avoid for this task.
- `qwen3.5-9b` is a reasoning model — it emits structured output in the
  reasoning channel, which `podcast/llm.py` reads transparently.
