"""Giọng tiếng Trung phổ thông (Kokoro) và pinyin cho video hội thoại song ngữ.

Kokoro-82M (cùng model với giọng tiếng Anh ở app/english.py) có sẵn 8 giọng tiếng Trung.
Các giọng này được huấn luyện với âm vị của misaki (pinyin có mũi tên thanh điệu), nên chữ Hán
phải qua `misaki.zh` rồi mới đưa vào model; dùng espeak như tiếng Anh thì đọc sai thanh và
sai âm (Whisper nghe "不抽，谢谢" thành "不凑写戏言"). Pinyin hiển thị trên video lấy từ
pypinyin, tách từ bằng jieba để viết liền theo từ ("Máfan nǐ zhàn qǐlái yīxià.").
"""
import functools
import logging
import unicodedata
from typing import List, Optional, Tuple

import numpy as np

from . import english

log = logging.getLogger("tit.chinese")

PREFIX = english.PREFIX
PREVIEW_TEXT = "你好！我是你的中文口语伙伴。我们一起练习吧。"

# (mã giọng, tên, giới tính, nổi bật); thứ tự theo chất lượng nghe thử bằng Whisper
_VOICES = [
    ("zf_xiaoxiao", "Xiaoxiao", "female", True),
    ("zf_xiaobei", "Xiaobei", "female", False),
    ("zf_xiaoni", "Xiaoni", "female", False),
    ("zf_xiaoyi", "Xiaoyi", "female", False),
    ("zm_yunxi", "Yunxi", "male", True),
    ("zm_yunjian", "Yunjian", "male", False),
    ("zm_yunxia", "Yunxia", "male", False),
    ("zm_yunyang", "Yunyang", "male", False),
]


def voices() -> List[dict]:
    return [{
        "id": PREFIX + key, "name": name, "gender": gender, "region": None, "accent": "zh",
        "style": "Tiếng Trung", "description": f"{'Nữ' if gender == 'female' else 'Nam'} · Tiếng Trung phổ thông",
        "featured": featured, "custom": False,
    } for key, name, gender, featured in _VOICES]


def _find(voice: str) -> Optional[tuple]:
    return next((v for v in _VOICES if PREFIX + v[0] == voice), None)


def has_voice(voice: str) -> bool:
    return _find(voice) is not None


def label(voice: str) -> str:
    v = _find(voice)
    return v[1] if v else voice


def status() -> dict:
    return {**english.status(), "voices": voices()}


# ── đọc câu ────────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _g2p():
    from misaki import zh

    return zh.ZHG2P()


def has_hanzi(text: str) -> bool:
    return any("\u3400" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff" for c in text)


def phonemes(text: str) -> str:
    out = _g2p()(text)
    return (out[0] if isinstance(out, tuple) else out).strip()


def synthesize(text: str, voice: str, speed: float = 1.0,
               on_download: Optional[english.ProgressFn] = None) -> np.ndarray:
    """Đọc một câu tiếng Trung, trả audio 48 kHz."""
    v = _find(voice)
    if not v:
        raise ValueError(f"Không có giọng {voice}.")
    ph = phonemes(text)
    if not ph:
        raise ValueError(f"Câu “{text}” không có chữ để đọc.")
    audio, sr = english.model(on_download).create(ph, voice=v[0], speed=speed, lang="cmn", is_phonemes=True)
    return english.resample(np.asarray(audio, dtype=np.float32), sr)


# ── pinyin ─────────────────────────────────────────────────────────────────

PUNCT = {"。": ".", "，": ",", "？": "?", "！": "!", "：": ":", "；": ";", "、": ",", "“": "\"", "”": "\"",
         "‘": "'", "’": "'", "（": "(", "）": ")", "《": "«", "》": "»", "～": "~", "·": "·"}
_OPENING = set("“‘（《([")      # dấu mở: dính vào từ sau thay vì từ trước
_SENTENCE_END = (".", "?", "!", "…")


def _is_proper(word: str, flag: str) -> bool:
    """Tên riêng cần viết hoa: địa danh, tổ chức, hoặc tên người ít gặp.

    Từ điển jieba gắn nhãn tên người cho cả từ thường hay gặp (谢谢, 安静, 文明 vì là họ + tên),
    nên chỉ tin nhãn đó khi từ hiếm (tần suất thấp hoặc không có trong từ điển, như 小明).
    """
    import jieba

    if flag in ("ns", "nt"):
        return True
    return flag in ("nr", "nrfg", "nrt") and jieba.dt.FREQ.get(word, 0) < 500


Part = Tuple[str, int]          # (chữ, vị trí ký tự Hán tương ứng trong câu)
Word = List[Part]               # các âm tiết viết liền của một từ, kèm dấu câu dính hai đầu


def _is_punct(text: str) -> bool:
    return all(c in PUNCT or unicodedata.category(c)[0] in "PZ" for c in text)


@functools.lru_cache(maxsize=1)
def _pinyin_fn():
    # CC-CEDICT có thanh nhẹ (máfan, xièxie, qǐlai) như sách học; bộ từ mặc định của pypinyin
    # đọc mọi âm tiết theo thanh gốc. Không nạp bộ chữ đơn kxhc1983: nó đổi 行 thành háng.
    from pypinyin import Style, pinyin
    from pypinyin_dict.phrase_pinyin_data import cc_cedict

    cc_cedict.load()
    return lambda tok: [s[0] for s in pinyin(tok, style=Style.TONE, errors=lambda s: list(s))]


@functools.lru_cache(maxsize=4096)
def romanize(zh: str) -> Tuple[Tuple[Part, ...], ...]:
    """Pinyin có dấu thanh, chia theo từ: mỗi âm tiết nhớ ký tự Hán của nó để tô từ khoá.

    Dấu câu Trung đổi sang dấu Latin, dính vào từ bên cạnh; 儿 hoá thành "r" (nǎr);
    chữ cái đầu câu và tên riêng (jieba gắn nhãn tên người, địa danh, tổ chức) viết hoa.
    """
    import jieba.posseg

    to_pinyin = _pinyin_fn()
    words: List[Word] = []
    prefix: List[Part] = []    # dấu mở chờ dính vào từ sau
    pos = 0
    for tok, flag in jieba.posseg.cut(zh):
        start, pos = pos, pos + len(tok)
        if not tok.strip():
            continue
        if _is_punct(tok):
            for i, c in enumerate(tok):
                if c.isspace():
                    continue
                part = (PUNCT.get(c, c), start + i)
                if c in _OPENING:
                    prefix.append(part)
                elif words:
                    words[-1].append(part)
                else:
                    prefix.append(part)
            continue
        syl = to_pinyin(tok)
        if len(syl) != len(tok):   # pypinyin gộp chuỗi không phải chữ Hán: giữ nguyên cả cụm
            word = [(tok, start)]
        else:
            word = []
            for i, s in enumerate(syl):
                if tok[i] == "儿" and i and s in ("er", "ér"):
                    word.append(("r", start + i))
                else:
                    word.append((s, start + i))
            if word and _is_proper(tok, flag):
                word[0] = (word[0][0][:1].upper() + word[0][0][1:], word[0][1])
        words.append(prefix + word)
        prefix = []
    if prefix:
        words.append(prefix)

    out, cap = [], True
    for word in words:
        parts = []
        for text, idx in word:
            if cap and text[:1].isalpha():
                text, cap = text[:1].upper() + text[1:], False
            if text.endswith(_SENTENCE_END):
                cap = True
            parts.append((text, idx))
        out.append(tuple(parts))
    return tuple(out)


def pinyin_text(zh: str) -> str:
    return " ".join("".join(t for t, _ in word) for word in romanize(zh))
