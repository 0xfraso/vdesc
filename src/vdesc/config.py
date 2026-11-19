"""Configuration: built-in defaults < config.toml < environment < CLI flags.

Secrets never live in config files — configs reference the *name* of an
environment variable (`api_key_env`) and the key itself is read at runtime.
"""
from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

SEARCH_PATHS = (
    Path("config.toml"),
    Path.home() / ".config" / "vdesc" / "config.toml",
)
ENV_CONFIG_VAR = "VDESC_CONFIG"


@dataclass
class PipelineConfig:
    out_dir: str = "out"
    depth: str = "standard"  # brief | standard | max
    frame_interval: int = 5
    max_width: int = 1600
    frames_per_call: int = 6
    vision_workers: int = 4
    writer_workers: int = 3
    context: str = (
        "a technical video (code editors, terminals and engine/UI settings panels may appear)"
    )
    summary_words: int = 1200


@dataclass
class ASRConfig:
    provider: str = "auto"  # groq | openai | custom | local | auto
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    language: str | None = None  # None = auto-detect
    prompt: str = ""  # optional vocabulary hint (max ~224 tokens server-side)
    chunk_seconds: int = 1800
    overlap_seconds: float = 2.0
    max_upload_mb: int = 20


@dataclass
class EndpointConfig:
    base_url: str | None = None
    model: str | None = None
    api_key_env: str = "LLM_API_KEY"


@dataclass
class PromptsConfig:
    dir: str | None = None  # optional override dir for prompt templates


@dataclass
class Config:
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    vision: EndpointConfig = field(default_factory=EndpointConfig)
    text: EndpointConfig = field(default_factory=EndpointConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    pricing: dict = field(default_factory=dict)
    config_path: Path | None = None


def _fill(dc, data: dict):
    """Set dataclass fields from a dict, ignoring unknown keys."""
    known = {f.name for f in fields(dc)}
    for k, v in (data or {}).items():
        if k in known:
            setattr(dc, k, v)
    return dc


def find_config(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            sys.exit(f"config not found: {p}")
        return p
    env = os.environ.get(ENV_CONFIG_VAR)
    if env:
        p = Path(env).expanduser()
        if not p.exists():
            sys.exit(f"{ENV_CONFIG_VAR} points to a missing file: {p}")
        return p
    for p in SEARCH_PATHS:
        if p.exists():
            return p
    return None


def load_config(explicit: str | None = None) -> Config:
    path = find_config(explicit)
    cfg = Config(config_path=path)
    if path is None:
        return cfg
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    _fill(cfg.pipeline, data.get("pipeline"))
    _fill(cfg.asr, data.get("asr"))
    _fill(cfg.vision, data.get("vision"))
    _fill(cfg.text, data.get("text"))
    _fill(cfg.prompts, data.get("prompts"))
    cfg.pricing = data.get("pricing", {}) or {}
    return cfg


def apply_cli_overrides(cfg: Config, args) -> None:
    """Map parsed argparse namespace onto the config (only set flags)."""
    p, a = cfg.pipeline, cfg.asr
    if getattr(args, "depth", None):
        p.depth = args.depth
    if getattr(args, "frame_interval", None):
        p.frame_interval = args.frame_interval
    if getattr(args, "max_width", None):
        p.max_width = args.max_width
    if getattr(args, "frames_per_call", None):
        p.frames_per_call = args.frames_per_call
    if getattr(args, "vision_workers", None):
        p.vision_workers = args.vision_workers
    if getattr(args, "writer_workers", None):
        p.writer_workers = args.writer_workers
    if getattr(args, "context", None):
        p.context = args.context
    if getattr(args, "summary_words", None):
        p.summary_words = args.summary_words
    if getattr(args, "asr_provider", None):
        a.provider = args.asr_provider
    if getattr(args, "language", None):
        a.language = None if args.language in (None, "", "auto") else args.language
    if getattr(args, "asr_prompt", None):
        a.prompt = args.asr_prompt
    if getattr(args, "out", None):
        p.out_dir = args.out


def resolve_api_key(env_name: str | None, what: str) -> str:
    if not env_name:
        sys.exit(
            f"{what}: no api_key_env configured. Set base_url/model/api_key_env for this "
            f"endpoint in config.toml (secrets live in environment variables, never in configs)."
        )
    key = os.environ.get(env_name)
    if not key:
        sys.exit(f"{what}: environment variable {env_name} is not set.")
    return key


def estimate_cost(model: str, *, prompt_tokens: int = 0, completion_tokens: int = 0,
                  audio_seconds: float = 0.0, pricing: dict | None = None) -> float | None:
    """Best-effort USD estimate using the optional [pricing] config table."""
    rate = (pricing or {}).get(model)
    if not rate:
        return None
    cost = 0.0
    if audio_seconds and rate.get("audio_per_hour"):
        cost += (audio_seconds / 3600.0) * rate["audio_per_hour"]
    if rate.get("input_per_m"):
        cost += prompt_tokens / 1e6 * rate["input_per_m"]
        cost += completion_tokens / 1e6 * float(rate.get("output_per_m", 0))
    return cost
