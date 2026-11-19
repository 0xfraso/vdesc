"""Per-run workspace: one directory per video, a meta manifest with stage
cache keys, and a usage ledger.

Every expensive stage stores a cache key derived from its inputs (input hash +
provider/model + prompt version + relevant settings). If the key matches
`meta.json` and the artifacts exist, the stage is skipped. `--force <stage>`
ignores the cache; a changed key means artifacts from the old run are wiped so
partial artifacts (vision batches, writer sections) can never be mixed across
runs.
"""
from __future__ import annotations

import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

META_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.meta_path = self.root / "meta.json"
        self.usage_path = self.root / "usage.json"
        self.meta: dict = {"version": META_VERSION, "stages": {}, "usage": []}
        if self.meta_path.exists():
            saved = json.loads(self.meta_path.read_text(encoding="utf-8"))
            self.meta = {**self.meta, **saved, "stages": saved.get("stages", {})}
        self._usage: list[dict] = list(self.meta.get("usage", []))
        if self.usage_path.exists():  # usage.json is the source of truth if present
            self._usage = json.loads(self.usage_path.read_text(encoding="utf-8"))
            self.meta["usage"] = self._usage

    # ------------------------------------------------------------ lifecycle
    def ensure(self) -> "Workspace":
        self.root.mkdir(parents=True, exist_ok=True)
        return self

    def save(self) -> None:
        self.meta["updated"] = _now()
        self.meta_path.write_text(json.dumps(self.meta, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ paths
    @property
    def source_video(self) -> Path:
        return self.root / "source.mp4"

    @property
    def audio_path(self) -> Path:
        info = self.stage_info("audio") or {}
        return Path(info["path"]) if info.get("path") else self.root / "audio.mp3"

    @property
    def transcript_json(self) -> Path:
        return self.root / "transcript.json"

    @property
    def transcript_txt(self) -> Path:
        return self.root / "transcript.txt"

    @property
    def transcript_srt(self) -> Path:
        return self.root / "transcript.srt"

    @property
    def frames_dir(self) -> Path:
        return self.root / "frames"

    @property
    def frames_json(self) -> Path:
        return self.root / "frames.json"

    @property
    def frames_md(self) -> Path:
        return self.root / "frames.md"

    @property
    def vision_dir(self) -> Path:
        return self.root / "vision"

    @property
    def sections_dir(self) -> Path:
        return self.root / "sections"

    @property
    def description_md(self) -> Path:
        return self.root / "description.md"

    @property
    def summary_md(self) -> Path:
        return self.root / "summary.md"

    # ------------------------------------------------------------ stages
    def stage_info(self, stage: str) -> dict | None:
        return self.meta.get("stages", {}).get(stage)

    def stage_key(self, stage: str) -> str | None:
        info = self.stage_info(stage)
        return info.get("key") if info else None

    def stage_ready(self, stage: str, key: str, *required: Path) -> bool:
        info = self.stage_info(stage)
        if not info or info.get("key") != key:
            return False
        return all(p.exists() for p in required)

    def set_stage(self, stage: str, key: str, **extra) -> None:
        self.meta.setdefault("stages", {})[stage] = {"key": key, "updated": _now(), **extra}
        self.save()

    def wipe_stage_artifacts(self, stage: str) -> None:
        """Remove the partial artifacts of a stage so a re-run starts clean."""
        dirs = {"vision": self.vision_dir, "writer": self.sections_dir}
        if stage in dirs and dirs[stage].exists():
            shutil.rmtree(dirs[stage])
        files = {
            "audio": [self.root / "audio.mp3", self.root / "audio.flac"],
            "transcript": [self.transcript_json, self.transcript_txt, self.transcript_srt],
            "frames": [self.frames_json],
            "vision": [self.frames_md],
            "writer": [self.description_md],
            "summary": [self.summary_md],
        }
        for f in files.get(stage, []):
            f.unlink(missing_ok=True)

    # ------------------------------------------------------------ usage
    def _write_usage_file(self) -> None:
        self.usage_path.write_text(json.dumps(self._usage, indent=1), encoding="utf-8")

    def add_usage(self, record: dict) -> None:
        record = {"ts": _now(), **record}
        self._usage.append(record)
        self.meta["usage"] = self._usage
        self._write_usage_file()
        self.save()

    def count_usage(self, stage: str) -> int:
        return sum(1 for r in self._usage if r.get("stage") == stage)

    def usage_totals(self) -> dict:
        totals = {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "audio_seconds": 0.0, "est_cost_usd": 0.0, "cost_known": False,
            "wall_seconds": 0.0,
        }
        for r in self._usage:
            totals["calls"] += 1
            totals["prompt_tokens"] += r.get("prompt_tokens") or 0
            totals["completion_tokens"] += r.get("completion_tokens") or 0
            totals["audio_seconds"] += r.get("audio_seconds") or 0.0
            totals["wall_seconds"] += r.get("elapsed_s") or 0.0
            cost = r.get("est_cost_usd")
            if cost is not None:
                totals["est_cost_usd"] += cost
                totals["cost_known"] = True
        return totals
