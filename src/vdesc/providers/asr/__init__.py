"""ASR provider resolution: presets + auto selection + key checks."""
from __future__ import annotations

import os
import sys

from ...config import ASRConfig, resolve_api_key
from .base import Transcript  # re-export for convenience  # noqa: F401
from .groq import CloudASR
from .local import LocalWhisper

PRESETS: dict[str, dict] = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3-turbo",
        "api_key_env": "GROQ_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "whisper-1",
        "api_key_env": "OPENAI_API_KEY",
    },
}

KINDS = ("groq", "openai", "custom", "local", "auto")


def resolve_asr(cfg: ASRConfig, audio_codec: str = "mp3"):
    name = cfg.provider
    if name == "auto":
        if os.environ.get("GROQ_API_KEY"):
            name = "groq"
        else:
            try:
                import faster_whisper  # noqa: F401
                name = "local"
            except ImportError:
                sys.exit(
                    "ASR provider 'auto' found no GROQ_API_KEY and faster-whisper is not "
                    "installed.\nSet GROQ_API_KEY, pick --asr groq/openai/custom, or "
                    "install the local extra: pip install 'vdesc[local]'"
                )

    if name == "local":
        return LocalWhisper(model=cfg.model or "large-v3-turbo")

    if name in ("groq", "openai"):
        preset = PRESETS[name]
        base_url = cfg.base_url or preset["base_url"]
        model = cfg.model or preset["model"]
        api_key_env = cfg.api_key_env or preset["api_key_env"]
    elif name == "custom":
        if not (cfg.base_url and cfg.model):
            sys.exit("ASR provider 'custom' needs both base_url and model in [asr] config.")
        api_key_env = cfg.api_key_env or "ASR_API_KEY"
        base_url, model = cfg.base_url, cfg.model
    else:
        sys.exit(f"unknown ASR provider '{name}'. Choose one of: {', '.join(KINDS)}.")

    key = resolve_api_key(api_key_env, f"ASR provider '{name}'")
    return CloudASR(provider_name=name, base_url=base_url, model=model, api_key=key,
                    chunk_seconds=cfg.chunk_seconds, overlap_seconds=cfg.overlap_seconds,
                    max_upload_mb=cfg.max_upload_mb, audio_codec=audio_codec)
