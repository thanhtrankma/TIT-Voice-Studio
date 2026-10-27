"""Kiểm thử giọng bản xứ (Kokoro). Phần cần model thật tự bỏ qua khi model chưa tải."""
import hashlib
import os
import tempfile
from collections import namedtuple
from pathlib import Path

import pytest

os.environ.setdefault("TIT_DATA_DIR", tempfile.mkdtemp(prefix="tit-qa-"))
os.environ.setdefault("TIT_MODELS_DIR", str(Path(__file__).resolve().parents[1] / "data" / "models"))

from app import engine as eng, english  # noqa: E402

T = namedtuple("T", "phoneme start end")


def test_voice_catalog():
    voices = english.voices()
    assert {v["accent"] for v in voices} == {"us", "uk"}
    assert all(english.is_native(v["id"]) and english.has_voice(v["id"]) for v in voices)
    assert english.label("kokoro:bm_george") == "George (Anh)"
    assert not english.has_voice("kokoro:zz_nobody") and not english.is_native("Adam")


def test_group_starts_splits_on_spaces():
    timings = [T("ð", .1, .12), T("ə", .12, .14), T(" ", .14, .19), T("m", .19, .22), T("i", .22, .3),
               T(".", .3, .4), T(" ", .4, .5), T(" ", .5, .55), T("w", .55, .6)]
    assert english.group_starts(timings) == [.1, .19, .55]


def test_align_words_direct_and_by_count():
    assert english.align_words(["a", "b"], [0.1, 0.5], lambda w: 99) == [0.1, 0.5]
    # "1,250" đọc thành 4 từ âm vị: dùng số nhóm của từng từ để ghép
    counts = {"We": 1, "sold": 1, "1,250": 4, "tickets.": 1}
    groups = [0.1, 0.3, 0.7, 1.0, 1.3, 1.6, 2.5]
    assert english.align_words(list(counts), groups, counts.get) == [0.1, 0.3, 0.7, 2.5]
    assert english.align_words(["a", "b"], [0.1, 0.5, 0.9], lambda w: 1) is None   # vẫn lệch → ước lượng
    assert english.align_words(["a"], [], lambda w: 1) is None


def test_download_verifies_checksum(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.bin").write_bytes(b"x" * 3000)
    (src / "bad.bin").write_bytes(b"y" * 10)
    monkeypatch.setattr(english, "BASE_URL", src.as_uri() + "/")
    monkeypatch.setattr(english, "MODEL_DIR", tmp_path / "models")
    monkeypatch.setattr(english, "FILES", {"good.bin": (hashlib.sha256(b"x" * 3000).hexdigest(), 3000)})
    seen = []
    english.download(lambda done, total: seen.append((done, total)))
    assert (tmp_path / "models" / "good.bin").read_bytes() == b"x" * 3000 and seen[-1] == (3000, 3000)
    assert english.installed() and english.status()["download_mb"] == 0

    monkeypatch.setattr(english, "FILES", {"bad.bin": ("0" * 64, 10)})
    with pytest.raises(RuntimeError, match="mã kiểm tra"):
        english.download()
    assert not list((tmp_path / "models").glob("bad.bin*"))   # không để lại file hỏng


needs_model = pytest.mark.skipif(not english.installed(), reason="chưa tải model Kokoro")


@needs_model
def test_synthesize_returns_48k_audio_and_word_starts():
    text = "The meeting starts at 3:30 p.m. on Wednesday."
    audio, starts = english.synthesize(text, "kokoro:af_heart")
    seconds = len(audio) / eng.SAMPLE_RATE
    assert 2 < seconds < 6
    assert starts is not None and len(starts) == len(text.split())
    assert starts == sorted(starts) and starts[-1] < seconds
