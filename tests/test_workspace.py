import json

from vdesc.workspace import Workspace


def test_stage_cache_roundtrip(tmp_path):
    ws = Workspace(tmp_path / "run").ensure()
    key = "abc123"
    assert not ws.stage_ready("transcript", key, ws.transcript_json)
    ws.set_stage("transcript", key, provider="groq", segments=10)
    ws.transcript_json.write_text("{}")
    ws.transcript_txt.write_text("hello")
    assert ws.stage_ready("transcript", key, ws.transcript_json, ws.transcript_txt)
    # changed key -> not ready
    assert not ws.stage_ready("transcript", "other", ws.transcript_json)
    # missing artifact -> not ready
    ws.transcript_txt.unlink()
    assert not ws.stage_ready("transcript", key, ws.transcript_json, ws.transcript_txt)


def test_wipe_stage(tmp_path):
    ws = Workspace(tmp_path / "run").ensure()
    v = ws.vision_dir / "batch_0000.md"
    v.parent.mkdir(parents=True)
    v.write_text("x")
    ws.frames_md.write_text("notes")
    ws.wipe_stage_artifacts("vision")
    assert not v.exists() and not ws.frames_md.exists()


def test_usage_ledger(tmp_path):
    ws = Workspace(tmp_path / "run").ensure()
    ws.add_usage({"stage": "vision", "model": "m", "prompt_tokens": 100,
                  "completion_tokens": 10, "est_cost_usd": 0.02, "elapsed_s": 5})
    ws.add_usage({"stage": "transcribe", "model": "w", "audio_seconds": 600,
                  "est_cost_usd": None, "elapsed_s": 3})
    ws.add_usage({"stage": "writer", "model": "m", "prompt_tokens": 50,
                  "completion_tokens": 5, "est_cost_usd": 0.01, "elapsed_s": 2})
    totals = ws.usage_totals()
    assert totals["calls"] == 3
    assert totals["prompt_tokens"] == 150
    assert totals["completion_tokens"] == 15
    assert totals["audio_seconds"] == 600
    assert abs(totals["est_cost_usd"] - 0.03) < 1e-9
    assert totals["cost_known"]

    # persists across instances
    ws2 = Workspace(tmp_path / "run")
    assert ws2.usage_totals()["calls"] == 3
    assert ws2.count_usage("vision") == 1
    assert json.loads((tmp_path / "run" / "meta.json").read_text())["stages"] == {}
