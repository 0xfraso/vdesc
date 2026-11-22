"""vdesc — command-line interface.

Commands:
  describe    full pipeline: audio -> transcript -> frames -> vision -> description -> summary
  transcribe  audio + ASR only (transcript.txt/json/srt)
  summarize   one summary pass over an existing description.md
  doctor      check system deps, config and provider credentials
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import (Config, apply_cli_overrides, estimate_cost, load_config,
                     resolve_api_key)
from .media import (AUDIO_SPEC, FRAMES_SPEC, ensure_ffmpeg, extract_audio,
                    extract_frames, probe_duration)
from .prompts import prompt_version
from .providers.asr import resolve_asr
from .providers.llm import ChatClient
from .util import Timer, hash_json, is_url, load_dotenv, sha256_file, sha256_text, slugify
from .vision import analyze_frames
from .workspace import Workspace
from .writer import PRESETS, assemble, make_summary, run_sections

ALL_STAGES = ("audio", "transcript", "frames", "vision", "writer", "summary")


# ---------------------------------------------------------------- helpers
def _usage_recorder(ws: Workspace, cfg: Config):
    """Callback installed on ChatClients so every successful call is logged."""
    def cb(label: str, model: str, usage, elapsed: float) -> None:
        ws.add_usage({
            "stage": label,
            "model": model,
            "prompt_tokens": usage.prompt_tokens if usage else None,
            "completion_tokens": usage.completion_tokens if usage else None,
            "total_tokens": usage.total_tokens if usage else None,
            "est_cost_usd": estimate_cost(
                model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                pricing=cfg.pricing),
            "elapsed_s": round(elapsed, 1),
        })
    return cb


def _record_asr_usage(ws: Workspace, cfg: Config, *, model: str, audio_seconds: float,
                      elapsed: float) -> None:
    ws.add_usage({
        "stage": "transcribe",
        "model": model,
        "audio_seconds": round(audio_seconds, 2),
        "est_cost_usd": estimate_cost(model, audio_seconds=audio_seconds, pricing=cfg.pricing),
        "elapsed_s": round(elapsed, 1),
    })


def _make_chat_client(endpoint, what: str, *, label: str, ws: Workspace | None = None,
                      cfg: Config | None = None) -> ChatClient:
    if not (endpoint.base_url and endpoint.model):
        sys.exit(
            f"{what}: base_url/model are not configured. Set them for this endpoint in "
            f"config.toml (any OpenAI-compatible endpoint works)."
        )
    key = resolve_api_key(endpoint.api_key_env, what)
    return ChatClient(base_url=endpoint.base_url, model=endpoint.model, api_key=key,
                      label=label,
                      usage_cb=_usage_recorder(ws, cfg) if ws and cfg else None)


def _forced_stages(spec: str | None) -> set[str]:
    if not spec:
        return set()
    parts = {s.strip() for s in spec.split(",") if s.strip()}
    if "all" in parts:
        return set(ALL_STAGES)
    unknown = parts - set(ALL_STAGES)
    if unknown:
        sys.exit(f"--force: unknown stage(s): {', '.join(sorted(unknown))}. "
                 f"Valid: {', '.join(ALL_STAGES)}, all")
    return parts


def _fetch_url_title(url: str) -> str | None:
    try:
        import yt_dlp
    except ImportError:
        return None
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    return info.get("title")


def _resolve_source(ws: Workspace, inp: str, title: str | None
                    ) -> tuple[Path, str | None, str | None]:
    """Return (video_path, title, url). Downloads URLs into the workspace."""
    if is_url(inp):
        try:
            import yt_dlp
        except ImportError:
            sys.exit("URL input requires the youtube extra: pip install 'vdesc[youtube]'")
        if not title:
            title = _fetch_url_title(inp)
        cached = ws.source_video
        if ws.meta.get("source", {}).get("url") == inp and cached.exists():
            print(f"Reusing downloaded source: {cached.name}")
            return cached, title, inp
        print(f"Downloading {inp!r} (<=1080p)...")
        opts = {
            "format": "bv*[height<=1080]+ba/b",
            "merge_output_format": "mp4",
            "outtmpl": str(ws.root / "source.%(ext)s"),
            "quiet": True, "no_warnings": True, "noprogress": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(inp, download=True)
            path = Path(info["requested_downloads"][0]["filepath"])
        return path, title, inp
    p = Path(inp).expanduser()
    if not p.exists():
        sys.exit(f"input file not found: {p}")
    return p.resolve(), title, None


def _import_transcript(ws: Workspace, path: Path) -> None:
    from .providers.asr.base import Transcript
    tr = Transcript.from_timestamped_txt(path.read_text(encoding="utf-8"))
    if not tr.segments:
        sys.exit(f"no '[mm:ss - mm:ss] text' lines found in {path}")
    tr.save(ws.transcript_json.with_suffix(""))  # writes .json/.txt/.srt trio


def _print_totals(ws: Workspace) -> None:
    t = ws.usage_totals()
    cost = f"${t['est_cost_usd']:.4f}" if t["cost_known"] else "n/a (no [pricing] rates)"
    print(f"\nUsage: {t['calls']} calls, {t['prompt_tokens']:,} in / "
          f"{t['completion_tokens']:,} out tokens, {t['audio_seconds'] / 60.0:.1f} audio-min, "
          f"est cost {cost}")


def _fmt_duration(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


# ---------------------------------------------------------------- commands
def cmd_describe(a) -> None:
    cfg = load_config(a.config)
    apply_cli_overrides(cfg, a)
    forced = _forced_stages(a.force)
    ensure_ffmpeg()
    prompts_dir = cfg.prompts.dir

    slug_seed = a.title
    if not slug_seed:
        if is_url(a.input):
            slug_seed = _fetch_url_title(a.input)  # may be None without the extra
        else:
            slug_seed = Path(a.input).stem
    ws = Workspace(Path(cfg.pipeline.out_dir) / slugify(slug_seed or "video")).ensure()
    print(f"Workspace: {ws.root}")

    video, title, url = _resolve_source(ws, a.input, a.title)
    src_sha = sha256_file(video)
    duration = probe_duration(video)
    title = title or slugify(slug_seed or "video")
    ws.meta["source"] = {"path": str(video), "url": url, "title": title,
                         "sha256": src_sha, "duration": round(duration, 2)}
    ws.save()
    print(f"Source: {Path(video).name} ({_fmt_duration(duration)})")

    # --- 1. audio -------------------------------------------------------
    audio_key = hash_json({"v": 1, "sha": src_sha, "spec": AUDIO_SPEC})
    if "audio" in forced:
        ws.wipe_stage_artifacts("audio")
    if ws.stage_ready("audio", audio_key):
        audio = ws.audio_path
        print(f"Reusing audio: {audio.name}")
    else:
        t = Timer()
        audio = extract_audio(video, ws.root / "audio")
        ws.set_stage("audio", audio_key, path=str(audio), elapsed_s=round(t.elapsed(), 1))
        print(f"Audio extracted -> {audio.name} ({t.elapsed():.1f}s)")

    # --- 2. transcript --------------------------------------------------
    if a.transcript:  # import existing timestamped transcript, skip ASR entirely
        imp_key = hash_json({"v": 1, "imported": sha256_file(a.transcript)})
        if "transcript" in forced or ws.stage_key("transcript") != imp_key:
            ws.wipe_stage_artifacts("transcript")
            _import_transcript(ws, Path(a.transcript))
            ws.set_stage("transcript", imp_key, provider="imported")
            print(f"Transcript imported from {a.transcript}")
        else:
            print("Reusing imported transcript")
    else:
        asr = resolve_asr(cfg.asr, audio_codec="flac" if audio.suffix == ".flac" else "mp3")
        t_key = hash_json({"v": 1, "audio_sha": sha256_file(audio),
                           "provider": asr.provider_name, "model": asr.model,
                           "language": cfg.asr.language, "prompt": cfg.asr.prompt,
                           "chunk": cfg.asr.chunk_seconds, "overlap": cfg.asr.overlap_seconds})
        if "transcript" in forced:
            ws.wipe_stage_artifacts("transcript")
        if ws.stage_ready("transcript", t_key, ws.transcript_json, ws.transcript_txt):
            print(f"Reusing transcript: {ws.transcript_txt.name}")
        else:
            print(f"Transcribing with {asr.provider_name}:{asr.model} ...")
            t = Timer()
            tr = asr.transcribe(audio, language=cfg.asr.language, prompt=cfg.asr.prompt)
            tr.save(ws.transcript_json.with_suffix(""))
            ws.set_stage("transcript", t_key, provider=asr.provider_name, model=asr.model,
                         language=tr.language, segments=len(tr.segments),
                         audio_seconds=round(tr.audio_seconds, 1),
                         elapsed_s=round(t.elapsed(), 1))
            _record_asr_usage(ws, cfg, model=asr.model, audio_seconds=tr.audio_seconds,
                              elapsed=t.elapsed())
            print(f"Transcript: {len(tr.segments)} segments "
                  f"({tr.language or 'auto'}) in {t.elapsed():.1f}s")
    transcript_txt = ws.transcript_txt.read_text(encoding="utf-8")

    # --- 3. frames ------------------------------------------------------
    f_key = hash_json({"v": 1, "sha": src_sha, "interval": cfg.pipeline.frame_interval,
                       "spec": FRAMES_SPEC, "max_width": cfg.pipeline.max_width})
    if "frames" in forced or ws.stage_key("frames") != f_key:
        ws.wipe_stage_artifacts("frames")
    if ws.stage_ready("frames", f_key, ws.frames_json):
        raw = json.loads(ws.frames_json.read_text(encoding="utf-8"))
        frames = [(r["t"], Path(r["path"])) for r in raw]
        print(f"Reusing {len(frames)} frames")
    else:
        frames = extract_frames(video, ws.frames_dir, cfg.pipeline.frame_interval,
                                cfg.pipeline.max_width)
        ws.frames_json.write_text(json.dumps(
            [{"t": t, "path": str(p)} for t, p in frames]), encoding="utf-8")
        ws.set_stage("frames", f_key, count=len(frames),
                     interval=cfg.pipeline.frame_interval, max_width=cfg.pipeline.max_width)
        print(f"Extracted {len(frames)} frames (every {cfg.pipeline.frame_interval}s)")
    if not frames:
        sys.exit("no frames extracted")

    # --- 4. vision ------------------------------------------------------
    vclient = _make_chat_client(cfg.vision, "vision endpoint", label="vision", ws=ws, cfg=cfg)
    v_key = hash_json({"v": 1, "frames": f_key, "model": cfg.vision.model,
                       "base_url": cfg.vision.base_url, "context": cfg.pipeline.context,
                       "per_call": cfg.pipeline.frames_per_call,
                       "prompt": prompt_version(["vision_frames"], prompts_dir)})
    if "vision" in forced or ws.stage_key("vision") != v_key:
        ws.wipe_stage_artifacts("vision")
    vision_before = ws.count_usage("vision")
    frame_notes = analyze_frames(frames, ws.vision_dir, client=vclient,
                                 context=cfg.pipeline.context,
                                 per_call=cfg.pipeline.frames_per_call,
                                 workers=cfg.pipeline.vision_workers,
                                 custom_prompts_dir=prompts_dir)
    ws.frames_md.write_text(frame_notes, encoding="utf-8")
    new_calls = ws.count_usage("vision") - vision_before
    ws.set_stage("vision", v_key, chars=len(frame_notes))
    print(f"Frame analyses -> {ws.frames_md.name} ({len(frame_notes):,} chars, "
          f"{new_calls} vision call(s) this run)")

    # --- 5. writer ------------------------------------------------------
    wclient = _make_chat_client(cfg.text, "text endpoint", label="writer", ws=ws, cfg=cfg)
    depth = cfg.pipeline.depth
    if depth not in PRESETS:
        sys.exit(f"unknown depth preset '{depth}'. Valid: {', '.join(PRESETS)}")
    templates = [t for _, t, _ in PRESETS[depth]]
    w_key = hash_json({"v": 1, "transcript": sha256_text(transcript_txt),
                       "notes": sha256_text(frame_notes), "preset": depth,
                       "model": cfg.text.model, "base_url": cfg.text.base_url,
                       "prompts": prompt_version(templates, prompts_dir)})
    if "writer" in forced or ws.stage_key("writer") != w_key:
        ws.wipe_stage_artifacts("writer")
    timer = Timer()
    results = run_sections(ws.sections_dir, wclient, preset=depth, title=title,
                           duration_hint=f"{_fmt_duration(duration)} minutes",
                           transcript_txt=transcript_txt, frame_notes=frame_notes,
                           custom_prompts_dir=prompts_dir,
                           workers=cfg.pipeline.writer_workers,
                           force="writer" in forced)
    doc = assemble(depth, results)
    ws.description_md.write_text(doc, encoding="utf-8")
    ws.set_stage("writer", w_key, preset=depth, words=len(doc.split()))
    print(f"Description -> {ws.description_md.name} ({len(doc.split()):,} words, "
          f"{timer.elapsed():.0f}s)")

    # --- 6. summary -----------------------------------------------------
    if not a.no_summary:
        target = cfg.pipeline.summary_words
        s_key = hash_json({"v": 1, "desc": sha256_text(doc), "words": target,
                           "model": cfg.text.model, "base_url": cfg.text.base_url,
                           "prompt": prompt_version(["summary"], prompts_dir)})
        if "summary" in forced or not ws.stage_ready("summary", s_key, ws.summary_md):
            print("Generating summary...")
            wclient.label = "summary"
            timer = Timer()
            summary = make_summary(wclient, doc, target, prompts_dir)
            ws.summary_md.write_text(summary, encoding="utf-8")
            ws.set_stage("summary", s_key, words=len(summary.split()))
            print(f"Summary -> {ws.summary_md.name} ({len(summary.split()):,} words, "
                  f"{timer.elapsed():.0f}s)")
        else:
            print(f"Reusing summary: {ws.summary_md.name}")

    _print_totals(ws)
    print(f"Done. Outputs in {ws.root}/")


def cmd_transcribe(a) -> None:
    cfg = load_config(a.config)
    apply_cli_overrides(cfg, a)
    forced = _forced_stages(a.force)
    ensure_ffmpeg()

    if is_url(a.input):
        sys.exit("'transcribe' takes a local file; use 'describe' for URLs "
                 "(it downloads and transcribes in one pass).")
    video = Path(a.input).expanduser()
    if not video.exists():
        sys.exit(f"input file not found: {video}")
    ws = Workspace(Path(a.out or cfg.pipeline.out_dir)
                   / slugify(a.title or video.stem)).ensure()
    duration = probe_duration(video)

    audio_key = hash_json({"v": 1, "sha": sha256_file(video), "spec": AUDIO_SPEC})
    if "audio" in forced or not ws.stage_ready("audio", audio_key):
        audio = extract_audio(video, ws.root / "audio")
        ws.set_stage("audio", audio_key, path=str(audio))
    else:
        audio = ws.audio_path

    asr = resolve_asr(cfg.asr, audio_codec="flac" if audio.suffix == ".flac" else "mp3")
    t_key = hash_json({"v": 1, "audio_sha": sha256_file(audio), "provider": asr.provider_name,
                       "model": asr.model, "language": cfg.asr.language,
                       "prompt": cfg.asr.prompt, "chunk": cfg.asr.chunk_seconds,
                       "overlap": cfg.asr.overlap_seconds})
    if "transcript" in forced or not ws.stage_ready("transcript", t_key,
                                                   ws.transcript_json, ws.transcript_txt):
        print(f"Transcribing {video.name} ({_fmt_duration(duration)}) with "
              f"{asr.provider_name}:{asr.model} ...")
        t = Timer()
        tr = asr.transcribe(audio, language=cfg.asr.language, prompt=cfg.asr.prompt)
        tr.save(ws.transcript_json.with_suffix(""))
        ws.set_stage("transcript", t_key, provider=asr.provider_name, model=asr.model,
                     language=tr.language, segments=len(tr.segments),
                     audio_seconds=round(tr.audio_seconds, 1), elapsed_s=round(t.elapsed(), 1))
        _record_asr_usage(ws, cfg, model=asr.model, audio_seconds=tr.audio_seconds,
                          elapsed=t.elapsed())
        print(f"Done: {len(tr.segments)} segments ({tr.language or 'auto'}) "
              f"in {t.elapsed():.1f}s -> {ws.transcript_txt}")
        _print_totals(ws)
    else:
        print(f"Cached transcript: {ws.transcript_txt}")


def cmd_summarize(a) -> None:
    cfg = load_config(a.config)
    src = Path(a.input).expanduser()
    if not src.exists():
        sys.exit(f"input file not found: {src}")
    ws = Workspace(src.parent).ensure() if (src.parent / "meta.json").exists() else None
    client = _make_chat_client(cfg.text, "text endpoint", label="summary", ws=ws, cfg=cfg)
    doc = src.read_text(encoding="utf-8")
    out = Path(a.out) if a.out else src.parent / "summary.md"
    print(f"Summarizing {src.name} ({len(doc.split()):,} words) -> {out.name} ...")
    t = Timer()
    summary = make_summary(client, doc, a.words or cfg.pipeline.summary_words, cfg.prompts.dir)
    if not summary.lstrip().startswith("#"):
        summary = f"# {a.title or src.parent.name} - Technical Summary\n\n{summary}"
    out.write_text(summary, encoding="utf-8")
    print(f"Saved {len(summary.split()):,} words in {t.elapsed():.0f}s")
    if ws:
        _print_totals(ws)


def _stale_venv_scripts(bin_dir: Path) -> list[Path]:
    stale: list[Path] = []
    for script in sorted(bin_dir.glob("*")):
        if not script.is_file():
            continue
        with script.open("rb") as fh:
            first = fh.readline()
        if not first.startswith(b"#!"):
            continue
        words = first[2:].split()
        if not words or not Path(words[0].decode("utf-8", "replace")).exists():
            stale.append(script)
    return stale


def cmd_doctor(a) -> None:
    cfg = load_config(a.config)
    print(f"vdesc {__version__}")
    print(f"config: {cfg.config_path or '(defaults only — no config file found)'}")

    ensure_ffmpeg()
    print("ffmpeg/ffprobe: ok")

    stale = _stale_venv_scripts(Path(sys.executable).parent)
    print(f"venv: {len(stale)} stale script(s) — run scripts/bootstrap.sh"
          if stale else "venv: ok")

    name = cfg.asr.provider
    if name == "auto":
        guess = "groq" if os.environ.get("GROQ_API_KEY") else "local (if installed)"
        print(f"ASR provider 'auto' -> would select: {guess}")
    else:
        print(f"ASR provider: {name}")
    env_name = cfg.asr.api_key_env or (
        {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY"}.get(name, "ASR_API_KEY"))
    if name in ("groq", "openai", "custom", "auto"):
        state = "set" if os.environ.get(env_name) else "MISSING"
        print(f"  ASR key env {env_name}: {state}")
    try:
        import faster_whisper  # noqa: F401
        print("  faster-whisper (local extra): installed")
    except ImportError:
        print("  faster-whisper (local extra): not installed")

    for label, ep in (("vision", cfg.vision), ("text", cfg.text)):
        state = "ok" if (ep.base_url and ep.model) else "NOT CONFIGURED"
        key_state = "set" if os.environ.get(ep.api_key_env) else "MISSING"
        print(f"{label}: {state} (model={ep.model or '-'}, {ep.api_key_env}={key_state}, "
              f"base_url={ep.base_url or '-'})")

    if a.probe:
        _probe(cfg)


def _probe(cfg: Config) -> None:
    print("\nProbing providers with tiny requests...")
    client = _make_chat_client(cfg.text, "text endpoint", label="probe")
    r = client.complete(user="Reply with the single word: ok")
    print(f"  text:   {r.model} -> {r.text[:40]!r}")

    vclient = _make_chat_client(cfg.vision, "vision endpoint", label="probe")
    px = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
          "AAAABJRU5ErkJggg==")  # 1x1 red PNG
    r = vclient.complete(user=[
        {"type": "text", "text": "What color is this pixel? One word."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{px}"}},
    ])
    print(f"  vision: {r.model} -> {r.text[:40]!r}")

    asr = resolve_asr(cfg.asr)
    with __import__("tempfile").TemporaryDirectory() as td:
        wav = Path(td) / "probe.wav"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-ar", "16000", "-ac", "1", str(wav)], check=True, capture_output=True)
        tr = asr.transcribe(wav)
        print(f"  asr:    {asr.provider_name}:{asr.model} -> {len(tr.segments)} segment(s)")


# ---------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vdesc",
                                 description="Slim video-description pipeline")
    ap.add_argument("--version", action="version", version=f"vdesc {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--config", help="path to config.toml (default: ./config.toml or "
                                        "~/.config/vdesc/config.toml)")

    d = sub.add_parser("describe", help="full pipeline on a video file or URL")
    d.add_argument("input")
    d.add_argument("--depth", choices=list(PRESETS))
    d.add_argument("--title", help="override video title (slug + document title)")
    d.add_argument("--context", help="domain hint for the vision model")
    d.add_argument("--frame-interval", type=int)
    d.add_argument("--max-width", type=int)
    d.add_argument("--frames-per-call", type=int)
    d.add_argument("--vision-workers", type=int)
    d.add_argument("--writer-workers", type=int)
    d.add_argument("--summary-words", type=int)
    d.add_argument("--asr", dest="asr_provider",
                   help="groq | openai | custom | local | auto (overrides config)")
    d.add_argument("--language", help="ISO-639-1 language hint, or 'auto'")
    d.add_argument("--asr-prompt", help="vocabulary hint for ASR (~224 token limit)")
    d.add_argument("--transcript", help="import an existing [mm:ss - mm:ss] transcript "
                                        "file instead of running ASR")
    d.add_argument("--out", help="output root dir (default from config, 'out')")
    d.add_argument("--force", help="comma list of stages to redo: audio,transcript,frames,"
                                   "vision,writer,summary,all")
    d.add_argument("--no-summary", action="store_true")
    common(d)
    d.set_defaults(func=cmd_describe)

    t = sub.add_parser("transcribe", help="transcribe a local video/audio file")
    t.add_argument("input")
    t.add_argument("--title")
    t.add_argument("--asr", dest="asr_provider")
    t.add_argument("--language")
    t.add_argument("--asr-prompt")
    t.add_argument("--out", help="output root dir (default from config, 'out')")
    t.add_argument("--force")
    common(t)
    t.set_defaults(func=cmd_transcribe)

    s = sub.add_parser("summarize", help="summary pass over an existing description.md")
    s.add_argument("input")
    s.add_argument("--title")
    s.add_argument("--words", type=int)
    s.add_argument("--out")
    common(s)
    s.set_defaults(func=cmd_summarize)

    doc = sub.add_parser("doctor", help="check deps, config and credentials")
    doc.add_argument("--probe", action="store_true",
                     help="send tiny live requests to text/vision/ASR endpoints")
    common(doc)
    doc.set_defaults(func=cmd_doctor)
    return ap


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    load_dotenv()
    args.func(args)


if __name__ == "__main__":
    main()
