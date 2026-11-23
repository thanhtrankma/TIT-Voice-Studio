"""Bài luyện Shadowing: đọc từng câu tiếng Anh, chèn lượt nói, dựng video MP4 kèm MP3 và SRT.

Mô hình chỉ cần cho bước đọc câu (`synthesize_lines`, chạy trên luồng mô hình). Giọng bản xứ
(Kokoro, app/english.py) trả kèm lúc bắt đầu từng từ; giọng VieNeu thì ước lượng. Phần còn lại
(`build`) chạy ở luồng khác. Khung hình vẽ bằng Pillow vì ffmpeg của Homebrew không có
drawtext/libass: mỗi trạng thái (đổi từ được tô sáng, một nhịp đếm ngược) là một ảnh, ghép
bằng concat demuxer nên encode gần như tức thì.
"""
import functools
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
from PIL import Image, ImageDraw

from . import design, engine as eng, english
from .config import SHADOW_DIR

SR = eng.SAMPLE_RATE
MAX_LINES = 80
MAX_LINE_CHARS = 300

INTRO_S = 3.0
OUTRO_S = 2.0
FULL_RUN_GAP_S = 0.35
MIN_GAP_S = 1.5

# ── bài học ────────────────────────────────────────────────────────────────


@dataclass
class Line:
    en: str
    vi: str = ""


@dataclass
class Settings:
    voice: str
    title: str = ""
    repeats: int = 1
    slow_speed: float = 0.8      # 1.0 = bỏ lượt nghe chậm
    gap_factor: float = 1.3      # khoảng nói = hệ số × độ dài câu
    full_run: bool = True
    aspect: str = "16:9"


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'“(]?[A-Z0-9])")
_ABBREV = ("mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "vs.", "prof.", "e.g.", "i.e.")


def _split_sentences(text: str) -> List[str]:
    out: List[str] = []
    for part in _SENT_SPLIT.split(text):
        if out and out[-1].lower().endswith(_ABBREV):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return [s.strip() for s in out if s.strip()]


def parse_lesson(text: str) -> List[Line]:
    """Mỗi dòng là một câu luyện, dạng `English | Tiếng Việt`.

    Dòng không có bản dịch mà chứa nhiều câu thì được tách thành từng câu.
    """
    lines: List[Line] = []
    for raw in text.splitlines():
        en, _, vi = raw.strip().partition("|")
        en, vi = en.strip(), vi.strip()
        if not en:
            continue
        if vi:
            lines.append(Line(en, vi))
        else:
            lines.extend(Line(s) for s in _split_sentences(en))
    return lines


_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
         "fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?(?!\w)", re.IGNORECASE)


def _number_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    return _TENS[n // 10] + ("" if n % 10 == 0 else f"-{_ONES[n % 10]}")


def _time_words(m: re.Match) -> str:
    out = _number_words(int(m[1]))
    if m[2] and m[2] != "00":
        out += f" oh {_ONES[int(m[2])]}" if m[2][0] == "0" else f" {_number_words(int(m[2]))}"
    return f"{out} {m[3].upper()} M"


def normalize_en(text: str) -> str:
    """Viết giờ thành chữ trước khi đọc: "9 a.m." ở cuối câu dễ bị mô hình nuốt âm."""
    out = _TIME.sub(_time_words, text).replace("&", " and ")
    if text.rstrip().endswith(".") and not out.rstrip().endswith((".", "!", "?")):
        out = out.rstrip() + "."
    return re.sub(r"\s{2,}", " ", out).strip()


# ── âm thanh ───────────────────────────────────────────────────────────────


Timings = Optional[List[float]]   # lúc bắt đầu từng từ của câu (giây); None = chưa biết, sẽ ước lượng


def synthesize_lines(tts, lines: List[Line], voice: str, on_progress: Callable[[float], None],
                     on_download: Optional[english.ProgressFn] = None) -> tuple:
    """Đọc từng câu riêng (chạy trên luồng mô hình) để biết chính xác biên mỗi câu.

    Trả (clips, timings). Kokoro đọc nguyên văn để mốc khớp với từ hiển thị; VieNeu cần viết
    giờ thành chữ trước và không có mốc.
    """
    clips: List[np.ndarray] = []
    timings: List[Timings] = []
    for i, line in enumerate(lines):
        if english.is_native(voice):
            audio, starts = english.synthesize(line.en, voice, on_download)
        else:
            audio, starts = np.asarray(tts.infer(normalize_en(line.en), voice=voice), dtype=np.float32), None
        clips.append(audio)
        timings.append(starts)
        on_progress((i + 1) / len(lines))
    return clips, timings


def _loud_bounds(audio: np.ndarray, pad_s: float = 0.06) -> tuple:
    env = np.abs(audio)
    loud = np.flatnonzero(env > max(env.max() * 0.02, 1e-3)) if len(audio) else []
    if not len(loud):
        return 0, len(audio)
    pad = int(pad_s * SR)
    return max(0, loud[0] - pad), loud[-1] + pad


def trim_silence(audio: np.ndarray, pad_s: float = 0.06) -> np.ndarray:
    a, b = _loud_bounds(audio, pad_s)
    return audio[a:b]


def _syllables(word: str) -> float:
    digits = len(re.findall(r"\d", word))
    if digits:
        return digits * 1.5
    w = re.sub(r"[^a-z]", "", word.lower())
    n = len(re.findall(r"[aeiouy]+", w))
    if n > 1 and w.endswith("e") and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n)


def word_times(words: List[str], duration: float) -> List[float]:
    """Ước lượng lúc bắt đầu mỗi từ: chia thời lượng câu theo số âm tiết, cộng nhịp ngắt ở dấu câu."""
    weights = []
    for i, w in enumerate(words):
        extra = 0.0 if i == len(words) - 1 else 0.8 if w.endswith((",", ";", ":", "—")) else \
            1.2 if w.endswith((".", "!", "?")) else 0.0
        weights.append(_syllables(w) + extra)
    total = sum(weights) or 1
    starts, acc = [], 0.0
    for w in weights:
        starts.append(round(acc / total * duration, 3))
        acc += w
    return starts


# ── dòng thời gian ─────────────────────────────────────────────────────────


@dataclass
class Step:
    kind: str           # intro | listen | slow | gap | full | pause | outro
    line: int           # -1 với intro/outro
    start: float = 0.0
    duration: float = 0.0
    speed: float = 1.0
    words: List[float] = field(default_factory=list)   # lúc bắt đầu từng từ, tính từ đầu bước


def step_words(line: Line, starts: Timings, base: float, duration: float) -> List[float]:
    """Lúc bắt đầu từng từ trong một bước dài `duration` của câu gốc dài `base` giây.

    Có mốc thật thì co giãn theo tốc độ của bước; từ đầu luôn sáng từ giây 0 để khung đầu
    phủ cả đoạn lấy hơi.
    """
    words = line.en.split()
    if not starts or len(starts) != len(words):
        return word_times(words, duration)
    k = duration / base
    out = [min(max(0.0, round(t * k, 3)), duration) for t in starts]
    out[0] = 0.0
    return out


def plan_steps(lines: List[Line], durations: List[float], s: Settings,
               timings: Optional[List[Timings]] = None) -> List[Step]:
    steps = [Step("intro", -1, duration=INTRO_S)]
    for i, d in enumerate(durations):
        gap = max(MIN_GAP_S, d * s.gap_factor)
        for _ in range(s.repeats):
            steps += [Step("listen", i, duration=d), Step("gap", i, duration=gap)]
            if s.slow_speed < 0.99:
                steps += [Step("slow", i, duration=d / s.slow_speed, speed=s.slow_speed),
                          Step("gap", i, duration=gap / s.slow_speed)]
    if s.full_run:
        for i, d in enumerate(durations):
            steps.append(Step("full", i, duration=d))
            if i < len(durations) - 1:
                steps.append(Step("pause", i, duration=FULL_RUN_GAP_S))
    steps.append(Step("outro", -1, duration=OUTRO_S))
    t = 0.0
    for st in steps:
        if st.kind in ("listen", "slow", "full"):
            starts = timings[st.line] if timings else None
            st.words = step_words(lines[st.line], starts, durations[st.line], st.duration)
        st.start = round(t, 3)
        t += st.duration
    return steps


# ── khung hình ─────────────────────────────────────────────────────────────

BG_FROM, BG_TO = "#0b1026", "#1e1650"
CARD = "#161b3d"
TEXT = "#f8fafc"
MUTED = "#a5aed3"
DIM = "#646c94"
HILITE = "#facc15"
HILITE_TEXT = "#1c1917"
BRAND = "#ff5a4e"
PHASES = {   # nhãn, màu
    "listen": ("Nghe", "#ff5a4e"),
    "slow": ("Nghe chậm", "#a855f7"),
    "gap": ("Đến lượt bạn — nói theo", "#22c55e"),
    "full": ("Shadowing — nói cùng lúc", "#38bdf8"),
}


class Canvas:
    """Vẽ khung hình video. Nền (gradient, đốm sáng) vẽ một lần rồi chép cho mỗi khung."""

    def __init__(self, aspect: str, out: Path) -> None:
        self.W, self.H = (1920, 1080) if aspect == "16:9" else (1080, 1920)
        self.portrait = aspect != "16:9"
        k = self.k = 0.94 if self.portrait else 1.0
        self.m = int(110 * k)
        self.f_en = design.font("bold", int(72 * k))
        self.f_vi = design.font("regular", int(40 * k))
        self.f_tag = design.font("demi", int(32 * k))
        self.f_small = design.font("regular", int(27 * k))
        self.f_title = design.font("bold", int(104 * k))
        self.f_step = design.font("demi", int(30 * k))
        bg = design.gradient((self.W, self.H), BG_FROM, BG_TO)
        bg = design.glow(bg, (self.W * 0.1, self.H * 0.08), max(self.W, self.H) * 0.22, BRAND, 60)
        self.bg = design.glow(bg, (self.W * 0.92, self.H * 0.95), max(self.W, self.H) * 0.26, "#6366f1", 80)
        self.out = out
        self.count = 0

    def _new(self, progress: float) -> tuple:
        img = self.bg.copy()
        dr = ImageDraw.Draw(img)
        m, k = self.m, self.k
        bh = max(8, int(10 * k))
        y = self.H - int(m * 0.45)
        dr.rounded_rectangle((m, y, self.W - m, y + bh), radius=bh // 2, fill=design.mix(BG_TO, "#ffffff", 0.14))
        if progress > 0.005:
            dr.rounded_rectangle((m, y, m + max(bh, (self.W - 2 * m) * min(progress, 1)), y + bh), radius=bh // 2,
                                 fill=BRAND)
        dr.text((m, y - int(18 * k)), "TIT Voice Studio · Giọng đọc AI", font=self.f_small, fill=DIM, anchor="ls")
        return img, dr

    def _save(self, img: Image.Image) -> Path:
        # JPEG 4:4:4 chất lượng cao: nhanh gấp ~4 lần PNG trên nền gradient, x264 còn nén lại sau
        path = self.out / f"{self.count:05d}.jpg"
        self.count += 1
        img.save(path, quality=95, subsampling=0)
        return path

    def _centered(self, dr, text: str, font, y: float, fill, width: float, step: float = 1.3) -> float:
        words = text.split()
        for row in design.balanced_wrap(words, font, width):
            dr.text((self.W / 2, y), " ".join(words[j] for j in row), font=font, fill=fill, anchor="ma")
            y += font.size * step
        return y

    def _pill(self, dr, x: float, cy: float, kind: str, text: str, color: str) -> float:
        """Nhãn bo tròn có icon trong vòng tròn trắng; trả mép phải."""
        h = self.f_tag.size * 2.0
        d = h - 12 * self.k
        w = d + 22 * self.k + self.f_tag.getlength(text) + h * 0.45
        dr.rounded_rectangle((x, cy - h / 2, x + w, cy + h / 2), radius=h / 2, fill=color)
        ix = x + 6 * self.k + d / 2
        dr.ellipse((ix - d / 2, cy - d / 2, ix + d / 2, cy + d / 2), fill="white")
        design.ICONS[kind](dr, ix, cy, d * 0.55, color)
        dr.text((x + d + 22 * self.k, cy), text, font=self.f_tag, fill="white", anchor="lm")
        return x + w

    def _counter(self, dr, cy: float, text: str, index: int, total: int, color: str) -> None:
        """Câu thứ mấy: chữ, kèm hàng chấm khi bài không quá dài."""
        m, k = self.m, self.k
        if total > 16 or total < 2:
            dr.text((self.W - m, cy), text, font=self.f_tag, fill=MUTED, anchor="rm")
            return
        r, gap = 7 * k, 26 * k
        x = self.W - m - r
        for i in reversed(range(total)):
            fill = color if i == index else TEXT if i < index else design.mix(BG_TO, "#ffffff", 0.22)
            rr = r * 1.35 if i == index else r
            dr.ellipse((x - rr, cy - rr, x + rr, cy + rr), fill=fill)
            x -= gap
        dr.text((x - 6 * k, cy), text, font=self.f_tag, fill=MUTED, anchor="rm")

    def intro_card(self, title: str, chips: List[str], steps: List[tuple], progress: float) -> Path:
        img, dr = self._new(progress)
        W, H, k, m = self.W, self.H, self.k, self.m
        badge = "LUYỆN SHADOWING TIẾNG ANH"
        bw, bh = self.f_tag.getlength(badge) + 56 * k, self.f_tag.size * 1.9
        by = H * (0.2 if not self.portrait else 0.24)
        dr.rounded_rectangle((W / 2 - bw / 2, by, W / 2 + bw / 2, by + bh), radius=bh / 2, fill=BRAND)
        dr.text((W / 2, by + bh / 2), badge, font=self.f_tag, fill="white", anchor="mm")

        y = by + bh + 50 * k
        words = title.split()
        for row in design.balanced_wrap(words, self.f_title, W - 2 * m):
            design.shadow_text(img, (W / 2, y), " ".join(words[j] for j in row), self.f_title, TEXT, anchor="ma",
                               offset=(0, int(8 * k)), blur=int(14 * k))
            y += self.f_title.size * 1.15
        dr = ImageDraw.Draw(img)

        y += 40 * k
        widths = [self.f_step.getlength(c) + 48 * k for c in chips]
        x = W / 2 - (sum(widths) + 16 * k * (len(chips) - 1)) / 2
        ch = self.f_step.size * 1.8
        for c, w in zip(chips, widths):
            dr.rounded_rectangle((x, y, x + w, y + ch), radius=ch / 2, outline=design.mix(BG_TO, "#ffffff", 0.35),
                                 width=max(2, int(2 * k)))
            dr.text((x + w / 2, y + ch / 2), c, font=self.f_step, fill=MUTED, anchor="mm")
            x += w + 16 * k

        # các bước luyện: vòng tròn có icon, nối bằng mũi tên
        r = 46 * k
        cy = max(y + ch + 110 * k, H * (0.7 if not self.portrait else 0.64))
        span = min(W - 2 * m, (2 * r + 190 * k) * len(steps))
        xs = [W / 2 - span / 2 + span * (i + 0.5) / len(steps) for i in range(len(steps))]
        for i, ((kind, label), cx) in enumerate(zip(steps, xs)):
            color = PHASES[kind][1]
            if i:
                x0, x1 = xs[i - 1] + r + 18 * k, cx - r - 18 * k
                dr.line((x0, cy, x1 - 10 * k, cy), fill=design.mix(BG_TO, "#ffffff", 0.35), width=max(2, int(3 * k)))
                dr.polygon([(x1, cy), (x1 - 14 * k, cy - 9 * k), (x1 - 14 * k, cy + 9 * k)],
                           fill=design.mix(BG_TO, "#ffffff", 0.35))
            dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
            design.ICONS[kind](dr, cx, cy, r * 1.05, "white")
            dr.text((cx, cy + r + 22 * k), label, font=self.f_step, fill=TEXT, anchor="ma")
        return self._save(img)

    def outro_card(self, title: str, progress: float) -> Path:
        img, dr = self._new(progress)
        W, H, k = self.W, self.H, self.k
        r = 80 * k
        cy = H * 0.34
        dr.ellipse((W / 2 - r, cy - r, W / 2 + r, cy + r), fill=PHASES["gap"][1])
        design.icon_check(dr, W / 2, cy, r * 1.1, "white")
        y = cy + r + 50 * k
        design.shadow_text(img, (W / 2, y), "Hoàn thành!", self.f_title, TEXT, anchor="ma", offset=(0, int(8 * k)),
                           blur=int(14 * k))
        dr = ImageDraw.Draw(img)
        y = self._centered(dr, title, self.f_vi, y + self.f_title.size * 1.35, MUTED, W - 2 * self.m)
        self._centered(dr, "Luyện lại mỗi ngày để nói trôi chảy hơn.", self.f_small, y + 20 * k, DIM, W - 2 * self.m)
        return self._save(img)

    def line_frame(self, kind: str, label_extra: str, line: Line, hi: Optional[int], progress: float,
                   index: int, total: int, countdown: Optional[float] = None) -> Path:
        img, dr = self._new(progress)
        W, H, k, m = self.W, self.H, self.k, self.m
        label, color = PHASES[kind]
        top = m * 0.8
        self._pill(dr, m, top, kind, f"{label} {label_extra}".strip(), color)
        counter = f"Liền mạch {index + 1}/{total}" if kind == "full" else f"Câu {index + 1}/{total}"
        self._counter(dr, top, counter, index, total, color)

        # thẻ câu
        pad = 64 * k
        inner = W - 2 * m - 2 * pad
        words = line.en.split()
        rows = design.balanced_wrap(words, self.f_en, inner)
        lh = self.f_en.size * 1.42
        vi_words = line.vi.split()
        vi_rows = design.balanced_wrap(vi_words, self.f_vi, inner) if line.vi else []
        vi_block = (68 * k + len(vi_rows) * self.f_vi.size * 1.45) if vi_rows else 0
        ch = len(rows) * lh + vi_block + 2 * pad - (lh - self.f_en.size * 1.15)
        cy = H * (0.45 if not self.portrait else 0.42)
        y0 = cy - ch / 2
        dr.rounded_rectangle((m, y0, W - m, y0 + ch), radius=40 * k, fill=CARD,
                             outline=design.mix(CARD, color, 0.6), width=max(2, int(3 * k)))

        y = y0 + pad
        space = self.f_en.getlength(" ")
        for row in rows:
            x = (W - self.f_en.getlength(" ".join(words[j] for j in row))) / 2
            for j in row:
                wl = self.f_en.getlength(words[j])
                if j == hi:
                    dr.rounded_rectangle((x - 8 * k, y - 2 * k, x + wl + 8 * k, y + self.f_en.size * 1.2),
                                         radius=14 * k, fill=HILITE)
                    fill = HILITE_TEXT
                else:
                    fill = TEXT if hi is None or j < hi else DIM
                dr.text((x, y), words[j], font=self.f_en, fill=fill)
                x += wl + space
            y += lh
        if vi_rows:
            y += self.f_en.size * 1.15 - lh + 30 * k
            dr.rounded_rectangle((W / 2 - 40 * k, y, W / 2 + 40 * k, y + 6 * k), radius=3 * k, fill=color)
            y += 38 * k
            for row in vi_rows:
                dr.text((W / 2, y), " ".join(vi_words[j] for j in row), font=self.f_vi, fill=MUTED, anchor="ma")
                y += self.f_vi.size * 1.45

        if countdown is not None:   # vòng đếm ngược có micro
            r = 62 * k
            ry = min(y0 + ch + 70 * k + r, H - m - r - 40 * k)
            box = (W / 2 - r, ry - r, W / 2 + r, ry + r)
            w = max(6, int(12 * k))
            dr.ellipse(box, outline=design.mix(BG_TO, "#ffffff", 0.16), width=w)
            if countdown > 0.01:
                dr.arc(box, -90, -90 + 360 * countdown, fill=color, width=w)
            design.icon_mic(dr, W / 2, ry, r * 0.95, TEXT)
            dr.text((W / 2, ry + r + 22 * k), "Nói to theo!", font=self.f_step, fill=TEXT, anchor="ma")
        return self._save(img)


# ── dựng bài ───────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _video_codec() -> List[str]:
    encoders = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx264" in encoders:
        return ["-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "22"]
    if "h264_videotoolbox" in encoders:
        return ["-c:v", "h264_videotoolbox", "-b:v", "4M"]
    return ["-c:v", "mpeg4", "-q:v", "4"]


def lesson_dir(lesson_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", lesson_id):   # id do Engine.submit sinh; chặn "../"
        raise ValueError(lesson_id)
    return SHADOW_DIR / lesson_id


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build(lesson_id: str, lines: List[Line], raw_clips: List[np.ndarray], s: Settings,
          on_progress: Callable[[float], None], timings: Optional[List[Timings]] = None) -> dict:
    """Ghép audio, vẽ khung hình, encode MP4; ghi kèm MP3, SRT và timeline.json.

    `timings` (nếu có) tính từ đầu clip thô; cắt khoảng lặng đầu thì dời mốc theo.
    """
    out = lesson_dir(lesson_id)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        bounds = [_loud_bounds(c) for c in raw_clips]
        clips = [eng.normalize_loudness(c[a:b]) for c, (a, b) in zip(raw_clips, bounds)]
        if timings:
            timings = [None if t is None else [x - a / SR for x in t] for t, (a, _) in zip(timings, bounds)]
        slow = {i: eng.change_speed(c, s.slow_speed) for i, c in enumerate(clips)} if s.slow_speed < 0.99 else {}
        durations = [len(c) / SR for c in clips]
        steps = plan_steps(lines, durations, s, timings)
        # Độ dài thật của bản chậm lệch vài ms so với d / speed: lấy theo audio để khớp tuyệt đối.
        t = 0.0
        for st in steps:
            if st.kind == "slow":
                st.duration = len(slow[st.line]) / SR
                st.words = step_words(lines[st.line], timings[st.line] if timings else None,
                                      durations[st.line], st.duration)
            st.start = round(t, 3)
            t += st.duration
        total = t

        track = []
        for st in steps:
            if st.kind in ("listen", "full"):
                track.append(clips[st.line])
            elif st.kind == "slow":
                track.append(slow[st.line])
            else:
                track.append(np.zeros(int(round(st.duration * SR)), dtype=np.float32))
        audio = np.concatenate(track)
        on_progress(0.1)

        canvas = Canvas(s.aspect, frames_dir)
        title = s.title.strip() or "Luyện Shadowing"
        n = len(lines)
        steps_shown = [("listen", "Nghe"), ("gap", "Nói theo")]
        if s.slow_speed < 0.99:
            steps_shown.append(("slow", "Nghe chậm"))
        if s.full_run:
            steps_shown.append(("full", "Nói cùng lúc"))
        entries = []   # (ảnh, thời lượng)
        for k, st in enumerate(steps):
            p = st.start / total
            if st.kind == "intro":
                chips = [f"{n} câu", f"Giọng {s.voice}", f"{int(total // 60)}:{int(total % 60):02d}"]
                entries.append((canvas.intro_card(title, chips, steps_shown, p), st.duration))
            elif st.kind == "outro":
                entries.append((canvas.outro_card(title, p), st.duration))
            elif st.kind == "pause":
                entries.append((canvas.line_frame("full", "", lines[st.line], None, p, st.line, n), st.duration))
            elif st.kind == "gap":
                ticks = max(1, min(int(st.duration / 0.25), 24))
                for j in range(ticks):
                    d = st.duration / ticks
                    entries.append((canvas.line_frame("gap", "", lines[st.line], None, (st.start + j * d) / total,
                                                      st.line, n, 1 - j / ticks), d))
            else:
                extra = f"{st.speed:g}x" if st.kind == "slow" else ""
                marks = st.words + [st.duration]
                for j in range(len(st.words)):
                    entries.append((canvas.line_frame(st.kind, extra, lines[st.line], j,
                                                      (st.start + marks[j]) / total, st.line, n),
                                    marks[j + 1] - marks[j]))
            on_progress(0.1 + 0.7 * (k + 1) / len(steps))

        concat = frames_dir / "list.txt"
        concat.write_text("".join(f"file '{p.name}'\nduration {max(d, 0.034):.3f}\n" for p, d in entries)
                          + f"file '{entries[-1][0].name}'\n")
        wav = out / "lesson.wav"
        eng.write_wav(audio, wav)
        mp4 = out / "lesson.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(wav),
                        "-vf", "fps=30,format=yuv420p", *_video_codec(), "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", str(mp4)], check=True, capture_output=True)
        eng.to_mp3(wav)
        wav.unlink()
        on_progress(0.95)

        cues, idx = [], 1
        for st in steps:
            if st.kind in ("listen", "slow", "full"):
                line = lines[st.line]
                text = line.en + (f"\n{line.vi}" if line.vi else "")
                cues.append(f"{idx}\n{_srt_time(st.start)} --> {_srt_time(st.start + st.duration)}\n{text}\n")
                idx += 1
        (out / "lesson.srt").write_text("\n".join(cues), encoding="utf-8")
        (out / "timeline.json").write_text(json.dumps({
            "title": title, "duration": round(total, 3), "settings": asdict(s),
            "lines": [asdict(line) for line in lines], "steps": [asdict(st) for st in steps],
            "word_timing": "measured" if timings and all(t is not None for t in timings) else "estimated",
        }, ensure_ascii=False), encoding="utf-8")
        return {"duration": round(total, 3), "title": title}
    except Exception:
        shutil.rmtree(out, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
