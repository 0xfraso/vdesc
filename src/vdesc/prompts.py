"""Prompt templates are data, not code — loaded from package resources with an
optional user override directory. Template content is hashed into stage cache
keys, so editing a prompt invalidates affected caches automatically.

Placeholders use str.format and templates must therefore contain no stray
braces. Large payloads (transcript, frame notes, source document) are appended
by code, never embedded in templates.
"""
from __future__ import annotations

import functools
from importlib import resources
from pathlib import Path

from .util import sha256_text

VALID_NAMES = {
    "vision_frames",
    "summary",
    "sections/p1",
    "sections/p2",
    "sections/code",
    "sections/concepts",
    "sections/takeaways",
    "sections/concepts_takeaways",
    "sections/document",
}


@functools.lru_cache(maxsize=None)
def load_prompt(name: str, custom_dir: str | None = None) -> str:
    if name not in VALID_NAMES:
        raise KeyError(f"unknown prompt template: {name}")
    if custom_dir:
        p = Path(custom_dir).expanduser() / f"{name}.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    parts = name.split("/")
    ref = resources.files("vdesc").joinpath("prompts")
    for part in parts:
        ref = ref.joinpath(part)
    return ref.with_suffix(".md").read_text(encoding="utf-8")


def prompt_version(names: list[str], custom_dir: str | None = None) -> str:
    """Combined hash of the exact template texts used by a stage."""
    return sha256_text("\n".join(load_prompt(n, custom_dir) for n in names))
