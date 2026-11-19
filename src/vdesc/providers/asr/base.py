"""ASR data model and chunking/stitching math (pure functions, unit-tested).

Cloud ASR endpoints cap upload size and/or duration, so long audio is cut into
overlapping chunks, transcribed independently, and stitched: each chunk k>0
overlaps the previous one by `overlap_seconds`, and segments that begin inside
the overlap region (before the chunk's "fresh boundary") are dropped.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ...util import fmt_ts, srt_ts


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None
    duration: float = 0.0
    provider: str = ""
    model: str = ""
    audio_seconds: float = 0.0  # seconds actually sent for transcription (for cost/quota)

    def timestamped_text(self) -> str:
        lines = [f"[{fmt_ts(s.start)} - {fmt_ts(s.end)}] {s.text.strip()}" for s in self.segments]
        return "\n".join(lines)

    def plain_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments).strip()

    def to_json(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "duration": self.duration,
            "audio_seconds": self.audio_seconds,
            "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in self.segments],
        }

    @classmethod
    def from_json(cls, data: dict) -> "Transcript":
        return cls(
            segments=[Segment(**s) for s in data.get("segments", [])],
            language=data.get("language"),
            duration=data.get("duration") or 0.0,
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            audio_seconds=data.get("audio_seconds") or 0.0,
        )

    @classmethod
    def from_timestamped_txt(cls, text: str, provider: str = "imported") -> "Transcript":
        """Parse `[mm:ss - mm:ss] text` lines (e.g. transcripts from older runs)."""
        import re

        pat = re.compile(r"^\[(\d{2,}):(\d{2}) - (\d{2,}):(\d{2})\]\s*(.*)$")
        segments: list[Segment] = []
        for line in text.splitlines():
            m = pat.match(line.strip())
            if not m:
                continue
            m1, s1, m2, s2, body = m.groups()
            start = int(m1) * 60 + int(s1)
            end = int(m2) * 60 + int(s2)
            if body.strip():
                segments.append(Segment(start=start, end=max(end, start), text=body.strip()))
        return cls(segments=segments, provider=provider, model="imported",
                   duration=segments[-1].end if segments else 0.0,
                   audio_seconds=0.0)

    def to_srt(self) -> str:
        blocks = []
        for i, s in enumerate(self.segments, 1):
            blocks.append(f"{i}\n{srt_ts(s.start)} --> {srt_ts(s.end)}\n{s.text.strip()}\n")
        return "\n".join(blocks)

    def save(self, base: Path) -> None:
        base.with_suffix(".json").write_text(
            json.dumps(self.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        base.with_suffix(".txt").write_text(self.timestamped_text() + "\n", encoding="utf-8")
        base.with_suffix(".srt").write_text(self.to_srt(), encoding="utf-8")


def chunk_plan(duration: float, chunk_seconds: float, overlap: float) -> list[tuple[float, float]]:
    """[(start, length), ...] with each chunk k>0 starting `overlap` before its fresh region.

    Chunk k's fresh region is [k*chunk_seconds, (k+1)*chunk_seconds).
    """
    if duration <= 0:
        return [(0.0, 0.0)]
    if duration <= chunk_seconds:
        return [(0.0, duration)]
    plan = [(0.0, chunk_seconds)]
    k = 1
    while k * chunk_seconds < duration:
        start = max(0.0, k * chunk_seconds - overlap)
        end = min((k + 1) * chunk_seconds, duration)
        plan.append((start, end - start))
        k += 1
    return plan


def fresh_boundaries(plan: list[tuple[float, float]], chunk_seconds: float) -> list[float]:
    """Absolute start of each chunk's fresh region (chunk 0 -> 0.0)."""
    return [0.0] + [k * chunk_seconds for k in range(1, len(plan))]


def stitch(batches: list[list[Segment]], boundaries: list[float]) -> list[Segment]:
    """Concatenate per-chunk segments, dropping segments that begin inside the
    previous chunk's overlap region, plus exact duplicates at seams."""
    out: list[Segment] = []
    for k, segs in enumerate(batches):
        boundary = boundaries[k] if k < len(boundaries) else None
        for seg in segs:
            if not seg.text.strip():
                continue
            if boundary is not None and seg.start < boundary - 1e-6:
                continue
            if out and abs(seg.start - out[-1].start) < 0.05 and seg.text == out[-1].text:
                continue
            out.append(seg)
    return out
