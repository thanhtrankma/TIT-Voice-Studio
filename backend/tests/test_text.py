from app.text import Pause, apply_dictionary, spoken_length, to_segments


def test_pause_seconds_and_ms():
    segs = to_segments("Một. [nghỉ 2s] Hai. [nghỉ 500ms] Ba.", {})
    assert segs == ["Một.", Pause(2.0), "Hai.", Pause(0.5), "Ba."]


def test_pause_is_capped_and_accepts_comma():
    segs = to_segments("A [nghỉ 30s] B [nghỉ 1,5s] C", {})
    assert Pause(10.0) in segs and Pause(1.5) in segs


def test_emotion_tags_are_kept_for_the_model():
    assert to_segments("Vui quá [cười] nhỉ", {}) == ["Vui quá [cười] nhỉ"]


def test_paragraphs_get_a_short_gap():
    segs = to_segments("Dòng một.\nDòng hai.", {})
    assert segs[0] == "Dòng một." and isinstance(segs[1], Pause) and segs[2] == "Dòng hai."


def test_long_paragraph_is_split_on_sentences():
    text = " ".join(["Đây là một câu khá dài để kiểm tra việc chia đoạn."] * 20)
    segs = to_segments(text, {})
    assert len(segs) > 1 and all(len(s) <= 400 for s in segs)


def test_dictionary_matches_whole_words_longest_first():
    d = {"TP": "thành phố", "TP.HCM": "thành phố Hồ Chí Minh", "KTX": "ký túc xá"}
    assert apply_dictionary("Ở TP.HCM có KTX", d) == "Ở thành phố Hồ Chí Minh có ký túc xá"
    assert apply_dictionary("KTXA không đổi", d) == "KTXA không đổi"


def test_spoken_length_ignores_pause_tags():
    assert spoken_length("Xin [nghỉ 2s] chào") == len("Xin  chào")
