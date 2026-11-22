# vdesc

A slim video-description pipeline distilled from the VideoAgent project: produce an
exhaustive, code-faithful markdown breakdown of a technical video from two evidence
streams — a speech transcript and vision-model OCR of sampled frames.

```
file/URL ──► 16 kHz mono audio ──► ASR (Groq cloud, or local faster-whisper)
             │                          └► transcript.txt / .json / .srt
             └► frames every N s ──► vision model: scene + VERBATIM code per frame
                                          └► frames.md
transcript + frames.md ──► parallel writer sections ──► description.md ──► summary.md
```

## Install

```bash
uv venv .venv && uv pip install -e ".[dev]" --python .venv/bin/python
# optional extras:
uv pip install -e ".[local,youtube]"   # local faster-whisper ASR, YouTube URLs
```

After moving or renaming the repo, run `bash scripts/bootstrap.sh`. A venv
hardcodes its birth path in shebangs and editable-install `.pth` files, so the
old one goes stale; the script detects that and recreates the venv, and is
safe to rerun any time. `vdesc doctor` reports the same condition.

System dependency: `ffmpeg`.

## Configure

```bash
cp config.example.toml config.toml   # gitignored; set endpoints/models
cp .env.example .env                 # API keys (never committed)
vdesc doctor --probe                 # verify everything with tiny live requests
```

Providers are generic OpenAI-compatible endpoints — set `base_url`, `model`, and
`api_key_env` per endpoint in `config.toml`:

| Endpoint | Examples |
|---|---|
| `[asr]` | `provider = "groq"` (free tier: ~8 h audio/day, 25 MB/upload, $0.04/audio-hour paid), `"openai"`, `"custom"`, `"local"` (faster-whisper), `"auto"` (Groq if key present, else local) |
| `[vision]` | must be a **vision-capable** model (e.g. z.ai `glm-5.3-flash`, OpenAI `gpt-4.1`) |
| `[text]` | any text model for the long-form writer |

## Use

```bash
vdesc describe video.mp4                        # full pipeline, standard depth
vdesc describe video.mp4 --depth max            # exhaustive 7-section document
vdesc describe https://youtu.be/... --depth max # downloads (<=1080p), then runs
vdesc describe video.mp4 --transcript old.txt   # reuse an existing [mm:ss - mm:ss] transcript
vdesc transcribe video.mp4                      # ASR only -> transcript.txt/json/srt
vdesc summarize out/<slug>/description.md       # re-run just the summary pass
```

Useful flags: `--force vision,writer` (redo stages), `--no-summary`,
`--asr-prompt "Unity, HLSL, G-buffer"` (vocabulary hint), `--context "..."` (domain hint
for the vision model), `--frame-interval`, `--language`.

## Output layout

```
out/<slug>/
├─ meta.json        # source info + per-stage cache keys
├─ usage.json       # per-call token/audio/cost ledger
├─ source.mp4       # (URL inputs only)
├─ audio.mp3        # 16 kHz mono, 48 kbps
├─ transcript.txt   # [mm:ss - mm:ss] lines
├─ transcript.json  # canonical segments
├─ transcript.srt
├─ frames/          # sampled frames
├─ frames.json
├─ frames.md        # merged per-frame vision analyses
├─ vision/          # per-batch raw vision outputs (cache)
├─ sections/        # per-section writer outputs (cache)
├─ description.md
└─ summary.md
```

Every stage is cached by a content key (input hash + model + prompt version +
settings). Re-runs skip finished work — including individual vision batches and
writer sections — so failures resume instead of restarting. `--force <stages>`
invalidates deliberately.

## Depth presets

| Preset | Writer calls | Result |
|---|---|---|
| `brief` | 1 | 2–3k words: overview, condensed walkthrough, key code, takeaways |
| `standard` | 4 | 8–12k words: walkthrough halves, code deep-dive, concepts + takeaways |
| `max` | 5 | 20–30k words: exhaustive 7-section document with glossary |

## Tests

```bash
.venv/bin/python -m pytest -q
```

See `DESIGN.md` for the principles this tool encodes.

---

## Credits

`vdesc` was distilled from the describe-video pipeline we built on top of
[VideoAgent](https://github.com/HKUDS/VideoAgent) (HKUDS) — the transcript +
frame-OCR + grounded-writer flow and its prompts originated there.

## License

[MIT](LICENSE)

