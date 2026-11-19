"""Media helpers: probing, audio extraction, frame sampling. ffmpeg is the only system dependency."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .util import Timer

# Included in stage cache keys so changing the recipe invalidates artifacts.
AUDIO_SPEC = "mp3/16k/mono/48k"
FLAC_SPEC = "flac/16k/mono"
FRAMES_SPEC = "jpg/q2"


def ensure_ffmpeg() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if not shutil.which(t)]
    if missing:
        sys.exit(f"missing system dependency: {', '.join(missing)}. Install ffmpeg and retry.")


def probe_duration(path: str | os.PathLike) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def _audio_encoder_args(codec: str) -> list[str]:
    if codec == "flac":
        return ["-c:a", "flac"]
    return ["-c:a", "libmp3lame", "-b:a", "48k"]


def extract_audio(video: Path, out_base: Path, codec: str = "mp3") -> Path:
    """16 kHz mono audio next to the workspace root. Falls back to flac if libmp3lame is absent."""
    out_base.parent.mkdir(parents=True, exist_ok=True)
    ext = ".mp3" if codec == "mp3" else ".flac"
    out = out_base.with_suffix(ext)
    cmd = ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
           *_audio_encoder_args(codec), str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        if codec == "mp3" and "libmp3lame" in (proc.stderr or ""):
            return extract_audio(video, out_base, codec="flac")
        sys.exit(f"ffmpeg audio extraction failed:\n{proc.stderr[-1500:]}")
    return out


def cut_audio(src: Path, dst: Path, start: float, duration: float, codec: str = "mp3") -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{duration:.3f}",
           "-vn", "-ac", "1", "-ar", "16000", *_audio_encoder_args(codec), str(dst)]
    subprocess.run(cmd, check=True, capture_output=True)


def extract_frames(video: Path, frames_dir: Path, interval: int, max_width: int
                   ) -> list[tuple[float, Path]]:
    """One frame every `interval` seconds, scaled to at most max_width wide.

    Timestamps are nominal (frame i -> i * interval); the fps filter samples at
    that grid, which is accurate enough for description purposes.
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in glob.glob(str(frames_dir / "*.jpg")):
        os.remove(old)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vf",
         f"fps=1/{interval},scale='min({max_width},iw)':-2", "-q:v", "2",
         str(frames_dir / "frame_%05d.jpg")],
        check=True, capture_output=True,
    )
    frames = sorted(glob.glob(str(frames_dir / "frame_*.jpg")))
    return [(i * interval, Path(f)) for i, f in enumerate(frames)]
