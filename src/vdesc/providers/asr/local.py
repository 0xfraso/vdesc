"""Local ASR via faster-whisper (optional `local` extra).

CTranslate2 int8 on CPU is several times faster and much lighter than a
torch/transformers pipeline, and keeps audio entirely on the machine — the
right fallback when content is private or there is no ASR API key.
"""
from __future__ import annotations

from pathlib import Path

from .base import Segment, Transcript


class LocalWhisper:
    provider_name = "local"

    def __init__(self, model: str = "large-v3-turbo", device: str = "auto",
                 compute_type: str = "auto"):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - exercised only without the extra
            raise RuntimeError(
                "local ASR requires the optional extra: pip install 'vdesc[local]'"
            ) from exc
        self.model = model
        self._model = WhisperModel(model, device=device, compute_type=compute_type)

    def transcribe(self, audio: Path, language: str | None = None,
                   prompt: str | None = None) -> Transcript:
        raw, info = self._model.transcribe(
            str(audio), language=language, initial_prompt=prompt or None,
            vad_filter=True, beam_size=5,
        )
        segments = [Segment(start=s.start, end=s.end, text=(s.text or "").strip())
                    for s in raw if (s.text or "").strip()]
        return Transcript(segments=segments, language=getattr(info, "language", None),
                          duration=float(getattr(info, "duration", 0.0) or 0.0),
                          provider=self.provider_name, model=self.model,
                          audio_seconds=float(getattr(info, "duration", 0.0) or 0.0))
