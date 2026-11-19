# AGENTS.md

Pointers for agents working in this repository.

## Commands

```bash
cd /home/fraso/vdesc                    # config.toml, .env keys and out/ all resolve against CWD
.venv/bin/vdesc ...                     # CLI (not on PATH; venv binary is the only entry point)
.venv/bin/python -m pytest -q           # 26 unit tests — run before committing anything
.venv/bin/vdesc doctor --probe          # tiny live requests against all three providers
```

## Where things live

- `README.md` — flags, config reference, output layout. The CLI's `--help` is
  the authority on flags.
- `DESIGN.md` — the nine principles the code encodes (two evidence streams,
  verbatim OCR, stage cache keys, provider adapters). Read it before changing
  pipeline behavior; keep changes consistent with it.
- `src/vdesc/prompts/` — prompt templates are data, not code. Their content
  is hashed into stage cache keys, so editing one intentionally invalidates the
  affected caches. Templates must contain no stray braces (`str.format`).
- `tests/` — pure-function tests for chunking/stitching, frame slicing, cache
  keys, config. New behavior in `media.py`, `writer.py`, `providers/asr/base.py`
  earns a test here.

## Conventions

- Secrets (`GROQ_API_KEY`, `ZAI_API_KEY`) live in `.env` or the environment —
  never in `config.toml`, which references them by env-var name (`api_key_env`).
  Both `.env` and `config.toml` are gitignored; `config.example.toml` is the
  committed template.
- Providers are generic OpenAI-compatible endpoints: vendor specifics belong in
  presets/config, never hardcoded in pipeline code.
- `out/` is run output, gitignored — inspect it freely, commit nothing from it.
