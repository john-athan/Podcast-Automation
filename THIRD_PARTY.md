# Third-party material in Podcast-Automation

MIT licensed, and its source was written for this project. This file records
what came from elsewhere and what that requires.

## Dependencies

Resolved by the installer, never vendored. Nothing here is redistributed by this
repository, so no notice obligation attaches to it. Listed because knowing what
the pipeline pulls in is worth more than the obligation would be.

| Package | License |
| --- | --- |
| httpx | BSD-3-Clause |
| feedparser | BSD-2-Clause |
| trafilatura | Apache-2.0 |
| openai (client only) | Apache-2.0 |
| pydantic | MIT |
| python-dotenv | BSD-3-Clause |
| mlx-audio | MIT |
| misaki (extra: `en`) | Apache-2.0 |
| soundfile | BSD-3-Clause |
| numpy | BSD-3-Clause |
| torch | BSD-3-Clause |
| google-api-python-client (extra: `publish`) | Apache-2.0 |
| google-auth-oauthlib (extra: `publish`) | Apache-2.0 |
| cryptography (extra: `publish`) | Apache-2.0 OR BSD-3-Clause |

## espeak-ng (not a Python dependency)

Kokoro's text front end (`misaki`) falls back to espeak-ng for words outside its
own dictionary. espeak-ng is GPL-3.0, and it is used here at runtime as a
separately installed system library (via Homebrew), loaded through ctypes; it
is not bundled or distributed with this project, and `uv sync` never installs
it. See the README's requirements for the `brew install espeak-ng` step.

## Models and generated audio

Speech is synthesised locally through `mlx-audio`. The model weights are not in
this repository; they are fetched at run time, and their own license governs
what may be done with the audio they produce. Anyone publishing episodes made
this way should read the license of the weights they actually loaded, because
that is where the terms on the output live.

The `openai` package is used as a client against a local LM Studio endpoint. No
OpenAI service is called by default.

## Article content

The pipeline reads feeds and extracts article text at run time. That text
belongs to whoever published it, it is not stored in this repository, and using
this tool on it does not grant any right to republish it. This matters more than
anything else in this file.

## Reviewed and cleared

Nothing yet. Findings from `oss provenance Podcast-Automation` that turn out to
be convergent output rather than copying belong here, with the date and the
reasoning.
