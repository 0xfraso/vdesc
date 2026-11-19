from vdesc.writer import (assemble, build_context, midpoint_seconds,
                              run_sections, slice_frames_by_ts)


NOTES = """## Frame @ 00:00
intro frame

## Frame @ 03:00
early frame

## Frame @ 05:00
mid frame

## Frame @ 08:00
late frame
"""

TRANSCRIPT = "[00:00 - 00:05] a\n[03:00 - 03:04] b\n[08:00 - 08:05] c\n"


def test_slice_frames_by_ts():
    assert "00:00" in slice_frames_by_ts(NOTES, 0, 300)
    assert "05:00" not in slice_frames_by_ts(NOTES, 0, 300)  # 300s excluded (half-open)
    both = slice_frames_by_ts(NOTES, 0, 10 ** 9)
    assert "08:00" in both and "00:00" in both


def test_midpoint_seconds():
    assert midpoint_seconds(TRANSCRIPT) == 180.0  # middle marker is 03:00
    assert midpoint_seconds("no markers here") is None


def test_build_context_halves():
    full = build_context(TRANSCRIPT, NOTES, None, None)
    assert "late frame" in full
    # transcript is shared to both halves (global context); only frame notes are sliced
    h1 = build_context(TRANSCRIPT, NOTES, 1, 300.0)
    assert "intro frame" in h1 and "early frame" in h1
    assert "mid frame" not in h1 and "late frame" not in h1
    h2 = build_context(TRANSCRIPT, NOTES, 2, 300.0)
    assert "intro frame" not in h2 and "early frame" not in h2
    assert "mid frame" in h2 and "late frame" in h2


def test_presets_shape():
    assert [k for k, _, _ in assemble.__globals__["PRESETS"]["max"]] == \
        ["p1", "p2", "code", "concepts", "takeaways"]


class FakeClient:
    """Records prompts; returns a deterministic section per key."""

    def __init__(self):
        self.prompts = []

    def complete(self, *, system=None, user, max_attempts=None):
        self.prompts.append((system, user))
        marker = "CONCEPTS+TAKEAWAYS" if "KEY CONCEPTS and TAKEAWAYS" in user else \
            ("DOCUMENT" if "concise but substantive" in user else "SECTION")
        from vdesc.providers.llm import ChatResult
        return ChatResult(text=f"echo {marker}", usage=None, model="fake")


def test_run_sections_brief(tmp_path):
    client = FakeClient()
    results = run_sections(tmp_path, client, preset="brief", title="T",
                           duration_hint="10:00 minutes", transcript_txt=TRANSCRIPT,
                           frame_notes=NOTES, custom_prompts_dir=None, workers=1)
    assert results["document"].startswith("echo DOCUMENT")
    doc = assemble("brief", results)
    assert doc.startswith("echo DOCUMENT")
    assert len(client.prompts) == 1
    assert "[00:00 - 00:05] a" in client.prompts[0][1]  # context appended


def test_run_sections_resume(tmp_path):
    client = FakeClient()
    run_sections(tmp_path, client, preset="brief", title="T", duration_hint="d",
                 transcript_txt=TRANSCRIPT, frame_notes=NOTES, custom_prompts_dir=None)
    # second run finds the section file and makes no calls
    client2 = FakeClient()
    results = run_sections(tmp_path, client2, preset="brief", title="T", duration_hint="d",
                           transcript_txt=TRANSCRIPT, frame_notes=NOTES,
                           custom_prompts_dir=None)
    assert client2.prompts == []
    assert results["document"].startswith("echo DOCUMENT")


def test_prompts_have_no_stray_braces():
    from vdesc.prompts import load_prompt, VALID_NAMES
    for name in VALID_NAMES:
        text = load_prompt(name)
        # str.format on the template must not raise (placeholders are provided)
        text.format(title="t", duration="d", split="s", target_words=100, context="c")
