"""Small shared helpers: hashing, env loading, time formatting, slugify."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

DEFAULT_DOTENV_PATHS = (Path(".env"), Path.home() / ".vdesc" / ".env")


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_json(obj) -> str:
    """Stable cache key from any JSON-serializable object."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_dotenv(paths=DEFAULT_DOTENV_PATHS) -> list[Path]:
    """Set KEY=VALUE pairs into os.environ without clobbering existing values."""
    loaded = []
    for p in paths:
        path = Path(p).expanduser()
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        loaded.append(path)
    return loaded


def fmt_ts(seconds: float) -> str:
    """mm:ss (minutes grow past 2 digits for long videos)."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:60].rstrip("-") or "video"


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip()))


def retry_sleep(exc: Exception) -> float | None:
    """Extract Retry-After (seconds) from an OpenAI SDK error, if present."""
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") if hasattr(headers, "get") else None
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


class Timer:
    def __init__(self) -> None:
        self.t0 = time.time()

    def elapsed(self) -> float:
        return time.time() - self.t0
