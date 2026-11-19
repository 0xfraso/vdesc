---
name: vdesc
description: >
  Turn a YouTube URL or local video into a timestamped transcript and an
  exhaustive, grounded markdown breakdown with the vdesc CLI (~/video-describer).
  Use when the user shares a video link or asks to transcribe, describe,
  summarize, or break down a video, or mentions vdesc.
---

# vdesc — video description pipeline

Produce transcripts, code-faithful video descriptions, and summaries from one
CLI. The tool's own `--help` and `~/video-describer/README.md` are the reference
for flags and layout; this skill carries only what they cannot tell you.

## Always run from the repo root

`config.toml`, the `.env` API keys, and the default `out/` directory all resolve
against the current working directory. Every invocation starts the same way:

```bash
cd /home/fraso/video-describer && .venv/bin/vdesc <command> ...
```

`vdesc` is not on PATH; the venv binary is the only entry point. If `doctor`
reports endpoints unconfigured, the cause is almost always the working
directory, not the config.

## Pick the command

| Situation | Command |
|---|---|
| URL or local file, want the breakdown | `describe <input>` (URLs auto-download ≤1080p) |
| Transcript only | `transcribe <file>` |
| Summarize an existing description | `summarize out/<slug>/description.md` |
| Timestamped transcript already exists | `describe <file> --transcript <transcript.txt>` (imports, skips ASR) |

## Choose depth

`--depth max` (20–30k words, 7 sections, all code verbatim) is the config
default and matches the user's established pattern — when they say "same level
of detail", it is max. `standard` (8–12k) for a solid breakdown; `brief`
(2–3k) for a quick pass.

## Match `--context` to the video

One clause naming the video's domain; the vision model uses it to decide what
to transcribe on screen. Default config suits game-engine tutorials; override
per video, e.g. `--context "an AI/LLM engineering conference talk (slides,
code demos and terminal output appear on screen)"`.

## Run it, then report

A max run takes 20–40 min (writer-dominated); vision ~5 min; Groq ASR seconds.
Launch long runs in the background. A run is complete when stdout ends with
`Done. Outputs in out/<slug>/`. Report the deliverable paths, description word
count, and the ledger totals just printed (calls, tokens, est cost).

## Resume and force

Every stage is cached by content key. A crashed or failed run resumes with the
same command: missing vision batches and writer sections reprocess individually,
finished ones are reused. Redo stages deliberately with `--force
transcript,vision` (or `all`). Editing `--asr-prompt`, prompts, or models
invalidates the affected caches automatically.

## Fixing problems

- Anything unexpected: `.venv/bin/vdesc doctor --probe` sends tiny live
  requests to all three providers and names the broken one.
- Proper nouns mangled in the transcript: add a vocabulary hint
  `--asr-prompt "Name1, Name2, ..."` and `--force transcript`.
- A vision batch failed: re-run `describe`; only the missing batches reprocess.
- Quota/rate limits: Groq free tier allows ~8 h of audio per day (25 MB per
  upload; a 20-min video is ~6 MB). Spend so far lives in
  `out/<slug>/usage.json`.

## Keys

Secrets live in environment variables, loaded from the repo `.env` or
`~/.vdesc/.env`: `GROQ_API_KEY` (ASR), `ZAI_API_KEY` (vision + text LLMs,
on the user's Coding Plan). Config files name these variables (`api_key_env`)
and never contain the keys themselves.
