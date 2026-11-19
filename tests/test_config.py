import os

from vdesc.config import (ASRConfig, Config, EndpointConfig, PipelineConfig,
                              apply_cli_overrides, estimate_cost, find_config, load_config)
from vdesc.util import load_dotenv


def test_defaults():
    cfg = Config()
    assert cfg.pipeline.depth == "standard"
    assert cfg.pipeline.frame_interval == 5
    assert cfg.asr.provider == "auto"
    assert cfg.vision.api_key_env == "LLM_API_KEY"


def test_load_from_file(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        """
[pipeline]
depth = "max"
frame_interval = 10
unknown_key = "ignored"

[asr]
provider = "groq"

[vision]
base_url = "https://example.com/v1"
model = "vision-x"
api_key_env = "MY_VISION_KEY"

[pricing."some-model"]
input_per_m = 1.0
output_per_m = 2.0
"""
    )
    cfg = load_config(str(p))
    assert cfg.config_path == p
    assert cfg.pipeline.depth == "max"
    assert cfg.pipeline.frame_interval == 10
    assert cfg.asr.provider == "groq"
    assert cfg.vision.model == "vision-x"
    assert cfg.vision.api_key_env == "MY_VISION_KEY"
    assert cfg.pricing["some-model"]["input_per_m"] == 1.0


def test_apply_cli_overrides():
    cfg = Config()
    ns = type("NS", (), {})()
    ns.depth = "brief"
    ns.frame_interval = 7
    ns.max_width = None
    ns.frames_per_call = None
    ns.vision_workers = None
    ns.writer_workers = None
    ns.context = "test domain"
    ns.summary_words = None
    ns.asr_provider = "local"
    ns.language = "auto"
    ns.asr_prompt = "vocab"
    ns.out = None
    apply_cli_overrides(cfg, ns)
    assert cfg.pipeline.depth == "brief"
    assert cfg.pipeline.frame_interval == 7
    assert cfg.pipeline.max_width == 1600  # untouched
    assert cfg.pipeline.context == "test domain"
    assert cfg.asr.provider == "local"
    assert cfg.asr.language is None  # 'auto' means no language hint
    assert cfg.asr.prompt == "vocab"


def test_estimate_cost():
    pricing = {"m": {"input_per_m": 0.15, "output_per_m": 0.5}}
    assert estimate_cost("m", prompt_tokens=1_000_000, completion_tokens=1_000_000,
                         pricing=pricing) == 0.65
    assert estimate_cost("unknown", prompt_tokens=5, pricing=pricing) is None
    audio_pricing = {"w": {"audio_per_hour": 0.04}}
    assert abs(estimate_cost("w", audio_seconds=3600, pricing=audio_pricing) - 0.04) < 1e-9


def test_find_config_env_var(tmp_path, monkeypatch):
    p = tmp_path / "c.toml"
    p.write_text("[pipeline]\ndepth = 'brief'\n")
    monkeypatch.setenv("VDESC_CONFIG", str(p))
    assert find_config(None) == p


def test_dotenv_does_not_clobber(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('A_KEY="hello world"\nB_KEY=existing\n# comment\n\nBAD LINE\n')
    monkeypatch.setenv("B_KEY", "keep-me")
    load_dotenv([f])
    assert os.environ["A_KEY"] == "hello world"
    assert os.environ["B_KEY"] == "keep-me"
