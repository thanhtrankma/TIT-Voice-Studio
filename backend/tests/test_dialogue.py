"""Kiểm thử video hội thoại tiếng Trung không cần mô hình: âm thanh giả bằng sóng sin."""
import json
import os
import subprocess
import tempfile

import numpy as np
import pytest

os.environ.setdefault("TIT_DATA_DIR", tempfile.mkdtemp(prefix="tit-qa-"))

from app import chinese, dialogue, shadow, thumbnail, youtube  # noqa: E402
from app.dialogue import Settings, Utterance  # noqa: E402

SR = dialogue.SR

SAMPLE = """麻烦你*站起来*一下。 | Phiền bạn *đứng dậy* một lát. | Please stand up for a while.
好的。 | Ok.

B: 你*抽烟*吗？ | Bạn *hút thuốc* không?
A：不抽，谢谢。
"""


def _tone(seconds, freq=220):
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_parse_marks():
    assert dialogue.parse_marks("麻烦你*站起来*一下。") == ("麻烦你站起来一下。", [[3, 6]])
    assert dialogue.parse_marks(" *a* b ＊cd") == ("a b cd", [[0, 1], [4, 6]])   # dấu * thiếu cặp: tô đến hết
    assert dialogue.parse_marks("**x") == ("x", [])


def test_parse_dialogue_alternates_speakers_and_blocks():
    utts = dialogue.parse_dialogue(SAMPLE)
    assert [(u.zh, u.speaker, u.block) for u in utts] == [
        ("麻烦你站起来一下。", 0, 0), ("好的。", 1, 0), ("你抽烟吗？", 1, 1), ("不抽，谢谢。", 0, 1)]
    assert utts[0].vi == "Phiền bạn đứng dậy một lát." and utts[0].vi_marks == [[10, 18]]
    assert utts[0].en == "Please stand up for a while." and utts[3].vi == ""


def test_exchanges_pair_question_and_answer():
    utts = [Utterance("一", speaker=0), Utterance("二", speaker=1), Utterance("三", speaker=0),
            Utterance("四", speaker=0), Utterance("五", speaker=1, block=1), Utterance("六", speaker=0, block=1)]
    groups, of = dialogue.exchanges(utts)
    assert groups == [{0: 0, 1: 1}, {0: 2}, {0: 3}, {1: 4}, {0: 5}]
    assert of == [0, 0, 1, 2, 3, 4]


def test_plan_steps_repeats_and_reads_translation_once():
    utts = [Utterance("一", "một", speaker=0), Utterance("二", speaker=1), Utterance("三", speaker=0, block=1)]
    s = Settings(voice_a="A", voice_b="B", repeats=2, pause=1.0)
    steps = dialogue.plan_steps(utts, [1.0, 2.0, 1.5], [0.8, 0, 0], s)
    kinds = [(st.kind, st.line) for st in steps if st.kind != "pause"]
    assert kinds == [("zh", 0), ("vi", 0), ("zh", 0), ("zh", 1), ("zh", 1), ("zh", 2), ("zh", 2)]
    starts = [st.start for st in steps]
    assert starts == sorted(starts) and steps[0].line == -1
    before_block = [st for st in steps if st.line == 1][-1]
    assert before_block.kind == "pause" and before_block.duration == pytest.approx(2.5)   # sang đoạn mới nghỉ lâu hơn


def test_second_reading_uses_its_own_speed_then_back_to_normal():
    utts = [Utterance("一", "một", speaker=0)]
    s = Settings(voice_a="A", voice_b="B", repeats=3, speed=1.0, speed2=0.8)
    assert dialogue.second_speed(s) == 0.8
    steps = dialogue.plan_steps(utts, [1.0], [0.8], s, [1.25])
    reads = [(st.kind, st.duration) for st in steps if st.kind != "pause"]
    assert reads == [("zh", 1.0), ("vi", 0.8), ("zh2", 1.25), ("zh", 1.0)]    # thường → chậm → thường

    for same in (Settings(voice_a="A", voice_b="B", repeats=2, speed=0.9, speed2=0.9),
                 Settings(voice_a="A", voice_b="B", repeats=1, speed2=0.7),
                 Settings(voice_a="A", voice_b="B", repeats=2)):
        assert dialogue.second_speed(same) is None      # không cần đọc thêm bản riêng


@pytest.mark.parametrize("zh,expected", [
    ("麻烦你站起来一下。", "Máfan nǐ zhàn qǐlai yīxià."),
    ("不抽，谢谢。", "Bù chōu, xièxie."),
    ("“你去哪儿？”他问。", "\"Nǐ qù nǎr?\" Tā wèn."),
    ("我们去北京和上海旅游。", "Wǒmen qù Běijīng hé Shànghǎi lǚyóu."),      # địa danh viết hoa
    ("请安静一点儿。", "Qǐng ānjìng yīdiǎnr."),          # từ điển gắn nhầm 安静 là tên người: không viết hoa
])
def test_pinyin_text(zh, expected):
    assert chinese.pinyin_text(zh) == expected


def test_pinyin_and_hanzi_tokens_carry_keyword_marks():
    zh, marks = dialogue.parse_marks("麻烦你*站起来*一下。")
    py = dialogue.pinyin_tokens(zh, marks)
    assert [seg for tok, _ in py for seg in tok if seg[1]] == [("zhàn", True), ("qǐlai", True)]
    hz = dialogue.hanzi_tokens(zh, marks)
    assert "".join(t for tok, _ in hz for t, _ in tok) == zh
    assert hz[-1][0][-1][0].endswith("。")      # dấu câu dính vào từ trước, không đứng đầu dòng
    vi, vmarks = dialogue.parse_marks("Phiền bạn *đứng dậy* một lát.")
    assert [tok for tok, _ in dialogue.word_tokens(vi, vmarks) if tok[0][1]] == [(("đứng", True),), (("dậy", True),)]


def test_build_loops_video_audio_srt_and_timeline():
    utts = dialogue.parse_dialogue(SAMPLE)
    clips = [_tone(1.2), _tone(0.6, 330), _tone(1.0), _tone(0.9, 330)]
    vi = [_tone(1.0, 440), None, None, None]
    progress = []
    s = Settings(voice_a="Xiaoxiao", voice_b="Yunxi", vi_voice="Adam", title="Thử", repeats=2, loops=3)
    meta = dialogue.build("abcdef0d1a10", utts, clips, vi, s, progress.append)
    out = shadow.lesson_dir("abcdef0d1a10")
    assert sorted(p.name for p in out.iterdir()) == ["lesson.mp3", "lesson.mp4", "lesson.srt", "timeline.json"]
    assert progress == sorted(progress) and progress[-1] <= 1

    timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
    assert timeline["kind"] == "dialogue" and timeline["loops"] == meta["loops"] == 3
    loop = timeline["loop_duration"]
    quanta = loop * SR / dialogue.QUANTUM                            # mỗi lượt khớp khung hình và khung AAC
    assert quanta == pytest.approx(round(quanta), abs=1e-3)
    intro = timeline["intro_duration"]                               # intro mặc định bật: chuông, không có giọng
    assert 4.5 <= intro < 5.1 and (intro * SR) % dialogue.QUANTUM == 0
    assert meta["duration"] == pytest.approx(intro + 3 * loop, abs=0.01)
    assert timeline["lines"][0]["pinyin"] == "Máfan nǐ zhàn qǐlai yīxià."

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,duration", "-of", "json",
         str(out / "lesson.mp4")], capture_output=True, text=True, check=True).stdout)
    streams = {st["codec_type"]: st for st in probe["streams"]}
    assert (streams["video"]["width"], streams["video"]["height"]) == (1920, 1080)
    assert float(streams["video"]["duration"]) == pytest.approx(meta["duration"], abs=0.1)
    assert float(streams["audio"]["duration"]) == pytest.approx(meta["duration"], abs=0.1)

    srt = (out / "lesson.srt").read_text(encoding="utf-8")
    assert srt.count(" --> ") == 4 * 3 and "Máfan nǐ" in srt
    first = srt.split("\n")[1].split(" --> ")[0]                      # cue đầu bắt đầu sau intro
    assert first >= shadow._srt_time(intro)


def _probe(path):
    return json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration:format=duration", "-of", "json",
         str(path)], capture_output=True, text=True, check=True).stdout)


def test_build_without_intro_and_with_spoken_intro():
    utts = [Utterance("好的。", speaker=0)]
    off = dialogue.build("abcdef0d1a14", utts, [_tone(1.0)], [None],
                         Settings(voice_a="A", voice_b="B", repeats=1, loops=2, intro=False), lambda p: None)
    tl = json.loads((shadow.lesson_dir("abcdef0d1a14") / "timeline.json").read_text(encoding="utf-8"))
    assert tl["intro_duration"] == 0 and off["duration"] == pytest.approx(2 * tl["loop_duration"], abs=0.01)

    spoken = dialogue.build("abcdef0d1a15", utts, [_tone(1.0)], [None],
                            Settings(voice_a="A", voice_b="B", title="Chào hỏi", repeats=1, loops=2), lambda p: None,
                            intro_vi=_tone(4.0, 440))
    tl = json.loads((shadow.lesson_dir("abcdef0d1a15") / "timeline.json").read_text(encoding="utf-8"))
    assert tl["intro_duration"] >= 1.0 + 4.0 + 1.0 - 0.2          # chuông + giọng đọc tên bài + nghỉ
    probe = _probe(shadow.lesson_dir("abcdef0d1a15") / "lesson.mp4")
    assert float(probe["format"]["duration"]) == pytest.approx(spoken["duration"], abs=0.1)


def test_intro_card_renders(tmp_path):
    from PIL import Image
    c = dialogue.Canvas("Gọi món ở nhà hàng Trung Quốc thật ngon", ("Xiaoxiao", "Yunxi"), True, tmp_path)
    paths = [c.intro(["6 câu", "Đọc 2 lần mỗi câu", "8 giờ 30 phút"], k) for k in range(4)]
    assert len(set(paths)) == 4 and Image.open(paths[-1]).size == (1920, 1080)


def test_build_mixes_background_music():
    from app import music
    utts = [Utterance("好的。", speaker=0)]
    s = Settings(voice_a="A", voice_b="B", repeats=1, loops=3, music="Mưa nhẹ", music_volume=0.5)
    meta = dialogue.build("abcdef0d1a16", utts, [_tone(1.0)], [None], s, lambda p: None,
                          music_path=music.path("builtin-rain"))
    out = shadow.lesson_dir("abcdef0d1a16")
    assert sorted(p.name for p in out.iterdir()) == ["lesson.mp3", "lesson.mp4", "lesson.srt", "timeline.json"]
    for name in ("lesson.mp4", "lesson.mp3"):
        assert float(_probe(out / name)["format"]["duration"]) == pytest.approx(meta["duration"], abs=0.15)
    # khoảng lặng giữa các câu giờ có tiếng mưa
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out / "lesson.mp3"), "-ss", "2", "-t", "1.5",
                          "-f", "f32le", "-ac", "1", "-"], capture_output=True, check=True).stdout
    assert np.abs(np.frombuffer(pcm, dtype=np.float32)).max() > 0.005


def test_build_with_slower_second_reading():
    utts = dialogue.parse_dialogue("你好。\n好的。")
    s = Settings(voice_a="A", voice_b="B", repeats=2, speed=1.0, speed2=0.7)
    meta = dialogue.build("abcdef0d1a13", utts, [_tone(1.0), _tone(0.8)], [None, None], s, lambda p: None,
                          zh2_raw=[_tone(1.4), _tone(1.1)])
    timeline = json.loads((shadow.lesson_dir("abcdef0d1a13") / "timeline.json").read_text(encoding="utf-8"))
    reads = [(st["kind"], st["line"], round(st["duration"], 1)) for st in timeline["steps"] if st["kind"] != "pause"]
    assert reads == [("zh", 0, 1.0), ("zh2", 0, 1.4), ("zh", 1, 0.8), ("zh2", 1, 1.1)]
    assert timeline["settings"]["speed2"] == 0.7 and meta["duration"] > 0


def test_build_caps_total_length_for_youtube(monkeypatch):
    monkeypatch.setattr(dialogue, "MAX_TOTAL_S", 20.0)
    utts = [Utterance("好的。", speaker=0)]
    meta = dialogue.build("abcdef0d1a11", utts, [_tone(2.0)], [None],
                          Settings(voice_a="A", voice_b="B", repeats=1, loops=50), lambda p: None)
    assert 1 <= meta["loops"] < 50 and meta["duration"] <= 20.0


def _timeline(loops=1, duration=None):
    lines = [{**dialogue.asdict(u), "pinyin": chinese.pinyin_text(u.zh)} for u in dialogue.parse_dialogue(SAMPLE)]
    steps, t = [], 0.0
    for i, ln in enumerate(lines):
        steps.append({"kind": "zh", "line": i, "start": t, "duration": 12.0})
        t += 12.0
    return {"kind": "dialogue", "duration": duration or t * loops, "loop_duration": t, "loops": loops, "lines": lines,
            "steps": steps, "settings": {"repeats": 2, "vi_voice": "Adam"}}


def test_youtube_draft_for_dialogue():
    lesson = {"id": "abcdef0d1a12", "title": "Khẩu ngữ", "voice": "Xiaoxiao & Yunxi", "lines": 4}
    d = youtube.draft(lesson, _timeline(loops=1))
    assert "tiếng Trung" in d["title"] and len(d["title"]) <= 100
    assert "Máfan nǐ zhàn qǐlai yīxià." in d["description"] and "B: 好的。" in d["description"]
    assert d["thumbnail"]["quote"] == "你抽烟吗？"
    slow = _timeline(loops=1)
    slow["settings"].update(speed=1.0, speed2=0.8)
    assert "lần 2 ở tốc độ 0.8x" in youtube.draft(lesson, slow)["description"]
    assert youtube.chapters(_timeline(loops=1)) == []        # 2 đoạn hội thoại: YouTube cần ít nhất 3 mốc
    three = _timeline(loops=1)
    three["lines"][3]["block"] = 2
    assert youtube.chapters(three) == ["0:00 Hội thoại 1: 麻烦你站起来一下。", "0:24 Hội thoại 2: 你抽烟吗？",
                                       "0:36 Hội thoại 3: 不抽，谢谢。"]

    long = _timeline(loops=600, duration=8 * 3600)
    assert "Nghe tiếng Trung 8 tiếng" in youtube.draft(lesson, long)["title"]
    assert youtube.chapters(_timeline(loops=3))[2] == "1:36 Lượt nghe 3"
    with_intro = _timeline(loops=3)
    with_intro.update(intro_duration=5.0, duration=with_intro["duration"] + 5)
    assert youtube.chapters(with_intro)[:3] == ["0:00 Lượt nghe 1", "0:53 Lượt nghe 2", "1:41 Lượt nghe 3"]


def test_thumbnail_renders_chinese_quote(tmp_path):
    lesson = {"title": "Khẩu ngữ", "voice": "Xiaoxiao & Yunxi", "lines": 4}
    out = thumbnail.render(lesson, _timeline(loops=600, duration=8 * 3600), tmp_path / "t.jpg")
    from PIL import Image
    assert Image.open(out).size == (1280, 720)


def test_music_library_builtin_upload_and_remove(tmp_path):
    from app import music
    items = {m["id"]: m for m in music.list_music()}
    assert {"builtin-pad", "builtin-rain", "builtin-waves"} <= set(items)
    for k in ("builtin-pad", "builtin-waves"):
        p = music.path(k)
        data = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-"],
                                            capture_output=True, check=True).stdout, dtype=np.float32)
        assert len(data) > 50 * SR and 0.01 < np.abs(data).max() <= 0.9

    src = tmp_path / "song.wav"
    import soundfile as sf
    sf.write(str(src), _tone(6.0, 330), SR)
    item = music.add(src, "Bài của tôi")
    assert item["name"] == "Bài của tôi" and 5.5 < item["duration"] < 6.5
    assert music.path(item["id"]).suffix == ".m4a"
    short = tmp_path / "short.wav"
    sf.write(str(short), _tone(2.0), SR)
    with pytest.raises(ValueError):
        music.add(short, "ngắn")
    music.remove(item["id"])
    assert music.path(item["id"]) is None
    with pytest.raises(KeyError):
        music.remove("builtin-rain")
    assert music.path("../studio") is None


TAGGED = ("B: [cười] 我和朋友一起去*旅游*了。[nghỉ 500ms] 你呢？ | [cười] Mình đi *du lịch* cùng bạn bè. [nghỉ 500ms] "
          "Còn bạn thì sao? | [laugh] I went *traveling* with my friends. [pause 500ms] How about you?")


def test_tags_drive_audio_but_never_show_on_screen():
    (u,) = dialogue.parse_dialogue(TAGGED)
    assert u.zh == "我和朋友一起去旅游了。你呢？" and u.zh_marks == [[7, 9]]
    assert u.vi == "Mình đi du lịch cùng bạn bè. Còn bạn thì sao?" and u.vi[u.vi_marks[0][0]:u.vi_marks[0][1]] == "du lịch"
    assert u.en == "I went traveling with my friends. How about you?"
    assert u.zh_say == "[cười] 我和朋友一起去旅游了。[nghỉ 500ms] 你呢？" and u.vi_say.startswith("[cười] Mình")
    assert dialogue.parse_dialogue("你好。 | Chào.")[0].zh_say == ""
    assert dialogue.vieneu_tags("[sigh] A [pause 1,5s] B [Clears throat] [笑]") == \
        "[thở dài] A [nghỉ 1,5s] B [hắng giọng] [cười]"
    assert dialogue.strip_tags("Okay, [pause 500ms] then [smile]") == "Okay, then [smile]"   # thẻ lạ giữ nguyên


def test_chinese_tags_become_silence_and_interjections(monkeypatch):
    said = []

    def fake(text, voice, speed, on_download=None):
        said.append(text)
        return np.ones(int(0.5 * dialogue.SR), dtype=np.float32)
    monkeypatch.setattr(dialogue.chinese, "synthesize", fake)
    half = int(0.5 * dialogue.SR)
    audio = dialogue.speak_zh("[cười] 我们去海边了，[nghỉ 500ms] 那里很好。[sigh]", "v", 1.0)
    assert said == ["哈哈哈！", "我们去海边了，", "那里很好。", "唉……"]     # cảm xúc thành thán từ, đúng vị trí
    gap = int(dialogue.EMOTION_GAP_S * dialogue.SR)
    assert len(audio) == half + gap + half + half + half + half + gap
    pause = audio[half + gap + half:half + gap + 2 * half]
    assert not pause.any()                                            # [nghỉ 500ms] là khoảng lặng thật
    with pytest.raises(ValueError, match="không có chữ"):
        dialogue.speak_zh("[nghỉ 1s]", "v", 1.0)
