"""Frame analysis stage: batched vision-model OCR over sampled frames.

Frames arrive as a list of (timestamp, path). Each batch is one vision call
whose result is persisted immediately to vision/batch_NNNN.md — a failed batch
is simply missing, so the next run reprocesses only what failed. The merged
`frames.md` uses '## Frame @ mm:ss' sections, which is the anchor format the
writer stage slices by.
"""
from __future__ import annotations

import base64
import concurrent.futures
from pathlib import Path

from .providers.llm import ChatClient
from .prompts import load_prompt
from .util import Timer, fmt_ts

BATCH_HEADER = "Frame at {ts}:"


def analyze_frames(frames: list[tuple[float, Path]], vision_dir: Path, *, client: ChatClient,
                   context: str, per_call: int, workers: int, custom_prompts_dir: str | None,
                   log=print) -> str:
    batches = [frames[i:i + per_call] for i in range(0, len(frames), per_call)]
    vision_dir.mkdir(parents=True, exist_ok=True)
    instruction = load_prompt("vision_frames", custom_prompts_dir).format(context=context)

    def run(idx: int, batch: list[tuple[float, Path]]) -> str:
        out = vision_dir / f"batch_{idx:04d}.md"
        if out.exists() and out.stat().st_size > 0:
            return out.read_text(encoding="utf-8")
        content = [{"type": "text", "text": instruction}]
        for ts, path in batch:
            content.append({"type": "text", "text": BATCH_HEADER.format(ts=fmt_ts(ts))})
            b64 = base64.b64encode(Path(path).read_bytes()).decode()
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        result = client.complete(user=content)
        out.write_text(result.text, encoding="utf-8")
        return result.text

    log(f"Analyzing {len(frames)} frames in {len(batches)} vision calls "
        f"({per_call} frames/call, {workers} workers)...")
    timer = Timer()
    results: list[str] = [""] * len(batches)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, i, b): i for i, b in enumerate(batches)}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            idx = futures[fut]
            try:
                results[idx] = fut.result()
            except Exception as exc:  # keep going; placeholder marks the gap for a retry run
                results[idx] = f"(frame batch {idx} failed: {exc})"
            done += 1
            log(f"  vision batch {done}/{len(batches)} done ({timer.elapsed():.0f}s)")
    merged = "\n\n".join(r for r in results if r)
    return merged
