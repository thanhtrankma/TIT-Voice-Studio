"""Bộ thiết kế dùng chung cho khung hình video Shadowing và ảnh bìa YouTube.

Font: ưu tiên Avenir Next (chữ trong video) và Helvetica Neue Condensed Black (tiêu đề ảnh
bìa) có sẵn trên macOS và đủ dấu tiếng Việt; máy khác dùng Arial hoặc DejaVu Sans.
Arial Black, Impact, Futura thiếu dấu tiếng Việt nên không dùng.
"""
import functools
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

_ARIAL = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf", "C:/Windows/Fonts/arial.ttf",
          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf"]
_ARIAL_BOLD = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
               "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
               "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"]
_AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
_HELVETICA = "/System/Library/Fonts/HelveticaNeue.ttc"

# vai trò → các lựa chọn (đường dẫn, kiểu trong file .ttc hoặc None), lấy cái đầu tiên có trên máy
FONTS = {
    "regular": [(_AVENIR, "Medium")] + [(p, None) for p in _ARIAL],
    "demi": [(_AVENIR, "Demi Bold")] + [(p, None) for p in _ARIAL_BOLD],
    "bold": [(_AVENIR, "Bold")] + [(p, None) for p in _ARIAL_BOLD],
    "black": [(_HELVETICA, "Condensed Black"), (_AVENIR, "Bold")] + [(p, None) for p in _ARIAL_BOLD],
    # chữ Hán giản thể (Avenir không có); pinyin vẫn dùng Avenir vì có đủ ǎ ǐ ǒ ǔ ǚ
    "zh": [("/System/Library/Fonts/Hiragino Sans GB.ttc", "W6"), ("/System/Library/Fonts/STHeiti Medium.ttc", None),
           ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", None),
           ("/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", None), ("C:/Windows/Fonts/msyhbd.ttc", None)],
}


@functools.lru_cache(maxsize=None)
def _face_index(path: str, style: str) -> Optional[int]:
    for i in range(32):
        try:
            if ImageFont.truetype(path, 12, index=i).getname()[1] == style:
                return i
        except OSError:
            return None
    return None


@functools.lru_cache(maxsize=None)
def font(role: str, size: int) -> ImageFont.FreeTypeFont:
    for path, style in FONTS[role]:
        if not Path(path).exists():
            continue
        if style is None:
            return ImageFont.truetype(path, size)
        idx = _face_index(path, style)
        if idx is not None:
            return ImageFont.truetype(path, size, index=idx)
    raise RuntimeError("Không tìm thấy font có dấu tiếng Việt (Avenir Next, Arial hoặc DejaVu Sans) để vẽ.")


def rgb(hex_color: str) -> Tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a: str, b: str, t: float) -> Tuple[int, int, int]:
    ca, cb = rgb(a), rgb(b)
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))


def gradient(size: Tuple[int, int], top_left: str, bottom_right: str) -> Image.Image:
    """Gradient chéo từ góc trên trái xuống góc dưới phải."""
    w, h = size
    t = (np.linspace(0, 1, w)[None, :] * w + np.linspace(0, 1, h)[:, None] * h) / (w + h)
    a, b = np.array(rgb(top_left), float), np.array(rgb(bottom_right), float)
    return Image.fromarray((a + (b - a) * t[..., None]).round().astype(np.uint8), "RGB")


def backdrop(size: Tuple[int, int], top_left: str, bottom_right: str, spacing: int = 46) -> Image.Image:
    """Gradient chéo phủ sọc chéo rất mờ cho nền có kết cấu (ảnh bìa, ảnh kênh)."""
    w, h = size
    base = gradient(size, top_left, bottom_right)
    stripes = base.copy()
    sd = ImageDraw.Draw(stripes)
    for i in range(-h, w, spacing):
        sd.line((i, h, i + h, 0), fill=mix(bottom_right, top_left, 0.5), width=max(2, spacing // 23))
    return Image.blend(base, stripes, 0.35)


def glow(img: Image.Image, center: Tuple[float, float], radius: float, color: str, alpha: int) -> Image.Image:
    """Đốm sáng mờ để nền có chiều sâu."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    x, y = center
    ImageDraw.Draw(layer).ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*rgb(color), alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.6))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def shadow_text(img: Image.Image, xy, text: str, fnt, fill, anchor="la", offset=(0, 6), blur=10,
                shadow=(0, 0, 0, 150), stroke=0, stroke_fill=None) -> None:
    """Chữ có bóng đổ mờ (vẽ thẳng lên `img`, RGB)."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((xy[0] + offset[0], xy[1] + offset[1]), text, font=fnt, fill=shadow, anchor=anchor,
                               stroke_width=stroke, stroke_fill=shadow)
    blurred = layer.filter(ImageFilter.GaussianBlur(blur))
    img.paste(blurred, (0, 0), blurred)
    ImageDraw.Draw(img).text(xy, text, font=fnt, fill=fill, anchor=anchor, stroke_width=stroke,
                             stroke_fill=stroke_fill)


def wrap(words: List[str], fnt, width: float) -> List[List[int]]:
    """Chia từ thành các dòng vừa `width`, trả chỉ số từ của mỗi dòng."""
    rows: List[List[int]] = [[]]
    for i, w in enumerate(words):
        row = rows[-1]
        if row and fnt.getlength(" ".join(words[j] for j in row + [i])) > width:
            rows.append([i])
        else:
            row.append(i)
    return rows


def balanced_wrap(words: List[str], fnt, width: float) -> List[List[int]]:
    """Như `wrap` nhưng các dòng dài gần bằng nhau (tránh một chữ lẻ loi ở dòng cuối)."""
    rows = wrap(words, fnt, width)
    if len(rows) < 2:
        return rows
    lo, hi = width * 0.4, width
    for _ in range(14):   # tìm bề rộng nhỏ nhất vẫn giữ nguyên số dòng
        mid = (lo + hi) / 2
        if len(wrap(words, fnt, mid)) == len(rows):
            hi = mid
        else:
            lo = mid
    return wrap(words, fnt, hi)


# ── icon vẽ bằng hình cơ bản ───────────────────────────────────────────────


def icon_play(dr: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    dr.polygon([(cx - s * 0.35, cy - s * 0.45), (cx - s * 0.35, cy + s * 0.45), (cx + s * 0.45, cy)], fill=fill)


def icon_mic(dr: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    w = max(2, int(s * 0.1))
    dr.rounded_rectangle((cx - s * 0.2, cy - s * 0.5, cx + s * 0.2, cy + s * 0.12), radius=s * 0.2, fill=fill)
    dr.arc((cx - s * 0.36, cy - s * 0.3, cx + s * 0.36, cy + s * 0.3), 0, 180, fill=fill, width=w)
    dr.line((cx, cy + s * 0.3, cx, cy + s * 0.48), fill=fill, width=w)
    dr.line((cx - s * 0.2, cy + s * 0.48, cx + s * 0.2, cy + s * 0.48), fill=fill, width=w)


def icon_slow(dr: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    """Ba chấm nhỏ dần, gợi nhịp chậm lại."""
    for i, k in enumerate((0.22, 0.16, 0.11)):
        x = cx - s * 0.32 + i * s * 0.32
        dr.ellipse((x - s * k, cy - s * k, x + s * k, cy + s * k), fill=fill)


def icon_loop(dr: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    w = max(2, int(s * 0.12))
    dr.arc((cx - s * 0.42, cy - s * 0.42, cx + s * 0.42, cy + s * 0.42), 40, 340, fill=fill, width=w)
    dr.polygon([(cx + s * 0.28, cy - s * 0.52), (cx + s * 0.5, cy - s * 0.22), (cx + s * 0.14, cy - s * 0.2)], fill=fill)


def icon_check(dr: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    w = max(3, int(s * 0.14))
    dr.line([(cx - s * 0.38, cy), (cx - s * 0.1, cy + s * 0.3), (cx + s * 0.42, cy - s * 0.32)], fill=fill, width=w,
            joint="curve")


ICONS = {"listen": icon_play, "slow": icon_slow, "gap": icon_mic, "full": icon_loop, "done": icon_check}
