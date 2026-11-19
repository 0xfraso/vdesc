"""Cloud ASR via any OpenAI-compatible audio transcription endpoint.

Groq is the flagship preset (fast LPU inference, generous free tier); the same
code path serves OpenAI or any custom endpoint — only base_url/model/key
change. Long audio is cut into overlapping chunks (see base.chunk_plan),
transcribed sequentially with retries honoring Retry-After, then stitched.
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from ...media import cut_audio, probe_duration
from ...util import retry_sleep
from .base import Segment, Transcript, chunk_plan, fresh_boundaries, stitch

MAX_PROMPT_CHARS = 800  # server-side limit is ~224 tokens


class CloudASR:
    def __init__(self, *, provider_name: str, base_url: str, model: str, api_key: str,
                 chunk_seconds: int = 1800, overlap_seconds: float = 2.0,
                 max_upload_mb: int = 20, audio_codec: str = "mp3"):
        self.provider_name = provider_name
        self.model = model
        self.chunk_seconds = chunk_seconds
        self.overlap = overlap_seconds
        self.max_upload_mb = max_upload_mb
        self.audio_codec = audio_codec
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=900.0, max_retries=0)

    def transcribe(self, audio: Path, language: str | None = None,
                   prompt: str | None = None) -> Transcript:
        duration = probe_duration(audio)
        size_mb = audio.stat().st_size / 1e6
        vocab = (prompt or "")[:MAX_PROMPT_CHARS]

        if size_mb <= self.max_upload_mb and duration <= self.chunk_seconds:
            segs, lang = self._transcribe_file(audio, offset=0.0, language=language, prompt=vocab)
            return Transcript(segments=segs, language=lang, duration=duration,
                              provider=self.provider_name, model=self.model,
                              audio_seconds=duration)

        plan = chunk_plan(duration, self.chunk_seconds, self.overlap)
        boundaries = fresh_boundaries(plan, self.chunk_seconds)
        batches: list[list[Segment]] = []
        lang_seen: str | None = None
        with tempfile.TemporaryDirectory(prefix="vdesc_chunks_") as td:
            tmp = Path(td) / f"chunk.{'mp3' if self.audio_codec == 'mp3' else 'flac'}"
            for start, length in plan:
                cut_audio(audio, tmp, start, length, codec=self.audio_codec)
                segs, lang = self._transcribe_file(tmp, offset=start, language=language,
                                                   prompt=vocab)
                batches.append(segs)
                lang_seen = lang or lang_seen
        segments = stitch(batches, boundaries)
        return Transcript(segments=segments, language=lang_seen, duration=duration,
                          provider=self.provider_name, model=self.model,
                          audio_seconds=sum(length for _, length in plan))

    def _transcribe_file(self, path: Path, *, offset: float, language: str | None,
                         prompt: str) -> tuple[list[Segment], str | None]:
        max_attempts = 6
        delay = 10.0
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                with path.open("rb") as f:
                    kwargs: dict = {"model": self.model, "file": f,
                                    "response_format": "verbose_json", "temperature": 0}
                    if language:
                        kwargs["language"] = language
                    if prompt:
                        kwargs["prompt"] = prompt
                    resp = self._client.audio.transcriptions.create(**kwargs)
                raw = getattr(resp, "segments", None) or []
                segs = []
                for s in raw:
                    start = float(s.start) + offset
                    end = float(s.end if s.end is not None else s.start + 2.0) + offset
                    text = (s.text or "").strip()
                    if text:
                        segs.append(Segment(start=start, end=max(end, start), text=text))
                return segs, getattr(resp, "language", None)
            except RateLimitError as exc:
                last_exc = exc
                wait = retry_sleep(exc)
                time.sleep(min(wait, 120.0) if wait is not None else delay)
            except (APITimeoutError, APIConnectionError) as exc:
                last_exc = exc
                time.sleep(delay)
            except APIStatusError as exc:
                status = getattr(exc, "status_code", 0) or 0
                if status != 429 and status < 500:
                    raise  # permanent error — surface it
                last_exc = exc
                time.sleep(delay)
            delay = min(delay * 2, 60.0)
        raise RuntimeError(
            f"ASR failed after {max_attempts} attempts: {last_exc}") from last_exc
