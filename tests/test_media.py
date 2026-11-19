from pathlib import Path

from vdesc.media import extract_frames, probe_duration


def _make_test_video(tmp_path: Path, seconds: int = 6) -> Path:
    out = tmp_path / "clip.mp4"
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=30",
         "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True)
    return out


def test_probe_duration(tmp_path):
    video = _make_test_video(tmp_path, 6)
    assert abs(probe_duration(video) - 6.0) < 0.5


def test_extract_frames_nominal_timestamps(tmp_path):
    # 15s clip: fps=1/5 yields frames at the 0/5/10s grid (same filter as the
    # original pipeline; real-length videos cover the grid fully)
    video = _make_test_video(tmp_path, 15)
    frames = extract_frames(video, tmp_path / "frames", interval=5, max_width=320)
    assert [round(t) for t, _ in frames] == [0, 5, 10]
    assert all(p.exists() for _, p in frames)
    assert frames[0][1].stat().st_size > 0
