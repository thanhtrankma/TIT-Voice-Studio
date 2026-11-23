"""Ảnh đại diện và ảnh bìa (banner) cho kênh YouTube Shadowing, cùng bộ màu với ảnh bìa video.

Chạy trong thư mục backend:
    uv run python -m app.branding --name "TIT Shadowing"          # ảnh lưu vào thư mục branding/
    uv run python -m app.branding --lang zh                        # kênh luyện tiếng Trung

Cỡ ảnh theo YouTube: ảnh đại diện 800×800 (hiện thành hình tròn, nhỏ nhất 98 px) và banner
2560×1440 ≤ 6 MB. Banner bị cắt khác nhau theo thiết bị: điện thoại chỉ thấy vùng giữa
1235×338, máy tính thấy dải ngang 2560×423, TV thấy cả ảnh. Vì vậy tên kênh và khẩu hiệu
nằm gọn trong vùng giữa, phần trang trí ở hai bên và trên dưới.
"""
import argparse
import math
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter

from . import chinese, design
from .config import ROOT
from .thumbnail import DEFAULT_THEME, INK, THEMES

AVATAR = 800
BANNER = (2560, 1440)
SAFE = (1235, 338)          # vùng giữa banner luôn hiện, kể cả trên điện thoại
DESKTOP_H = 423             # chiều cao dải banner trên máy tính
YELLOW = "#facc15"
NAME = "TIT Shadowing"
# ngôn ngữ kênh → khẩu hiệu, dòng nhãn, câu trang trí hai bên banner, chữ trong biểu tượng (None: sóng âm)
LANGS = {
    "en": {"tagline": "Luyện nói tiếng Anh bằng Shadowing",
           "features": "GIỌNG MỸ & ANH  ·  TỪNG CÂU MỘT  ·  CÓ NGHĨA TIẾNG VIỆT",
           "phrases": [("How are you?", "left"), ("Nice to meet you!", "left"),
                       ("Let's practice!", "right"), ("Could you repeat that?", "right")],
           "glyph": None},
    "zh": {"tagline": "Luyện nói tiếng Trung bằng Shadowing",
           "features": "GIỌNG BẢN XỨ  ·  CÓ PINYIN  ·  CÓ NGHĨA TIẾNG VIỆT",
           "phrases": [("你叫什么名字？", "left"), ("很高兴认识你！", "left"),
                       ("你好！", "right"), ("我们一起练习吧！", "right")],
           "glyph": "中"},
}
_WAVE = [0.35, 0.7, 1.0, 0.55, 0.85, 0.45, 0.28]


def _speech(dr: ImageDraw.ImageDraw, box, tail: str, fill) -> None:
    """Bong bóng thoại bo tròn, đuôi ở góc dưới trái hoặc phải."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    dr.rounded_rectangle(box, radius=h * 0.34, fill=fill)
    if tail == "left":
        dr.polygon([(x0 + w * 0.16, y1 - h * 0.1), (x0 + w * 0.42, y1 - h * 0.1), (x0 + w * 0.06, y1 + h * 0.3)],
                   fill=fill)
    else:
        dr.polygon([(x1 - w * 0.16, y1 - h * 0.1), (x1 - w * 0.42, y1 - h * 0.1), (x1 - w * 0.06, y1 + h * 0.3)],
                   fill=fill)


def mark(size: int, wave, glyph: Optional[str] = None) -> Image.Image:
    """Biểu tượng kênh: bong bóng trắng có sóng âm (hoặc chữ `glyph`, vd. 中 cho kênh tiếng Trung),
    phía sau là “cái bóng” vàng lệch ra như tiếng nhại lại. Vẽ ở cỡ gấp 4 rồi thu nhỏ cho viền mịn;
    trả ảnh RGBA vuông `size`."""
    k = 4
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _speech(ImageDraw.Draw(img), (0.30 * s, 0.10 * s, 0.92 * s, 0.58 * s), "right", YELLOW)

    front = (0.08 * s, 0.30 * s, 0.74 * s, 0.78 * s)
    shade = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _speech(ImageDraw.Draw(shade), tuple(v + s * 0.02 for v in front), "left", (0, 0, 0, 110))
    img = Image.alpha_composite(img, shade.filter(ImageFilter.GaussianBlur(s * 0.025)))
    dr = ImageDraw.Draw(img)
    _speech(dr, front, "left", "white")

    x0, y0, x1, y1 = front
    if glyph:
        dr.text(((x0 + x1) / 2, (y0 + y1) / 2), glyph, font=design.font("zh", int((y1 - y0) * 0.66)), fill=wave,
                anchor="mm")
        return img.resize((size, size), Image.LANCZOS)
    step = (x1 - x0) * 0.66 / len(_WAVE)
    cx0, cy = x0 + (x1 - x0) * 0.17, (y0 + y1) / 2
    for i, hgt in enumerate(_WAVE):
        x = cx0 + step * (i + 0.5)
        half = (y1 - y0) * 0.29 * hgt
        dr.rounded_rectangle((x - step * 0.26, cy - half, x + step * 0.26, cy + half), radius=step * 0.26, fill=wave)
    return img.resize((size, size), Image.LANCZOS)


def _colors(theme: str):
    c1, c2, _, line2 = THEMES.get(theme, THEMES[DEFAULT_THEME])
    # sóng âm trong bong bóng trắng cần màu đậm, đủ tương phản ở cỡ 98 px
    wave = c1 if theme != "night" else "#7c3aed"
    return c1, c2, line2, wave


def avatar(out: Path, theme: str = DEFAULT_THEME, lang: str = "en") -> Path:
    c1, c2, _, wave = _colors(theme)
    img = design.backdrop((AVATAR, AVATAR), c1, c2, spacing=40)
    img = design.glow(img, (AVATAR * 0.72, AVATAR * 0.22), 300, "#ffffff", 70)
    img = design.glow(img, (AVATAR * 0.1, AVATAR * 0.95), 260, "#000000", 70)
    m = mark(int(AVATAR * 0.8), wave, LANGS[lang]["glyph"])
    img.paste(m, ((AVATAR - m.width) // 2, int(AVATAR / 2 - m.height * 0.51)), m)   # căn theo phần có hình
    img.save(out, "PNG")
    return out


def _phrase(text: str, tail: str, size: int = 44) -> Image.Image:
    """Bong bóng câu nói nhỏ để trang trí hai bên banner; câu chữ Hán kèm pinyin bên dưới."""
    k = 2
    if chinese.has_hanzi(text):
        f, f_py, py = design.font("zh", int(size * k * 1.1)), design.font("demi", int(size * k * 0.6)), \
            chinese.pinyin_text(text)
        w = max(f.getlength(text), f_py.getlength(py)) + 70 * k
        h = size * k * 2.9
    else:
        f, py = design.font("bold", size * k), None
        w, h = f.getlength(text) + 70 * k, size * k * 2.1
    img = Image.new("RGBA", (int(w + 10 * k), int(h * 1.4)), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    _speech(dr, (0, 0, w, h), tail, (255, 255, 255, 235))
    if py:
        dr.text((w / 2, h * 0.40), text, font=f, fill=INK, anchor="mm")
        dr.text((w / 2, h * 0.76), py, font=f_py, fill=design.mix(INK, "#ffffff", 0.35), anchor="mm")
    else:
        dr.text((w / 2, h / 2), text, font=f, fill=INK, anchor="mm")
    return img.resize((img.width // k, img.height // k), Image.LANCZOS)


def _fit_name(words, max_w: float):
    """Tên kênh một dòng thật to; dài quá thì xuống hai dòng nhỏ hơn."""
    for max_rows, sizes in ((1, range(160, 95, -4)), (2, range(84, 55, -4))):
        for size in sizes:
            f = design.font("black", size)
            rows = design.balanced_wrap(words, f, max_w)
            if len(rows) <= max_rows and all(f.getlength(" ".join(words[j] for j in r)) <= max_w for r in rows):
                return f, rows
    raise ValueError("Tên kênh quá dài để vừa banner, hãy rút gọn.")


def _cap(f) -> float:
    return -f.getbbox("H", anchor="ls")[1]


def banner(out: Path, name: str = NAME, tagline: Optional[str] = None, theme: str = DEFAULT_THEME,
           lang: str = "en") -> Path:
    w, h = BANNER
    copy = LANGS[lang]
    tagline, features = tagline or copy["tagline"], copy["features"]
    c1, c2, line2, wave = _colors(theme)
    img = design.backdrop(BANNER, c1, c2, spacing=80)
    img = design.glow(img, (w * 0.5, h * 0.5), 640, "#ffffff", 40)
    img = design.glow(img, (w * 0.06, h * 0.95), 620, "#000000", 90)
    img = design.glow(img, (w * 0.95, h * 0.08), 520, "#ffffff", 45)

    # sóng âm mờ chạy suốt chiều ngang, sau mọi thứ
    layer = Image.new("RGBA", BANNER, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for i, x in enumerate(range(20, w, 36)):
        amp = 0.25 + 0.75 * abs(math.sin(i * 0.37) * math.cos(i * 0.11))
        half = 190 * amp
        ld.rounded_rectangle((x - 8, h / 2 - half, x + 8, h / 2 + half), radius=8, fill=(255, 255, 255, 26))
    img = Image.alpha_composite(img.convert("RGBA"), layer)

    # câu mẫu hai bên: chỉ hiện trên máy tính và TV
    sx0, sy0 = (w - SAFE[0]) // 2, (h - SAFE[1]) // 2
    band0 = (h - DESKTOP_H) // 2
    # hàng dưới (y None) canh theo mép dưới dải máy tính để đuôi bong bóng không bị cắt
    spots = {"left": [(170, band0 + 30, -5), (70, None, 4)],
             "right": [(sx0 + SAFE[0] + 150, band0 + 40, 5), (sx0 + SAFE[0] + 60, None, -4)]}
    for text, side in copy["phrases"]:
        x, y, angle = spots[side].pop(0)
        bub = _phrase(text, side).rotate(angle, resample=Image.BICUBIC, expand=True)
        if y is None:
            y = band0 + DESKTOP_H - bub.height - 6
        img.alpha_composite(bub, (int(x), int(y)))
    img = img.convert("RGB")

    # biểu tượng bên trái, tên kênh và khẩu hiệu bên phải, gọn trong vùng an toàn
    msize = 340
    m = mark(msize, wave, copy["glyph"])
    vis_l, vis_w = 0.08 * msize, 0.84 * msize       # phần có hình của biểu tượng
    img.paste(m, (int(sx0 - vis_l), int(h / 2 - msize * 0.52)), m)
    tx = sx0 + vis_w + 46
    max_w = sx0 + SAFE[0] - tx - 16     # chừa chỗ cho viền chữ

    words = name.upper().split()
    f_name, rows = _fit_name(words, max_w)
    f_tag = next((design.font("demi", s) for s in range(58, 29, -2)
                  if design.font("demi", s).getlength(tagline) <= max_w), design.font("demi", 30))
    f_pill = next((design.font("black", s) for s in range(36, 19, -2)
                   if design.font("black", s).getlength(features) + 48 <= max_w), design.font("black", 20))
    pill_h = f_pill.size * 1.7
    gap = 30 if len(rows) == 1 else 22
    lead = _cap(f_name) * 1.4      # khoảng dòng tên kênh, chừa chỗ cho dấu chồng của chữ hoa tiếng Việt
    total = _cap(f_name) + lead * (len(rows) - 1) + gap + _cap(f_tag) + f_tag.size * 0.28 + gap + pill_h
    y = h / 2 - total / 2 + _cap(f_name)

    # từ cuối tên kênh tô màu nhấn, phần còn lại màu trắng
    for row in rows:
        x = tx
        for i in row:
            color = line2 if i == len(words) - 1 and len(words) > 1 else "white"
            design.shadow_text(img, (x, y), words[i], f_name, color, anchor="ls", stroke=7, stroke_fill=INK,
                               offset=(0, 10), blur=12, shadow=(0, 0, 0, 170))
            x += f_name.getlength(words[i] + " ")
        y += lead
    y -= lead
    y += gap + _cap(f_tag)
    design.shadow_text(img, (tx, y), tagline, f_tag, "white", anchor="ls", offset=(0, 4), blur=8,
                       shadow=(0, 0, 0, 140))
    y += f_tag.size * 0.28 + gap
    dr = ImageDraw.Draw(img)
    dr.rounded_rectangle((tx, y, tx + f_pill.getlength(features) + 48, y + pill_h), radius=pill_h / 2,
                         fill=design.rgb(INK))
    dr.text((tx + 24, y + pill_h / 2), features, font=f_pill, fill=YELLOW, anchor="lm")

    img.save(out, "JPEG", quality=92)
    return out


def safe_box() -> Tuple[int, int, int, int]:
    w, h = BANNER
    return ((w - SAFE[0]) // 2, (h - SAFE[1]) // 2, (w + SAFE[0]) // 2, (h + SAFE[1]) // 2)


def main() -> None:
    p = argparse.ArgumentParser(description="Tạo ảnh đại diện và banner cho kênh YouTube Shadowing.")
    p.add_argument("--name", default=NAME, help="tên kênh hiện trên banner")
    p.add_argument("--tagline", help="khẩu hiệu dưới tên kênh (mặc định theo --lang)")
    p.add_argument("--lang", default="en", choices=list(LANGS), help="ngôn ngữ kênh: en tiếng Anh, zh tiếng Trung")
    p.add_argument("--theme", default=DEFAULT_THEME, choices=list(THEMES))
    p.add_argument("--out", default=ROOT.parent / "branding", type=Path, help="thư mục lưu ảnh")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    stem = a.theme if a.lang == "en" else f"{a.lang}-{a.theme}"
    print(avatar(a.out / f"avatar-{stem}.png", a.theme, a.lang))
    print(banner(a.out / f"banner-{stem}.jpg", a.name, a.tagline, a.theme, a.lang))


if __name__ == "__main__":
    main()
