"""Kiểm thử bài luyện Shadowing không cần mô hình: âm thanh giả bằng sóng sin."""
import json
import os
import subprocess
import tempfile

import numpy as np
import pytest

os.environ.setdefault("TIT_DATA_DIR", tempfile.mkdtemp(prefix="tit-qa-"))

from app import shadow  # noqa: E402
from app.shadow import Line, Settings  # noqa: E402

SR = shadow.SR


def test_parse_lesson_translation_and_sentence_split():
    lines = shadow.parse_lesson(
        "Good morning! How are you? | Chào buổi sáng! Bạn khoẻ không?\n\n"
        "I met Mr. Smith yesterday. He was late.\n  | chỉ có bản dịch\n"
    )
    assert lines == [
        Line("Good morning! How are you?", "Chào buổi sáng! Bạn khoẻ không?"),
        Line("I met Mr. Smith yesterday."),
        Line("He was late."),
    ]


@pytest.mark.parametrize("text,spoken", [
    ("Call me before 9 a.m.", "Call me before nine A M."),
    ("It starts at 3:30 p.m. sharp.", "It starts at three thirty P M sharp."),
    ("Meet at 7:05pm", "Meet at seven oh five P M"),
    ("Salt & pepper.", "Salt and pepper."),
    ("No times here.", "No times here."),
])
def test_normalize_en(text, spoken):
    assert shadow.normalize_en(text) == spoken


def test_word_times_are_increasing_and_weighted():
    starts = shadow.word_times(["I", "absolutely", "agree."], 3.0)
    assert starts[0] == 0 and starts == sorted(starts) and starts[-1] < 3.0
    assert starts[2] - starts[1] > starts[1] - starts[0]   # "absolutely" dài hơn "I"


def test_trim_silence_keeps_small_pad():
    tone = 0.3 * np.sin(np.linspace(0, 2 * np.pi * 220, SR)).astype(np.float32)
    padded = np.concatenate([np.zeros(SR, np.float32), tone, np.zeros(SR, np.float32)])
    trimmed = shadow.trim_silence(padded)
    assert abs(len(trimmed) / SR - 1.12) < 0.02


def test_plan_steps_follows_pattern():
    lines = [Line("One two three."), Line("Four five.")]
    steps = shadow.plan_steps(lines, [2.0, 1.0], Settings(voice="x", repeats=2, slow_speed=0.8, gap_factor=1.5))
    kinds = [s.kind for s in steps]
    assert kinds[0] == "intro" and kinds[-1] == "outro"
    assert kinds[1:9] == ["listen", "gap", "slow", "gap"] * 2
    assert kinds.count("full") == 2 and kinds.count("pause") == 1
    assert steps[2].duration == 3.0 and steps[3].duration == 2.5          # khoảng nói, bản chậm 0.8x
    assert all(b.start == pytest.approx(a.start + a.duration, abs=1e-3) for a, b in zip(steps, steps[1:]))
    no_slow = shadow.plan_steps(lines, [2.0, 1.0], Settings(voice="x", slow_speed=1.0, full_run=False))
    assert [s.kind for s in no_slow] == ["intro", "listen", "gap", "listen", "gap", "outro"]
    assert no_slow[4].duration == shadow.MIN_GAP_S                         # câu ngắn vẫn có đủ thời gian nói


def test_plan_steps_uses_measured_word_starts():
    lines = [Line("Call me at nine."), Line("Thanks.")]
    s = Settings(voice="x", slow_speed=0.8, full_run=False)
    steps = shadow.plan_steps(lines, [2.0, 1.0], s, [[0.12, 0.5, 0.8, 1.2], None])
    listen, slow = steps[1], steps[3]
    assert listen.words == [0.0, 0.5, 0.8, 1.2]                       # từ đầu sáng ngay từ giây 0
    assert slow.words == [0.0, 0.625, 1.0, 1.5]                       # bản chậm co giãn theo 0.8x
    assert steps[5].words == shadow.word_times(["Thanks."], 1.0)      # câu không có mốc thì ước lượng
    # số mốc không khớp số từ → ước lượng
    assert shadow.step_words(lines[0], [0.1, 0.4], 2.0, 2.0) == shadow.word_times(lines[0].en.split(), 2.0)


def test_lesson_dir_rejects_traversal():
    with pytest.raises(ValueError):
        shadow.lesson_dir("../history")


def _tone(seconds):
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


@pytest.mark.parametrize("aspect,size", [("16:9", "1920x1080"), ("9:16", "1080x1920")])
def test_build_writes_video_audio_srt_and_timeline(aspect, size):
    lesson_id = "abcdef012345" if aspect == "16:9" else "abcdef543210"
    lines = [Line("Good morning, how are you doing today?", "Chào buổi sáng, hôm nay bạn thế nào?"),
             Line("Could you tell me where the nearest coffee shop is?")]
    progress = []
    meta = shadow.build(lesson_id, lines, [_tone(1.5), _tone(2.0)], Settings(voice="Thử", aspect=aspect),
                        progress.append)
    out = shadow.lesson_dir(lesson_id)
    assert sorted(p.name for p in out.iterdir()) == ["lesson.mp3", "lesson.mp4", "lesson.srt", "timeline.json"]
    assert progress == sorted(progress) and progress[-1] <= 1

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration", "-of", "json",
         str(out / "lesson.mp4")], capture_output=True, text=True, check=True).stdout)
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert f"{video['width']}x{video['height']}" == size
    assert {s["codec_type"] for s in probe["streams"]} == {"video", "audio"}
    assert abs(float(probe["format"]["duration"]) - meta["duration"]) < 0.3

    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["duration"] == meta["duration"] and len(timeline["lines"]) == 2
    assert timeline["word_timing"] == "estimated"
    srt = (out / "lesson.srt").read_text(encoding="utf-8")
    assert srt.count(" --> ") == 6 and "Chào buổi sáng" in srt   # nghe, chậm, liền mạch × 2 câu


def test_build_shifts_measured_starts_after_trimming():
    lead = np.zeros(int(SR * 0.5), np.float32)              # 0.5 s lặng đầu clip bị cắt (giữ lại 0.06 s)
    clip = np.concatenate([lead, _tone(2.0)])
    lines = [Line("One two three.")]
    shadow.build("abcdef111111", lines, [clip], Settings(voice="Thử", slow_speed=1.0, full_run=False),
                 lambda p: None, [[0.5, 1.2, 1.9]])
    timeline = json.loads((shadow.lesson_dir("abcdef111111") / "timeline.json").read_text(encoding="utf-8"))
    listen = next(s for s in timeline["steps"] if s["kind"] == "listen")
    assert timeline["word_timing"] == "measured"
    assert listen["words"][0] == 0 and listen["words"][1:] == pytest.approx([0.76, 1.46], abs=0.01)
