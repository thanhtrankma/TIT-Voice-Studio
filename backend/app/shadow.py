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
from PIL import Image, ImageDraw, ImageFont

from . import engine as eng, english
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

_FONTS = {
    False: ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"],
    True: ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
           "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
           "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"],
}


@functools.lru_cache(maxsize=None)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in _FONTS[bold]:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise RuntimeError("Không tìm thấy font có dấu tiếng Việt (Arial hoặc DejaVu Sans) để vẽ video.")


BG = "#0f172a"
TEXT = "#f8fafc"
MUTED = "#94a3b8"
DIM = "#64748b"
HILITE = "#facc15"
BRAND = "#ff5a4e"
LABELS = {
    "listen": ("Nghe", "#ff5a4e"),
    "slow": ("Nghe chậm", "#9333ea"),
    "gap": ("Đến lượt bạn — nói theo", "#16a34a"),
    "full": ("Shadowing — nói cùng lúc", "#0284c7"),
}


class Canvas:
    def __init__(self, aspect: str, out: Path) -> None:
        self.W, self.H = (1920, 1080) if aspect == "16:9" else (1080, 1920)
        k = self.W / 1920 if aspect == "16:9" else self.W / 1080 * 0.94
        self.margin = int(110 * k)
        self.f_en, self.f_vi = _font(int(66 * k), True), _font(int(40 * k))
        self.f_tag, self.f_small = _font(int(34 * k), True), _font(int(28 * k))
        self.f_title = _font(int(84 * k), True)
        self.out = out
        self.count = 0

    def _new(self, progress: float) -> tuple:
        img = Image.new("RGB", (self.W, self.H), BG)
        dr = ImageDraw.Draw(img)
        bar = max(6, self.H // 160)
        dr.rectangle((0, self.H - bar, int(self.W * min(progress, 1)), self.H), fill=BRAND)
        dr.text((self.W - self.margin // 2, self.H - bar - self.margin // 3), "Giọng đọc AI · TIT Voice Studio",
                font=self.f_small, fill=DIM, anchor="rs")
        return img, dr

    def _save(self, img: Image.Image) -> Path:
        path = self.out / f"{self.count:05d}.png"
        self.count += 1
        img.save(path, compress_level=1)
        return path

    def _wrap(self, words: List[str], font, width: int) -> List[List[int]]:
        rows: List[List[int]] = [[]]
        for i, w in enumerate(words):
            row = rows[-1]
            if row and font.getlength(" ".join(words[j] for j in row + [i])) > width:
                rows.append([i])
            else:
                row.append(i)
        return rows

    def _centered(self, dr, text: str, font, y: float, fill: str, width: int) -> float:
        words = text.split()
        step = font.size * 1.3
        for row in self._wrap(words, font, width):
            dr.text((self.W / 2, y), " ".join(words[j] for j in row), font=font, fill=fill, anchor="ma")
            y += step
        return y

    def title_card(self, title: str, subtitle: str, hint: str, progress: float) -> Path:
        img, dr = self._new(progress)
        width = self.W - 2 * self.margin
        y = self._centered(dr, title, self.f_title, self.H * 0.36, TEXT, width)
        y = self._centered(dr, subtitle, self.f_vi, y + self.f_vi.size, BRAND, width)
        self._centered(dr, hint, self.f_small, y + self.f_vi.size, MUTED, width)
        return self._save(img)

    def line_frame(self, kind: str, label_extra: str, counter: str, line: Line, hi: Optional[int],
                   progress: float, countdown: Optional[float] = None) -> Path:
        img, dr = self._new(progress)
        m = self.margin
        label, color = LABELS[kind]
        label = f"{label} {label_extra}".strip()
        pad = self.f_tag.size * 0.7
        top = m * 0.6
        dr.rounded_rectangle((m, top, m + self.f_tag.getlength(label) + 2 * pad, top + self.f_tag.size * 1.9),
                             radius=self.f_tag.size, fill=color)
        dr.text((m + pad, top + self.f_tag.size * 0.95), label, font=self.f_tag, fill="white", anchor="lm")
        dr.text((self.W - m, top + self.f_tag.size * 0.95), counter, font=self.f_small, fill=MUTED, anchor="rm")

        words = line.en.split()
        width = self.W - 2 * m
        rows = self._wrap(words, self.f_en, width)
        step = self.f_en.size * 1.35
        vi_rows = len(self._wrap(line.vi.split(), self.f_vi, width)) if line.vi else 0
        block = len(rows) * step + (vi_rows * self.f_vi.size * 1.3 + self.f_vi.size if vi_rows else 0)
        y = self.H * 0.46 - block / 2
        space = self.f_en.getlength(" ")
        for row in rows:
            x = (self.W - self.f_en.getlength(" ".join(words[j] for j in row))) / 2
            for j in row:
                fill = HILITE if j == hi else TEXT if hi is None or j < hi else DIM
                dr.text((x, y), words[j], font=self.f_en, fill=fill)
                x += self.f_en.getlength(words[j]) + space
            y += step
        if line.vi:
            self._centered(dr, line.vi, self.f_vi, y + self.f_vi.size * 0.6, MUTED, width)
        if countdown is not None:
            bw, bh, by = self.W * 0.42, max(12, self.H // 70), self.H * 0.76
            x0 = (self.W - bw) / 2
            dr.rounded_rectangle((x0, by, x0 + bw, by + bh), radius=bh // 2, fill="#1e293b")
            if countdown > 0.01:
                dr.rounded_rectangle((x0, by, x0 + bw * countdown, by + bh), radius=bh // 2, fill="#22c55e")
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
        entries = []   # (ảnh, thời lượng)
        for k, st in enumerate(steps):
            p = st.start / total
            counter = f"Câu {st.line + 1}/{n}" if st.kind != "full" and st.line >= 0 else "Lượt liền mạch"
            if st.kind == "intro":
                hint = "Nghe từng câu, rồi nói to theo khi thấy “Đến lượt bạn”."
                if s.full_run:
                    hint += " Cuối bài: nói cùng lúc với giọng đọc."
                entries.append((canvas.title_card(title, f"{n} câu · Giọng {s.voice}", hint, p), st.duration))
            elif st.kind == "outro":
                entries.append((canvas.title_card("Hoàn thành!", title, "Luyện lại mỗi ngày để nói trôi chảy hơn.", p),
                                st.duration))
            elif st.kind == "pause":
                entries.append((canvas.line_frame("full", "", counter, lines[st.line], None, p), st.duration))
            elif st.kind == "gap":
                ticks = max(1, min(int(st.duration / 0.25), 24))
                for j in range(ticks):
                    d = st.duration / ticks
                    entries.append((canvas.line_frame("gap", "", counter, lines[st.line], None,
                                                      (st.start + j * d) / total, 1 - j / ticks), d))
            else:
                extra = f"{st.speed:g}x" if st.kind == "slow" else ""
                marks = st.words + [st.duration]
                for j in range(len(st.words)):
                    entries.append((canvas.line_frame(st.kind, extra, counter, lines[st.line], j,
                                                      (st.start + marks[j]) / total), marks[j + 1] - marks[j]))
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
