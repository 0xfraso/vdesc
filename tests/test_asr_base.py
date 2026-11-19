from vdesc.providers.asr.base import (Segment, Transcript, chunk_plan,
                                          fresh_boundaries, stitch)
from vdesc.util import fmt_ts, srt_ts, slugify


def seg(start, end, text):
    return Segment(start=start, end=end, text=text)


def test_chunk_plan_short():
    assert chunk_plan(100, 1800, 2.0) == [(0.0, 100.0)]


def test_chunk_plan_long():
    plan = chunk_plan(100, 30, 2.0)
    assert plan == [(0.0, 30.0), (28.0, 32.0), (58.0, 32.0), (88.0, 12.0)]
    # total fresh coverage is contiguous: boundaries at 30, 60, 90
    assert fresh_boundaries(plan, 30) == [0.0, 30.0, 60.0, 90.0]


def test_stitch_drops_overlap_segments():
    batches = [
        [seg(0, 5, "hello"), seg(5, 10, "world")],
        # chunk 1 starts at 28; fresh boundary at 30 -> segment at 29 is dropped
        [seg(29, 31, "world overlap"), seg(31, 40, "next words")],
    ]
    out = stitch(batches, [0.0, 30.0])
    assert [(s.start, s.text) for s in out] == [(0.0, "hello"), (5.0, "world"), (31.0, "next words")]


def test_stitch_drops_empty_and_exact_duplicates():
    batches = [
        [seg(0, 2, ""), seg(2, 5, "a")],
        [seg(10, 12, "a")],  # same text but different time -> kept (boundary 10)
    ]
    out = stitch(batches, [0.0, 10.0])
    assert [(s.start, s.text) for s in out] == [(2.0, "a"), (10.0, "a")]


def test_transcript_roundtrip_and_formats():
    tr = Transcript(segments=[seg(0, 5, "hello world"), seg(65, 70, "second line")],
                    language="en", duration=70, provider="groq", model="m",
                    audio_seconds=70)
    txt = tr.timestamped_text()
    assert txt == "[00:00 - 00:05] hello world\n[01:05 - 01:10] second line"
    tr2 = Transcript.from_json(tr.to_json())
    assert tr2.timestamped_text() == txt
    assert tr2.segments[1].start == 65
    srt = tr.to_srt()
    assert "1\n00:00:00,000 --> 00:00:05,000\nhello world" in srt
    assert "00:01:05,000 --> 00:01:10,000" in srt


def test_parse_existing_timestamped_txt():
    txt = "[00:00 - 00:05] first\n[10:00 - 10:03] later\nnot a transcript line\n"
    tr = Transcript.from_timestamped_txt(txt)
    assert len(tr.segments) == 2
    assert tr.segments[1].start == 600
    assert tr.duration == 603


def test_time_formatting():
    assert fmt_ts(0) == "00:00"
    assert fmt_ts(65) == "01:05"
    assert fmt_ts(3700) == "61:40"
    assert srt_ts(3661.5) == "01:01:01,500"


def test_slugify():
    assert slugify("Drawing the Line on 3D Pixel Art | Pixel Perfect") == \
        "drawing-the-line-on-3d-pixel-art-pixel-perfect"
    assert slugify("") == "video"
    assert slugify("!!!") == "video"
