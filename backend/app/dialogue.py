"""Video hội thoại song ngữ Trung–Việt để "ngâm" tiếng: nghe thụ động, nghe trước khi ngủ.

Màn hình chia đôi: người A bên trái, người B bên phải. Mỗi bên hiện câu tiếng Anh (tuỳ chọn),
chữ Hán, pinyin và nghĩa tiếng Việt; từ khoá đánh dấu bằng *…* được tô màu ở cả chữ Hán,
pinyin lẫn tiếng Việt. Bên đang nói sáng lên, bên kia mờ đi.

Mỗi câu tiếng Trung đọc bằng giọng Kokoro (app/chinese.py), lặp vài lần, có thể chen bản đọc
nghĩa tiếng Việt bằng VieNeu. Cả bài lặp nhiều lượt thành video dài vài giờ: chỉ encode một
lượt rồi nối các bản sao bằng stream copy, nên video 8 tiếng dựng nhanh gần bằng video một lượt.
"""
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw

from . import chinese, design, engine as eng, english, music, shadow, text as textproc

SR = eng.SAMPLE_RATE
MAX_LINES = 300
MAX_ZH_CHARS = 80
MAX_TEXT_CHARS = 200
MAX_LOOPS = 60
MAX_TOTAL_S = 11.5 * 3600      # YouTube nhận video tối đa 12 giờ
LEAD_S = 0.8                    # khoảng lặng đầu mỗi lượt: các lượt nối nhau không dính tiếng
TAIL_S = 1.5
FPS = 30
# Độ dài mỗi lượt làm tròn lên bội số của 25.600 mẫu (0,533 s) = bội chung của một khung hình
# (1.600 mẫu ở 30 fps) và một khung AAC (1.024 mẫu): nối các lượt bằng stream copy không lệch tiếng.
QUANTUM = 25_600

# ── bài hội thoại ──────────────────────────────────────────────────────────


@dataclass
class Utterance:
    zh: str
    vi: str = ""
    en: str = ""
    speaker: int = 0                                          # 0 = A (trái), 1 = B (phải)
    block: int = 0                                            # đoạn hội thoại, cách nhau bằng dòng trống
    zh_marks: List[List[int]] = field(default_factory=list)   # [đầu, cuối) theo ký tự, từ khoá tô màu
    vi_marks: List[List[int]] = field(default_factory=list)
    zh_say: str = ""                                          # câu đọc còn giữ thẻ [nghỉ …], [cười]; "" = như zh
    vi_say: str = ""


@dataclass
class Settings:
    voice_a: str                 # tên hiển thị
    voice_b: str
    vi_voice: str = ""           # "" = không đọc nghĩa tiếng Việt
    title: str = ""
    repeats: int = 2             # đọc mỗi câu tiếng Trung mấy lần
    speed: float = 1.0
    speed2: Optional[float] = None   # tốc độ lần đọc thứ 2 (thường chậm hơn); None = như lần 1
    pause: float = 1.0           # giây nghỉ sau mỗi lượt đọc
    loops: int = 1               # lặp cả bài mấy lượt
    show_en: bool = True
    intro: bool = True           # đoạn giới thiệu vài giây ở đầu video
    music: str = ""              # tên nhạc nền ("" = không có)
    music_volume: float = 0.4    # 0–1 so với mức chuẩn của nhạc (app/music.py)


def parse_marks(raw: str) -> Tuple[str, List[List[int]]]:
    """Bỏ dấu * đánh dấu từ khoá, trả câu sạch và các khoảng [đầu, cuối) được đánh dấu."""
    out: List[str] = []
    spans: List[List[int]] = []
    start = None
    for c in raw.strip():
        if c in "*＊":
            if start is None:
                start = len(out)
            else:
                if len(out) > start:
                    spans.append([start, len(out)])
                start = None
        else:
            out.append(c)
    if start is not None and len(out) > start:
        spans.append([start, len(out)])
    return "".join(out), spans


# Thẻ trong câu, viết tiếng Việt, Anh hoặc Trung: [nghỉ 500ms] / [pause 1s] chèn khoảng lặng; thẻ cảm xúc
# [cười] / [laugh] / [笑]… chỉ giọng Việt VieNeu thể hiện được. Chữ trên màn hình, pinyin và phụ đề bỏ hết thẻ.
_PAUSE_TAG = re.compile(r"\[\s*(?:nghỉ|pause|停顿)\s*(\d+(?:[.,]\d+)?)\s*(ms|s)\s*\]", re.IGNORECASE)
_EMOTIONS = [("cười", r"cười|laugh(?:s|ing)?|笑"), ("thở dài", r"thở dài|sigh(?:s|ing)?|叹气"),
             ("hắng giọng", r"hắng giọng|clears? (?:one's |his |her |the )?throat|清嗓子?")]
_EMOTION_TAG = re.compile(r"\[\s*(" + "|".join(p for _, p in _EMOTIONS) + r")\s*\]", re.IGNORECASE)
_ANY_TAG = re.compile(r"\s*(?:" + _PAUSE_TAG.pattern + "|" + _EMOTION_TAG.pattern + r")\s*", re.IGNORECASE)
_CJK = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]")


def strip_tags(text: str) -> str:
    """Bỏ thẻ nghỉ, thẻ cảm xúc để hiện chữ; chỗ thẻ đứng giữa hai từ Latin còn lại một dấu cách."""
    def join(m: re.Match) -> str:
        before, after = m.string[:m.start()][-1:], m.string[m.end():][:1]
        if not before or not after or _CJK.match(before) or _CJK.match(after) or after in ",.!?;:…":
            return ""
        return " "
    return _ANY_TAG.sub(join, text).strip()


def vieneu_tags(text: str) -> str:
    """Đổi thẻ viết kiểu Anh/Trung sang thẻ VieNeu hiểu: [pause 1s] → [nghỉ 1s], [laugh] → [cười]."""
    def emotion(m: re.Match) -> str:
        return "[" + next(tag for tag, p in _EMOTIONS if re.fullmatch(p, m[1].strip(), re.IGNORECASE)) + "]"
    return _EMOTION_TAG.sub(emotion, _PAUSE_TAG.sub(lambda m: f"[nghỉ {m[1]}{m[2]}]", text))


def _spoken(raw: str, shown: str) -> str:
    """Câu đọc (giữ thẻ) nếu khác chữ hiện trên màn hình, không thì ""."""
    say = raw.replace("*", "").replace("＊", "").strip()
    return say if say != shown else ""


_SPEAKER = re.compile(r"^\s*([ABab])\s*[:：]\s*")


def parse_dialogue(text: str) -> List[Utterance]:
    """Mỗi dòng một câu: `中文 | Tiếng Việt | English` (hai phần sau tuỳ chọn).

    Trong một đoạn, người nói luân phiên A, B, A…; dòng trống mở đoạn mới (lại bắt đầu từ A).
    Ghi `A:` hoặc `B:` đầu dòng để chỉ định người nói.
    """
    out: List[Utterance] = []
    block, prev = 0, None
    for raw in text.splitlines():
        if not raw.strip():
            if prev is not None:
                block, prev = block + 1, None
            continue
        m = _SPEAKER.match(raw)
        parts = [p.strip() for p in raw[m.end() if m else 0:].split("|")]
        zh, zh_marks = parse_marks(strip_tags(parts[0]))
        if not zh:
            continue
        vi, vi_marks = parse_marks(strip_tags(parts[1])) if len(parts) > 1 else ("", [])
        en = strip_tags(parts[2].replace("*", "")) if len(parts) > 2 else ""
        speaker = ("AB".index(m[1].upper()) if m else 0 if prev is None else 1 - prev)
        out.append(Utterance(zh, vi, en, speaker, block, zh_marks, vi_marks, _spoken(parts[0], zh),
                             _spoken(parts[1], vi) if len(parts) > 1 else ""))
        prev = speaker
    return out


def exchanges(utts: Sequence[Utterance]) -> Tuple[List[Dict[int, int]], List[int]]:
    """Gom câu thành từng lượt hỏi–đáp hiện cùng màn hình: (các ô {người nói: câu}, lượt của mỗi câu)."""
    groups: List[Dict[int, int]] = []
    of: List[int] = []
    for i, u in enumerate(utts):
        g = groups[-1] if groups else None
        if g is None or utts[next(iter(g.values()))].block != u.block or u.speaker in g or \
                (u.speaker == 0 and 1 in g):
            groups.append({})
        groups[-1][u.speaker] = i
        of.append(len(groups) - 1)
    return groups, of


# ── âm thanh ───────────────────────────────────────────────────────────────


def second_speed(s: Settings) -> Optional[float]:
    """Tốc độ lần đọc thứ 2 nếu khác lần 1 (cần đọc riêng một bản), không thì None."""
    if s.repeats < 2 or s.speed2 is None or abs(s.speed2 - s.speed) < 0.01:
        return None
    return s.speed2


def synthesize(utts: Sequence[Utterance], voices: Tuple[str, str], speed: float,
               speak_vi: Optional[Callable[[str], np.ndarray]], on_progress: Callable[[float], None],
               on_download: Optional[english.ProgressFn] = None, speed2: Optional[float] = None,
               intro_text: str = "") -> tuple:
    """Đọc từng câu (luồng mô hình). Câu trùng nhau chỉ đọc một lần.

    `speed2`: đọc thêm bản cho lần thứ 2 ở tốc độ này. Kokoro tự đọc chậm (ngắt nghỉ, kéo âm tự nhiên)
    nên nghe tự nhiên hơn kéo giãn bản thường. `intro_text`: câu giọng Việt đọc ở đoạn giới thiệu.
    Trả (clips Trung, clips Trung lần 2 hoặc None, clips Việt, clip giới thiệu hoặc None).
    """
    cache: Dict[tuple, np.ndarray] = {}
    zh: List[np.ndarray] = []
    zh2: Optional[List[np.ndarray]] = [] if speed2 else None
    vi: List[Optional[np.ndarray]] = []
    for i, u in enumerate(utts):
        for rate, out in ((speed, zh), (speed2, zh2)):
            if out is None:
                continue
            key = ("zh", voices[u.speaker], u.zh_say or u.zh, rate)
            if key not in cache:
                cache[key] = speak_zh(u.zh_say or u.zh, voices[u.speaker], rate, on_download)
            out.append(cache[key])
        if speak_vi and u.vi:
            key = ("vi", u.vi_say or u.vi)
            if key not in cache:
                cache[key] = speak_vi(vieneu_tags(u.vi_say or u.vi))
            vi.append(cache[key])
        else:
            vi.append(None)
        on_progress((i + 1) / len(utts))
    intro = speak_vi(intro_text) if speak_vi and intro_text else None
    return zh, zh2, vi, intro


def speak_zh(text: str, voice: str, speed: float, on_download: Optional[english.ProgressFn] = None) -> np.ndarray:
    """Đọc câu tiếng Trung có thẻ: [nghỉ …] thành khoảng lặng. Thẻ cảm xúc bị bỏ qua vì giọng Kokoro
    không cười hay thở dài được (đọc thành chữ thì còn tệ hơn)."""
    parts = _PAUSE_TAG.split(text)          # [chữ, số, đơn vị, chữ, …]
    audio: List[np.ndarray] = []
    for i in range(0, len(parts), 3):
        chunk = strip_tags(parts[i])
        if chinese.has_hanzi(chunk) or re.search(r"[A-Za-z0-9]", chunk):
            audio.append(chinese.synthesize(chunk, voice, speed, on_download))
        if i + 1 < len(parts):
            value = float(parts[i + 1].replace(",", "."))
            seconds = min(value / 1000 if parts[i + 2].lower() == "ms" else value, textproc.MAX_PAUSE_S)
            audio.append(np.zeros(int(seconds * SR), dtype=np.float32))
    if not any(len(a) and a.any() for a in audio):
        raise ValueError(f"Câu “{strip_tags(text)}” không có chữ để đọc.")
    return np.concatenate(audio)


def intro_text(title: str) -> str:
    return f"Luyện nghe tiếng Trung: {title.strip() or 'hội thoại hằng ngày'}."


def chime(seconds: float = 1.6) -> np.ndarray:
    """Hai tiếng chuông nhẹ (Mi, Si) mở đầu đoạn giới thiệu."""
    t = np.arange(int(seconds * SR)) / SR
    out = np.zeros_like(t)
    for start, f in ((0.0, 659.25), (0.22, 987.77)):
        tt = np.clip(t - start, 0, None)
        env = np.where(t >= start, np.exp(-tt / 0.55) * np.clip(tt / 0.005, 0, 1), 0)
        out += env * (np.sin(2 * np.pi * f * tt) + 0.2 * np.sin(4 * np.pi * f * tt))
    return (out * 0.12).astype(np.float32)


@dataclass
class Step:
    kind: str           # zh | zh2 (lần đọc thứ 2 ở tốc độ riêng) | vi | pause
    line: int           # -1: khoảng lặng đầu lượt
    start: float = 0.0
    duration: float = 0.0


def plan_steps(utts: Sequence[Utterance], zh_d: Sequence[float], vi_d: Sequence[float], s: Settings,
               zh2_d: Optional[Sequence[float]] = None) -> List[Step]:
    """Dòng thời gian một lượt: mỗi câu đọc tiếng Trung `repeats` lần, nghĩa tiếng Việt sau lần đầu.

    Có `zh2_d` (độ dài bản đọc ở tốc độ lần 2) thì lần thứ 2 dùng bản đó; lần 3 trở đi lại như lần 1.
    """
    steps = [Step("pause", -1, duration=LEAD_S)]
    for i, u in enumerate(utts):
        for r in range(s.repeats):
            read = Step("zh2", i, duration=zh2_d[i]) if r == 1 and zh2_d else Step("zh", i, duration=zh_d[i])
            steps += [read, Step("pause", i, duration=s.pause)]
            if r == 0 and vi_d[i]:
                steps += [Step("vi", i, duration=vi_d[i]), Step("pause", i, duration=s.pause)]
        if i + 1 < len(utts) and utts[i + 1].block != u.block:
            steps[-1].duration += s.pause * 1.5      # nghỉ dài hơn khi sang đoạn hội thoại mới
    steps[-1].duration += TAIL_S
    t = 0.0
    for st in steps:
        st.start = round(t, 3)
        t += st.duration
    return steps


# ── chữ nhiều kiểu trên một dòng ───────────────────────────────────────────

Seg = Tuple[str, bool]                  # (chữ, là từ khoá)
Token = Tuple[Tuple[Seg, ...], bool]    # (các đoạn viết liền, có dấu cách sau)


def _in(marks: Sequence[Sequence[int]], i: int) -> bool:
    return any(a <= i < b for a, b in marks)


def _segs(chars: Sequence[Tuple[str, bool]]) -> Tuple[Seg, ...]:
    """Gộp các ký tự liền nhau cùng kiểu thành đoạn."""
    out: List[List] = []
    for text, hl in chars:
        if out and out[-1][1] == hl:
            out[-1][0] += text
        else:
            out.append([text, hl])
    return tuple((t, h) for t, h in out)


_CJK_CLOSE = set("。，、？！：；”’）》…—～.,?!:;)\"'")
_CJK_OPEN = set("“‘（《(")


def hanzi_tokens(zh: str, marks) -> List[Token]:
    """Mỗi từ (jieba) một token để không xuống dòng giữa từ; dấu câu không đứng đầu dòng."""
    import jieba

    groups: List[List[Tuple[str, bool]]] = []
    pending: List[Tuple[str, bool]] = []
    pos = 0
    for tok in jieba.cut(zh):
        start, pos = pos, pos + len(tok)
        for i, c in enumerate(tok):
            item = (c, _in(marks, start + i))
            if c in _CJK_OPEN:
                pending.append(item)
            elif (c in _CJK_CLOSE or c.isspace()) and groups and not pending:
                groups[-1].append(item)
            elif i and groups and not pending:
                groups[-1].append(item)                 # chữ tiếp theo trong cùng từ
            else:
                groups.append(pending + [item])
                pending = []
    if pending:
        groups.append(pending)
    return [(_segs(g), False) for g in groups]


def pinyin_tokens(zh: str, marks) -> List[Token]:
    return [(_segs([(text, _in(marks, idx)) for text, idx in word]), True) for word in chinese.romanize(zh)]


def word_tokens(text: str, marks) -> List[Token]:
    out = []
    for m in re.finditer(r"\S+", text):
        out.append((_segs([(c, _in(marks, m.start() + j)) for j, c in enumerate(m[0])]), True))
    return out


@dataclass
class Look:
    font: object
    font_hl: object
    color: tuple
    color_hl: tuple
    line_h: float


def _tok_w(tok: Token, look: Look) -> float:
    return sum((look.font_hl if hl else look.font).getlength(t) for t, hl in tok[0])


def _wrap(tokens: List[Token], look: Look, width: float) -> List[List[int]]:
    space = look.font.getlength(" ")
    rows: List[List[int]] = [[]]
    w = 0.0
    for i, tok in enumerate(tokens):
        tw = _tok_w(tok, look)
        gap = space if rows[-1] and tokens[rows[-1][-1]][1] else 0.0
        if rows[-1] and w + gap + tw > width:
            rows.append([i])
            w = tw
        else:
            rows[-1].append(i)
            w += gap + tw
    return rows


def _balanced(tokens: List[Token], look: Look, width: float) -> List[List[int]]:
    rows = _wrap(tokens, look, width)
    if len(rows) < 2:
        return rows
    lo, hi = width * 0.4, width
    for _ in range(14):
        mid = (lo + hi) / 2
        if len(_wrap(tokens, look, mid)) == len(rows):
            hi = mid
        else:
            lo = mid
    return _wrap(tokens, look, hi)


def _row_w(tokens: List[Token], row: List[int], look: Look) -> float:
    space = look.font.getlength(" ")
    return sum(_tok_w(tokens[j], look) for j in row) + sum(space for j in row[:-1] if tokens[j][1])


def _draw_rows(dr: ImageDraw.ImageDraw, tokens: List[Token], rows: List[List[int]], look: Look, cx: float,
               y: float) -> float:
    """Vẽ các dòng căn giữa quanh `cx` từ đỉnh `y`; trả đỉnh dòng kế tiếp."""
    space = look.font.getlength(" ")
    ascent = max(look.font.getmetrics()[0], look.font_hl.getmetrics()[0])
    for row in rows:
        x = cx - _row_w(tokens, row, look) / 2
        base = y + ascent
        for j in row:
            for text, hl in tokens[j][0]:
                f = look.font_hl if hl else look.font
                dr.text((x, base), text, font=f, fill=look.color_hl if hl else look.color, anchor="ls")
                x += f.getlength(text)
            if tokens[j][1]:
                x += space
        y += look.line_h
    return y


# ── khung hình ─────────────────────────────────────────────────────────────

BG_FROM, BG_TO = "#0b1026", "#1e1650"
CARD = "#161b3d"
CARD_ACTIVE = "#1d2350"
TEXT = "#f8fafc"
MUTED = "#a5aed3"
DIM = "#646c94"
PINYIN = "#fcd34d"
KEY = "#fb923c"                 # từ khoá
SPEAKERS = ("#ff5a4e", "#38bdf8")  # màu người A, người B


def _fade(color: tuple, t: float = 0.5) -> tuple:
    """Pha màu chữ về màu ô: chữ của người đang không nói."""
    return tuple(round(c + (b - c) * t) for c, b in zip(color, design.rgb(CARD)))


class Canvas:
    """Khung hình 1920×1080 hai ô hội thoại. Nền và tiêu đề vẽ một lần rồi chép cho mỗi khung."""

    W, H = 1920, 1080
    M = 80
    GAP = 40
    TOP = 150
    BOTTOM = 1080 - 110

    def __init__(self, title: str, voices: Tuple[str, str], show_en: bool, out: Path) -> None:
        W, H, m = self.W, self.H, self.M
        bg = design.gradient((W, H), BG_FROM, BG_TO)
        bg = design.glow(bg, (W * 0.08, H * 0.1), 420, SPEAKERS[0], 55)
        bg = design.glow(bg, (W * 0.94, H * 0.92), 480, "#6366f1", 75)
        self.plain = bg.copy()
        dr = ImageDraw.Draw(bg)
        f_badge = design.font("demi", 26)
        badge = "TIẾNG TRUNG  ·  HỘI THOẠI"
        bw = f_badge.getlength(badge) + 44
        cy = self.TOP / 2 + 4
        dr.rounded_rectangle((m, cy - 24, m + bw, cy + 24), radius=24, fill=SPEAKERS[0])
        dr.text((m + bw / 2, cy), badge, font=f_badge, fill="white", anchor="mm")
        f_title = design.font("bold", 40)
        name, room = title, W - 2 * m - bw - 420     # chừa chỗ cho bộ đếm bên phải
        while f_title.getlength(name) > room and len(name) > 4:
            name = name[:-2].rstrip() + "…"
        dr.text((m + bw + 28, cy), name, font=f_title, fill=TEXT, anchor="lm")
        dr.text((m, H - 52), "TIT Voice Studio · Giọng đọc AI", font=design.font("regular", 27), fill=DIM, anchor="ls")
        self.bg = bg
        self.title = title
        self.voices = voices
        self.show_en = show_en
        self.card_w = (W - 2 * m - self.GAP) / 2
        self.f_tag = design.font("demi", 30)
        self.f_counter = design.font("demi", 30)
        self.out = out
        self.count = 0
        self._layouts: Dict[int, tuple] = {}

    # bố cục chữ của một câu, thu nhỏ dần đến khi vừa ô
    def _layout(self, u: Utterance, width: float, height: float) -> List[tuple]:
        for scale in (1.0, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6, 0.55, 0.5):
            def look(role, role_hl, size, smallest, color, color_hl, lh):
                s = max(smallest, int(size * scale))   # chữ phụ không nhỏ quá mức đọc được
                return Look(design.font(role, s), design.font(role_hl, s), design.rgb(color), design.rgb(color_hl),
                            s * lh)

            blocks = []
            if self.show_en and u.en:
                lk = look("regular", "regular", 34, 26, MUTED, MUTED, 1.4)
                toks = word_tokens(u.en, [])
                blocks.append(("en", toks, _balanced(toks, lk, width), lk, 2, 26 * scale))
            lk = look("zh", "zh", 112, 52, TEXT, KEY, 1.28)
            toks = hanzi_tokens(u.zh, u.zh_marks)
            blocks.append(("zh", toks, _balanced(toks, lk, width), lk, 3, 14 * scale))
            lk = look("demi", "bold", 50, 32, PINYIN, KEY, 1.38)
            toks = pinyin_tokens(u.zh, u.zh_marks)
            blocks.append(("py", toks, _balanced(toks, lk, width), lk, 3, 64 * scale))
            if u.vi:
                lk = look("regular", "bold", 46, 32, TEXT, KEY, 1.4)
                toks = word_tokens(u.vi, u.vi_marks)
                blocks.append(("vi", toks, _balanced(toks, lk, width), lk, 4, 0))
            total = sum(len(rows) * lk.line_h + gap for _, _, rows, lk, _, gap in blocks)
            if total <= height and all(len(rows) <= limit for _, _, rows, _, limit, _ in blocks):
                return blocks
        return blocks

    def _card(self, img: Image.Image, dr: ImageDraw.ImageDraw, slot: int, u: Utterance, idx: int,
              state: str, wide: bool = False, tag: str = "") -> None:
        """state: active (đang nói) | idle (chưa ai nói) | dim (người kia đang nói).

        `wide`: lượt chỉ có một người nói thì ô chiếm cả bề ngang. `tag`: nhãn cạnh sóng âm ("Chậm 0.8x").
        """
        x0 = self.M if wide else self.M + slot * (self.card_w + self.GAP)
        x1 = self.W - self.M if wide else x0 + self.card_w
        y0, y1 = self.TOP, self.BOTTOM
        color = SPEAKERS[slot]
        active = state == "active"
        dr.rounded_rectangle((x0, y0, x1, y1), radius=40, fill=CARD_ACTIVE if active else CARD,
                             outline=color if active else design.mix(CARD, "#ffffff", 0.08), width=5 if active else 2)
        # huy hiệu người nói: vòng tròn chữ A/B và tên giọng
        r = 28
        cx, cy = x0 + 40 + r, y0 + 40 + r
        fade = 0.0 if state != "dim" else 0.55
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=design.mix(color, CARD, fade))
        dr.text((cx, cy), "AB"[slot], font=design.font("bold", 32), fill="white", anchor="mm")
        dr.text((cx + r + 16, cy), self.voices[slot], font=self.f_tag, fill=design.mix(MUTED, CARD, fade), anchor="lm")
        if active:   # sóng âm nhỏ: bên này đang nói
            bx = x1 - 52
            for k, h in enumerate((0.45, 0.9, 0.6, 1.0, 0.5)):
                x = bx - (4 - k) * 14
                half = 22 * h / 2
                dr.rounded_rectangle((x - 4, cy - half, x + 4, cy + half), radius=4, fill=color)
            if tag:
                f = design.font("demi", 26)
                tw = f.getlength(tag) + 36
                tx = bx - 4 * 14 - 24 - tw
                dr.rounded_rectangle((tx, cy - 22, tx + tw, cy + 22), radius=22, fill=design.mix(color, CARD, 0.75),
                                     outline=color, width=2)
                dr.text((tx + tw / 2, cy), tag, font=f, fill=TEXT, anchor="mm")

        pad = 56
        width = x1 - x0 - 2 * pad
        top, bottom = y0 + 40 + 2 * r + 30, y1 - 50
        if idx not in self._layouts:
            self._layouts[idx] = self._layout(u, width, bottom - top)
        blocks = self._layouts[idx]
        total = sum(len(rows) * lk.line_h + gap for _, _, rows, lk, _, gap in blocks)
        y = top + max(0.0, (bottom - top - total) / 2)
        cx = (x0 + x1) / 2
        for n, (kind, toks, rows, lk, _, gap) in enumerate(blocks):
            if state == "dim":
                lk = Look(lk.font, lk.font_hl, _fade(lk.color), _fade(lk.color_hl), lk.line_h)
            y = _draw_rows(dr, toks, rows, lk, cx, y) + gap
            if kind == "py" and n + 1 < len(blocks):   # gạch ngắn ngăn pinyin với nghĩa tiếng Việt
                bar_y = y - gap / 2 - 3
                dr.rounded_rectangle((cx - 36, bar_y, cx + 36, bar_y + 6), radius=3,
                                     fill=design.mix(color, CARD, 0.2 if state != "dim" else 0.6))

    def intro(self, chips: List[str], stage: int) -> Path:
        """Khung giới thiệu: các phần hiện dần theo `stage` (0 nhãn, 1 tên bài, 2 dòng phụ, 3 giọng và thông tin).

        Vị trí mọi phần cố định ở mọi stage để chữ không nhảy khi phần sau hiện ra.
        """
        W, H, m = self.W, self.H, self.M
        img = self.plain.copy()
        f_badge = design.font("demi", 34)
        words = self.title.split()
        for size in range(116, 70, -6):
            f_title = design.font("bold", size)
            rows = design.balanced_wrap(words, f_title, W - 2 * m - 160)
            if len(rows) <= 2:
                break
        f_sub = design.font("demi", 46)
        f_chip = design.font("demi", 32)
        title_h = len(rows) * f_title.size * 1.15
        block = 70 + 50 + title_h + 40 + f_sub.size * 1.3 + 70 + 76 + 40 + 64
        y = (H - block) / 2 - 10

        badge = "TIẾNG TRUNG  ·  HỘI THOẠI"
        bw, bh = f_badge.getlength(badge) + 64, 70
        dr = ImageDraw.Draw(img)
        dr.rounded_rectangle((W / 2 - bw / 2, y, W / 2 + bw / 2, y + bh), radius=bh / 2, fill=SPEAKERS[0])
        dr.text((W / 2, y + bh / 2), badge, font=f_badge, fill="white", anchor="mm")
        y += bh + 50
        if stage >= 1:
            yy = y
            for row in rows:
                design.shadow_text(img, (W / 2, yy), " ".join(words[j] for j in row), f_title, TEXT, anchor="ma",
                                   offset=(0, 8), blur=14)
                yy += f_title.size * 1.15
            dr = ImageDraw.Draw(img)
        y += title_h + 40
        if stage >= 2:
            dr.text((W / 2, y), "Chữ Hán  ·  Pinyin  ·  Nghĩa tiếng Việt", font=f_sub, fill=PINYIN, anchor="ma")
        y += f_sub.size * 1.3 + 70
        if stage >= 3:
            # hai người nói: vòng tròn chữ A/B và tên giọng
            pills = [(slot, self.voices[slot]) for slot in (0, 1)]
            widths = [76 + 20 + f_chip.getlength(v) + 36 for _, v in pills]
            x = W / 2 - (sum(widths) + 40) / 2
            for (slot, v), w in zip(pills, widths):
                dr.rounded_rectangle((x, y, x + w, y + 76), radius=38, fill=CARD_ACTIVE,
                                     outline=SPEAKERS[slot], width=3)
                dr.ellipse((x + 8, y + 8, x + 68, y + 68), fill=SPEAKERS[slot])
                dr.text((x + 38, y + 38), "AB"[slot], font=design.font("bold", 34), fill="white", anchor="mm")
                dr.text((x + 96, y + 38), v, font=f_chip, fill=TEXT, anchor="lm")
                x += w + 40
            y2 = y + 76 + 40
            widths = [f_chip.getlength(c) + 56 for c in chips]
            x = W / 2 - (sum(widths) + 20 * (len(chips) - 1)) / 2
            for c, w in zip(chips, widths):
                dr.rounded_rectangle((x, y2, x + w, y2 + 64), radius=32, outline=design.mix(BG_TO, "#ffffff", 0.35),
                                     width=2)
                dr.text((x + w / 2, y2 + 32), c, font=f_chip, fill=MUTED, anchor="mm")
                x += w + 20
        dr.text((m, H - 52), "TIT Voice Studio · Giọng đọc AI", font=design.font("regular", 27), fill=DIM, anchor="ls")
        return self._save(img)

    def _save(self, img: Image.Image) -> Path:
        path = self.out / f"{self.count:05d}.jpg"
        self.count += 1
        img.save(path, quality=95, subsampling=0)
        return path

    def frame(self, slots: Dict[int, int], utts: Sequence[Utterance], active: Optional[int], counter: str,
              tag: str = "") -> Path:
        img = self.bg.copy()
        dr = ImageDraw.Draw(img)
        dr.text((self.W - self.M, self.TOP / 2 + 4), counter, font=self.f_counter, fill=MUTED, anchor="rm")
        for slot, idx in slots.items():
            state = "idle" if active is None else "active" if active == slot else "dim"
            self._card(img, dr, slot, utts[idx], idx, state, wide=len(slots) == 1,
                       tag=tag if active == slot else "")
        return self._save(img)


# ── dựng bài ───────────────────────────────────────────────────────────────


def _encode_loop(entries: List[Tuple[Path, float]], wav: Path, mp4: Path, frames_dir: Path, seconds: float,
                 vf: str = "") -> None:
    concat = frames_dir / f"{mp4.stem}.txt"
    concat.write_text("".join(f"file '{p.name}'\nduration {max(d, 1 / FPS):.4f}\n" for p, d in entries)
                      + f"file '{entries[-1][0].name}'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(wav),
                    "-vf", f"fps={FPS},format=yuv420p{vf}", *shadow._video_codec(), "-g", str(FPS * 10),
                    "-c:a", "aac", "-b:a", "128k", "-t", f"{seconds:.4f}", "-movflags", "+faststart", str(mp4)],
                   check=True, capture_output=True)


def _concat(parts: List[Path], dst: Path, extra: Sequence[str] = ()) -> None:
    """Nối các file (cùng thư mục, cùng thông số; được lặp lại) không encode lại, rồi xoá file nguồn."""
    if len(parts) == 1:
        parts[0].rename(dst)
        return
    lst = dst.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    *extra, str(dst)], check=True, capture_output=True)
    lst.unlink()
    for p in set(parts):
        p.unlink()


def _quantize(audio: np.ndarray) -> np.ndarray:
    return np.concatenate([audio, np.zeros(-len(audio) % QUANTUM, dtype=np.float32)])


def build(lesson_id: str, utts: List[Utterance], zh_raw: List[np.ndarray], vi_raw: List[Optional[np.ndarray]],
          s: Settings, on_progress: Callable[[float], None], zh2_raw: Optional[List[np.ndarray]] = None,
          intro_vi: Optional[np.ndarray] = None, music_path: Optional[Path] = None) -> dict:
    """Ghép audio một lượt, vẽ khung hình, encode MP4 rồi nhân lên `loops` lượt; ghi kèm MP3, SRT, timeline.

    `zh2_raw`: bản đọc ở tốc độ lần 2 (xem `synthesize`), None = lần 2 dùng lại bản thường.
    `intro_vi`: giọng Việt đọc tên bài trong đoạn giới thiệu (khi `s.intro`).
    `music_path`: nhạc nền trộn dưới cả video, kể cả đoạn giới thiệu.
    """
    out = shadow.lesson_dir(lesson_id)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        done: Dict[int, np.ndarray] = {}     # câu trùng dùng chung một mảng: chỉ xử lý một lần

        def prep(c: np.ndarray, loud: bool) -> np.ndarray:
            if id(c) not in done:
                c2 = shadow.trim_silence(c)
                done[id(c)] = eng.normalize_loudness(c2) if loud else c2
            return done[id(c)]

        zh = [prep(c, True) for c in zh_raw]
        zh2 = [prep(c, True) for c in zh2_raw] if zh2_raw else None
        vi = [prep(c, False) if c is not None else None for c in vi_raw]
        steps = plan_steps(utts, [len(c) / SR for c in zh], [len(c) / SR if c is not None else 0 for c in vi], s,
                           [len(c) / SR for c in zh2] if zh2 else None)

        track = []
        for st in steps:
            if st.kind == "zh":
                track.append(zh[st.line])
            elif st.kind == "zh2":
                track.append(zh2[st.line])
            elif st.kind == "vi":
                track.append(vi[st.line])
            else:
                track.append(np.zeros(int(round(st.duration * SR)), dtype=np.float32))
        audio = np.concatenate(track)
        pad = -len(audio) % QUANTUM
        audio = np.concatenate([audio, np.zeros(pad, dtype=np.float32)])
        steps[-1].duration += pad / SR
        loop_s = len(audio) / SR

        # đoạn giới thiệu: chuông, rồi giọng Việt đọc tên bài (nếu có), tròn bội QUANTUM như mỗi lượt
        intro_audio = None
        if s.intro:
            parts = [chime()]
            if intro_vi is not None:
                spoken = shadow.trim_silence(intro_vi)
                parts = [chime(1.0), spoken, np.zeros(int(1.0 * SR), dtype=np.float32)]
            intro_audio = np.concatenate(parts)
            intro_audio = _quantize(np.concatenate([intro_audio, np.zeros(max(0, int(4.5 * SR) - len(intro_audio)),
                                                                          dtype=np.float32)]))
        intro_s = len(intro_audio) / SR if intro_audio is not None else 0.0
        loops = max(1, min(s.loops, int((MAX_TOTAL_S - intro_s) // loop_s)))
        on_progress(0.15)

        groups, of = exchanges(utts)
        title = s.title.strip() or "Hội thoại tiếng Trung"
        canvas = Canvas(title, (s.voice_a, s.voice_b), s.show_en, frames_dir)
        cache: Dict[tuple, Path] = {}
        entries: List[List] = []      # [ảnh, thời lượng]
        speaking: Optional[int] = None
        tag = ""                      # nhãn tốc độ khi đang đọc lần 2, giữ qua khoảng nghỉ ngay sau
        speed_tag = ""
        if zh2:
            speed_tag = f"{'Chậm' if s.speed2 < s.speed else 'Nhanh'} {s.speed2:g}x"
        for k, st in enumerate(steps):
            ex = of[st.line] if st.line >= 0 else 0
            if st.kind in ("zh", "zh2", "vi"):
                speaking = utts[st.line].speaker
                tag = speed_tag if st.kind == "zh2" else ""
            elif st.line < 0:
                speaking, tag = None, ""
            key = (ex, speaking, tag)
            if key not in cache:
                cache[key] = canvas.frame(groups[ex], utts, speaking, f"Hội thoại {ex + 1}/{len(groups)}", tag)
            if entries and entries[-1][0] == cache[key]:
                entries[-1][1] += st.duration
            else:
                entries.append([cache[key], st.duration])
            on_progress(0.15 + 0.35 * (k + 1) / len(steps))

        total = round(intro_s + loop_s * loops, 3)
        mp4_parts: List[Path] = []
        mp3_parts: List[Path] = []
        if intro_audio is not None:
            secs = int(round(total))
            length = f"{secs // 3600} giờ {secs // 60 % 60:02d} phút" if secs >= 3600 else f"{secs // 60}:{secs % 60:02d}"
            chips = [f"{len(utts)} câu", f"Đọc {s.repeats} lần mỗi câu", length]
            marks = [0.0, 0.35, 0.7, 1.05, intro_s]
            shots = [(canvas.intro(chips, k), marks[k + 1] - marks[k]) for k in range(4)]
            wav = out / "intro.wav"
            eng.write_wav(intro_audio, wav)
            _encode_loop(shots, wav, out / "intro.mp4", frames_dir, intro_s, ",fade=t=in:st=0:d=0.5")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(out / "intro.mp3")],
                           check=True)
            wav.unlink()
            mp4_parts.append(out / "intro.mp4")
            mp3_parts.append(out / "intro.mp3")

        wav = out / "loop.wav"
        eng.write_wav(audio, wav)
        loop_mp4 = out / "loop.mp4"
        # -t thay cho -shortest: với chuỗi ảnh, -shortest để hình dài hơn tiếng cả giây
        _encode_loop([(p, d) for p, d in entries], wav, loop_mp4, frames_dir, loop_s)
        on_progress(0.8)
        mp4_parts += [loop_mp4] * loops
        if music_path is None:
            loop_mp3 = out / "loop.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-b:a", "128k", str(loop_mp3)], check=True)
            mp3_parts += [loop_mp3] * loops
            _concat(mp4_parts, out / "lesson.mp4", ("-movflags", "+faststart"))
            _concat(mp3_parts, out / "lesson.mp3")
        else:
            for p in mp3_parts:
                p.unlink()
            raw = out / "voice.mp4"
            _concat(mp4_parts, raw)
            music.mix(raw, music_path, s.music_volume, total, out / "lesson.mp4", out / "lesson.mp3",
                      lambda p: on_progress(0.8 + 0.17 * p))
            raw.unlink()
        wav.unlink()
        on_progress(0.97)

        # phụ đề: mỗi câu một cue, từ lần đọc đầu đến hết lượt nghỉ cuối của câu
        spans: Dict[int, List[float]] = {}
        for st in steps:
            if st.line >= 0:
                a, b = spans.get(st.line, [st.start, st.start])
                spans[st.line] = [min(a, st.start), max(b, st.start + st.duration)]
        cues, n = [], 1
        for loop in range(loops):
            off = intro_s + loop * loop_s
            for i, u in enumerate(utts):
                a, b = spans[i]
                text = "\n".join(t for t in (u.zh, chinese.pinyin_text(u.zh), u.vi) if t)
                cues.append(f"{n}\n{shadow._srt_time(off + a)} --> {shadow._srt_time(off + b)}\n{text}\n")
                n += 1
        (out / "lesson.srt").write_text("\n".join(cues), encoding="utf-8")

        (out / "timeline.json").write_text(json.dumps({
            "kind": "dialogue", "title": title, "duration": total, "loop_duration": round(loop_s, 3),
            "intro_duration": round(intro_s, 3),
            "loops": loops, "settings": asdict(s),
            "lines": [{**asdict(u), "pinyin": chinese.pinyin_text(u.zh)} for u in utts],
            "steps": [asdict(st) for st in steps],
        }, ensure_ascii=False), encoding="utf-8")
        return {"duration": total, "title": title, "loops": loops}
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
