"""Ảnh bìa YouTube 1280×720 cho bài luyện Shadowing.

Theo kiểu ảnh bìa dễ được bấm: chữ rất to và ít (đọc được ở cỡ ảnh nhỏ trên điện thoại),
tương phản mạnh, màu nổi, và một câu tiếng Anh thật trong bài đặt trong bong bóng thoại
để người xem biết ngay sẽ học gì.
"""
import re
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFilter

from . import chinese, design

W, H = 1280, 720
THEMES = {   # tên → (gradient từ, gradient đến, màu nhấn, màu chữ dòng 2)
    "coral": ("#ff5a4e", "#6d28d9", "#facc15", "#facc15"),
    "ocean": ("#06b6d4", "#1e3a8a", "#facc15", "#fde047"),
    "sunset": ("#f59e0b", "#db2777", "#1e1b4b", "#ffffff"),
    "night": ("#111633", "#4c1d95", "#22c55e", "#facc15"),
}
DEFAULT_THEME = "coral"
INK = "#14112b"


def pick_quote(lines: List[dict]) -> str:
    """Câu ngắn, gọn để làm “mồi”: ưu tiên câu hỏi 3–7 từ, rồi câu ngắn nhất từ 3 từ."""
    cands = [ln["en"] for ln in lines if 3 <= len(ln["en"].split()) <= 7]
    questions = [c for c in cands if c.rstrip().endswith("?")]
    pool = questions or cands or [min((ln["en"] for ln in lines), key=len, default="Let's practice!")]
    return min(pool, key=lambda c: abs(len(c.split()) - 5))


def pick_quote_zh(lines: List[dict]) -> str:
    """Câu tiếng Trung làm “mồi” cho video hội thoại: ưu tiên câu hỏi 4–9 chữ."""
    def size(ln):
        return sum(chinese.has_hanzi(c) for c in ln["zh"])
    cands = [ln["zh"] for ln in lines if 4 <= size(ln) <= 9]
    questions = [c for c in cands if c.rstrip().endswith(("？", "?"))]
    pool = questions or cands or [min((ln["zh"] for ln in lines), key=len, default="你好！")]
    return min(pool, key=lambda c: abs(sum(chinese.has_hanzi(x) for x in c) - 6))


def default_quote(timeline: dict) -> str:
    lines = timeline.get("lines", [])
    return pick_quote_zh(lines) if timeline.get("kind") == "dialogue" else pick_quote(lines)


def default_headline(title: str) -> str:
    return title.strip() or "Giao tiếp hằng ngày"


def _fit(text: str, role: str, max_w: float, max_lines: int, start: int, min_size: int):
    """Cỡ chữ lớn nhất để `text` vừa `max_lines` dòng rộng `max_w`."""
    words = text.split()
    for size in range(start, min_size - 1, -4):
        f = design.font(role, size)
        rows = design.balanced_wrap(words, f, max_w)
        if len(rows) <= max_lines and all(f.getlength(" ".join(words[j] for j in r)) <= max_w for r in rows):
            return f, [" ".join(words[j] for j in r) for r in rows]
    f = design.font(role, min_size)
    return f, [" ".join(words[j] for j in r) for r in design.balanced_wrap(words, f, max_w)][:max_lines]


_STOP = set("a an the i you he she it we they me my your to of in on at for and or but is are am was were be "
            "do does did can could would will should have has had this that there here what where when how "
            "about with from i'm i'd it's don't".split())


def _accent_word(words: List[str]) -> int:
    """Từ được tô vàng trong câu trích: từ dài nhất không phải hư từ, thường là từ “đinh” của câu."""
    def score(i):
        w = re.sub(r"[^\w']", "", words[i]).lower()
        return (w not in _STOP, len(w))
    return max(range(len(words)), key=score)


def _fit_zh(text: str, max_w: float, max_lines: int, start: int, min_size: int):
    """Như `_fit` cho chữ Hán: xuống dòng giữa các từ (jieba), dấu câu không đứng đầu dòng."""
    import jieba

    words: List[str] = []
    for w in jieba.cut(text):
        if words and all(c in "。，、？！：；”）…" for c in w):
            words[-1] += w
        else:
            words.append(w)
    for size in range(start, min_size - 1, -4):
        f = design.font("zh", size)
        rows, row = [], ""
        for w in words:
            if row and f.getlength(row + w) > max_w:
                rows.append(row)
                row = w
            else:
                row += w
        rows.append(row)
        if len(rows) <= max_lines:
            return f, rows
    return f, rows[:max_lines]


def _bubble(text: str, accent: str) -> Image.Image:
    """Bong bóng thoại trắng chứa câu trích, sóng âm bên dưới, có đuôi; trả ảnh RGBA.

    Câu tiếng Trung: chữ Hán to, pinyin nhỏ bên dưới, không tô từ.
    """
    bw = 440
    zh = chinese.has_hanzi(text)
    if zh:
        f, rows = _fit_zh(text, bw - 70, 2, 76, 40)
        lh = f.size * 1.25
        f_py, py_rows = _fit(chinese.pinyin_text(text), "demi", bw - 70, 2, 30, 22)
        py_h = 10 + len(py_rows) * f_py.size * 1.3
    else:
        f, rows = _fit(text, "bold", bw - 70, 3, 52, 28)
        lh = f.size * 1.3
        py_h = 0
    wave_h = 54
    bh = int(48 + len(rows) * lh + py_h + 22 + wave_h + 40)
    img = Image.new("RGBA", (bw + 40, bh + 70), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((0, 0, bw, bh), radius=34, fill="white")
    dr.polygon([(70, bh - 2), (140, bh - 2), (64, bh + 56)], fill="white")   # đuôi bong bóng

    y = 48
    if zh:
        for row in rows:
            dr.text((bw / 2, y), row, font=f, fill=INK, anchor="ma")
            y += lh
        y += 10
        for row in py_rows:
            dr.text((bw / 2, y), row, font=f_py, fill=design.mix(INK, "#ffffff", 0.35), anchor="ma")
            y += f_py.size * 1.3
    else:
        words = text.split()
        hi = _accent_word(words)
        idx = 0
        for row in rows:
            n = len(row.split())
            x = (bw - f.getlength(row)) / 2
            for w in words[idx:idx + n]:
                wl = f.getlength(w)
                if idx == hi:
                    dr.rounded_rectangle((x - 8, y - 2, x + wl + 8, y + f.size * 1.18), radius=12, fill="#facc15")
                dr.text((x, y), w, font=f, fill=INK)
                x += wl + f.getlength(" ")
                idx += 1
            y += lh

    # sóng âm: các vạch cao thấp như đang phát
    heights = [0.35, 0.6, 0.9, 0.55, 1.0, 0.7, 0.4, 0.8, 0.5, 0.95, 0.65, 0.3, 0.75, 0.45, 0.85, 0.5, 0.3]
    y_mid = y + 22 + wave_h / 2
    step = (bw - 140) / len(heights)
    for i, hgt in enumerate(heights):
        x = 70 + i * step + step / 2
        half = wave_h * hgt / 2
        dr.rounded_rectangle((x - 5, y_mid - half, x + 5, y_mid + half), radius=5, fill=accent)
    return img


def render(lesson: dict, timeline: dict, out: Path, headline: Optional[str] = None, quote: Optional[str] = None,
           theme: str = DEFAULT_THEME) -> Path:
    """Vẽ ảnh bìa JPEG vào `out`."""
    c1, c2, accent, line2 = THEMES.get(theme, THEMES[DEFAULT_THEME])
    dialogue = timeline.get("kind") == "dialogue"
    img = design.backdrop((W, H), c1, c2)
    img = design.glow(img, (W * 0.78, H * 0.45), 330, "#ffffff", 60)
    img = design.glow(img, (W * 0.05, H * 1.0), 260, "#000000", 90)
    dr = ImageDraw.Draw(img)

    # nhãn trên cùng
    f_badge = design.font("black", 40)
    x, y = 48, 42
    badges = [("TIẾNG TRUNG", "#facc15", INK), ("CÓ PINYIN", INK, "white")] if dialogue else \
        [("SHADOWING", "#facc15", INK), (_accent_label(lesson["voice"]), INK, "white")]
    for text, fill, color in badges:
        if not text:
            continue
        w = f_badge.getlength(text) + 44
        dr.rounded_rectangle((x, y, x + w, y + 62), radius=14, fill=fill)
        dr.text((x + w / 2, y + 33), text, font=f_badge, fill=color, anchor="mm")
        x += w + 14

    # tiêu đề hai tầng: “LUYỆN NÓI” rồi chủ đề bài, chữ to có viền đậm và bóng
    left_w = 610
    f1 = design.font("black", 96)
    design.shadow_text(img, (48, 140), "LUYỆN NGHE" if dialogue else "LUYỆN NÓI", f1, "white", stroke=6, stroke_fill=INK, offset=(0, 10), blur=12,
                       shadow=(0, 0, 0, 170))
    f2, rows = _fit((headline or default_headline(lesson["title"])).upper(), "black", left_w, 2, 150, 70)
    y = 140 + f1.size * 1.02
    for row in rows:
        design.shadow_text(img, (48, y), row, f2, line2, stroke=7, stroke_fill=INK, offset=(0, 10), blur=12,
                           shadow=(0, 0, 0, 170))
        y += f2.size * 0.98
    dr = ImageDraw.Draw(img)

    # chân: số câu, độ dài, phụ đề
    secs = int(timeline.get("duration", 0))
    if secs >= 3600:
        hours = round(secs / 3600 * 2) / 2
        length = f"{hours:g} GIỜ".replace(".", ",")
    else:
        length = f"{secs // 60}:{secs % 60:02d}"
    info = f"{lesson['lines']} CÂU  ·  {length}"
    if any(ln.get("vi") for ln in timeline.get("lines", [])):
        info += "  ·  CÓ NGHĨA TIẾNG VIỆT"
    f_info = design.font("black", 34)
    iw = f_info.getlength(info) + 48
    dr.rounded_rectangle((48, H - 104, 48 + iw, H - 48), radius=28, fill=(20, 17, 43))
    dr.text((48 + 24, H - 76), info, font=f_info, fill="white", anchor="lm")

    # bong bóng thoại, nghiêng nhẹ cho sinh động, kèm bóng đổ
    bubble = _bubble(quote or default_quote(timeline), accent if accent != INK else "#ff5a4e")
    bubble = bubble.rotate(4, resample=Image.BICUBIC, expand=True)
    bx, by = W - bubble.width - 40, int(H * 0.47 - bubble.height / 2)
    shade = Image.new("RGBA", bubble.size, (0, 0, 0, 0))
    shade.putalpha(bubble.getchannel("A").point(lambda a: a * 0.45))
    img.paste((0, 0, 0), (bx + 10, by + 16), shade.getchannel("A").filter(ImageFilter.GaussianBlur(14)))
    img.paste(bubble, (bx, by), bubble)

    # nút tròn ở góc bong bóng: micro “đến lượt bạn nói”, hoặc nút phát cho video nghe
    dr = ImageDraw.Draw(img)
    r = 58
    cx, cy = bx + 40, by + bubble.height - 40
    dr.ellipse((cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7), fill="white")
    dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill="#22c55e")
    (design.icon_play if dialogue else design.icon_mic)(dr, cx, cy, r * 1.05, "white")

    img.save(out, "JPEG", quality=92)
    return out


def _accent_label(voice: str) -> str:
    if "(Mỹ)" in voice:
        return "GIỌNG MỸ"
    if "(Anh)" in voice:
        return "GIỌNG ANH"
    return ""
