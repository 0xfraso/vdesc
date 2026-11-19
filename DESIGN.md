# DESIGN — the core principles

`vdesc` is the distilled core of the VideoAgent `describe_video.py` flow: the
framework, planner, role system, and multi-GB media stack were cut; the ideas that
made the output good were kept. This document records them so the code doesn't drift.

## 1. Two evidence streams, one timeline

- **Transcript** (ASR) = what was said. It is the timeline spine: timestamps in,
  walkthrough sections out.
- **Frame notes** (vision OCR) = what was shown, especially code and settings panels,
  transcribed **verbatim** with `[illegible]` markers instead of guesses.
- The writer's only job is to **merge** the two streams. Every prompt carries
  "never invent; ground everything in the transcript/frame notes". Fidelity to the
  video beats eloquence.

## 2. Deterministic sampling beats clever detection

Frames are sampled on a fixed grid (`1 frame / N seconds`, capped width). No scene
detection: it's reproducible, cacheable, and good enough — a technical video shows
something relevant within any 5-second window.

## 3. Verbatim where fidelity matters

Code, formulas, and inspector settings are extracted exactly as visible. Vision
batches persist individually (`vision/batch_NNNN.md`), so failures resume per batch
and partial analyses are never mixed with a new run (stage cache keys wipe stale
artifacts on change).

## 4. Divide by time, not by token count

Long walkthroughs split at the **midpoint of the transcript timeline**, and each
half receives only the frame notes within its span (`slice_frames_by_ts`). The
transcript itself is shared to both halves for global context.

## 5. Parallel sections, fixed assembly

Sections (p1, p2, code, concepts, takeaways) run concurrently but assemble in a
fixed order. Each section is written to disk the moment it finishes — a crash loses
at most one section, and re-runs reuse the rest.

## 6. Depth presets are prompt sets, not code paths

`brief` / `standard` / `max` are lists of (section, template, timeline-half) specs.
Templates live in `vdesc/prompts/` as data; their content hash is part of stage
cache keys, so editing a prompt invalidates exactly the caches it affects.

## 7. Providers are adapters at the edges

- **ASR**: cloud-first (OpenAI-compatible transcription endpoint; Groq preset ships
  as the default) with chunking + overlap-stitching for long audio; local
  faster-whisper is an optional extra for private/offline use.
- **LLM**: one generic OpenAI-compatible chat client for vision and text; vendors
  differ only by config.

## 8. Everything expensive is cached; everything observable is recorded

- Stage keys = hash(inputs + provider/model + prompt versions + settings) stored in
  `meta.json`. Matching key + existing artifacts = skip. `--force` overrides.
- `usage.json` records every call: stage, model, tokens, audio seconds, elapsed
  time, and (when `[pricing]` rates are configured) estimated cost.

## 9. Secrets stay out of git

Config files reference environment variable *names* (`api_key_env`); keys are read
from the environment (`.env` supported, gitignored).
