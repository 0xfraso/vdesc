"""Writer stage: merges transcript + frame notes into the final documents.

Design principles carried over from the original pipeline:
- The transcript is the timeline spine; frame notes are visual ground truth.
  The writer merges and never invents.
- Walkthroughs divide by time (midpoint split), and each half only sees the
  frame notes within its span.
- Sections run in parallel but assemble in a fixed order.
- Each section is persisted as soon as it finishes, so a crash loses at most
  one section; existing section files are reused on resume.
"""
from __future__ import annotations

import concurrent.futures
import re
from dataclasses import dataclass

from .providers.llm import ChatClient
from .prompts import load_prompt
from .util import Timer, fmt_ts

WRITER_SYSTEM = (
    "You are a meticulous technical writer producing exhaustive, accurate video breakdowns. "
    "Never invent facts; ground everything in the provided transcript and frame analyses."
)

# (section file key, prompt template, timeline half) — assembly order is list order.
PRESETS: dict[str, list[tuple[str, str, int | None]]] = {
    "brief": [
        ("document", "sections/document", None),
    ],
    "standard": [
        ("p1", "sections/p1", 1),
        ("p2", "sections/p2", 2),
        ("code", "sections/code", None),
        ("concepts_takeaways", "sections/concepts_takeaways", None),
    ],
    "max": [
        ("p1", "sections/p1", 1),
        ("p2", "sections/p2", 2),
        ("code", "sections/code", None),
        ("concepts", "sections/concepts", None),
        ("takeaways", "sections/takeaways", None),
    ],
}

CONTEXT_TEMPLATE = """
=== TIMESTAMPED TRANSCRIPT ===
{transcript}

=== FRAME-BY-FRAME VISUAL ANALYSES (code transcribed verbatim from screen) ===
{frame_notes}
"""

FRAME_SECTION_RE = re.compile(r"^## Frame @ (\d{2,}):(\d{2})", re.M)
TRANSCRIPT_MARKER_RE = re.compile(r"\[(\d{2,}):(\d{2}) - ")


def midpoint_seconds(transcript_txt: str) -> float | None:
    """Midpoint of the transcript timeline (used to split walkthroughs)."""
    markers = TRANSCRIPT_MARKER_RE.findall(transcript_txt)
    if not markers:
        return None
    mm, ss = markers[len(markers) // 2]
    return int(mm) * 60 + int(ss)


def slice_frames_by_ts(frame_notes: str, start_s: float, end_s: float) -> str:
    """Keep only '## Frame @ mm:ss' sections whose timestamp falls in [start_s, end_s)."""
    parts = re.split(r"(?=## Frame @ \d{2,}:\d{2})", frame_notes)
    kept: list[str] = []
    for part in parts:
        m = FRAME_SECTION_RE.match(part)
        if not m:
            continue
        t = int(m.group(1)) * 60 + int(m.group(2))
        if start_s <= t < end_s:
            kept.append(part)
    return "".join(kept)


def build_context(transcript_txt: str, frame_notes: str, half: int | None,
                  mid: float | None) -> str:
    notes = frame_notes
    if half and mid is not None:
        notes = slice_frames_by_ts(frame_notes, 0, mid) if half == 1 \
            else slice_frames_by_ts(frame_notes, mid, float("inf"))
    return CONTEXT_TEMPLATE.format(transcript=transcript_txt, frame_notes=notes)


@dataclass
class SectionJob:
    key: str
    prompt: str


def run_sections(sections_dir: Path, client: ChatClient, *, preset: str, title: str,
                 duration_hint: str, transcript_txt: str, frame_notes: str,
                 custom_prompts_dir: str | None, workers: int = 3, force: bool = False,
                 log=print) -> dict[str, str]:
    specs = PRESETS[preset]
    sections_dir.mkdir(parents=True, exist_ok=True)
    mid = midpoint_seconds(transcript_txt)
    split = f"about [{fmt_ts(mid)}]" if mid is not None else "the middle of the video"

    results: dict[str, str] = {}
    prompts: dict[str, str] = {}
    out_paths: dict[str, Path] = {}
    for key, template, half in specs:
        out = sections_dir / f"{key}.md"
        if not force and out.exists() and out.stat().st_size > 0:
            results[key] = out.read_text(encoding="utf-8")
            continue
        head = load_prompt(template, custom_prompts_dir).format(
            title=title, duration=duration_hint, split=split)
        prompts[key] = head + "\n" + build_context(transcript_txt, frame_notes, half, mid)
        out_paths[key] = out

    if prompts:
        log(f"Writing {len(prompts)}/{len(specs)} section(s) in parallel (preset={preset})...")
        timer = Timer()
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(_run_job, client, key, prompts[key], out_paths[key], log): key
                       for key in prompts}
            for fut in concurrent.futures.as_completed(futures):
                key = futures[fut]
                results[key] = fut.result()
                log(f"  section '{key}' done ({timer.elapsed():.0f}s)")
    else:
        log(f"All {len(specs)} section(s) already present — reusing.")
    return results


def _run_job(client: ChatClient, key: str, prompt: str, out: Path, log=print) -> str:
    # One retry layer beyond the client's transport-level retries: the coding
    # endpoints occasionally return odd transient bodies under load.
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            result = client.complete(system=WRITER_SYSTEM, user=prompt)
            out.write_text(result.text, encoding="utf-8")
            return result.text
        except Exception as exc:
            last_exc = exc
            log(f"  section '{key}' attempt {attempt + 1} failed: {exc}")
    raise RuntimeError(f"section '{key}' failed after retries: {last_exc}") from last_exc


def assemble(preset: str, results: dict[str, str]) -> str:
    return "\n\n".join(results[key] for key, _, _ in PRESETS[preset])


def make_summary(client: ChatClient, description: str, target_words: int,
                 custom_prompts_dir: str | None) -> str:
    template = load_prompt("summary", custom_prompts_dir).format(target_words=target_words)
    prompt = template + "\n\n=== SOURCE DOCUMENT ===\n" + description
    result = client.complete(user=prompt)
    return result.text
