"""Ảnh đại diện và banner kênh đúng cỡ YouTube, tên kênh luôn nằm trong vùng an toàn."""
import pytest
from PIL import Image

from app import branding
from app.thumbnail import THEMES


@pytest.mark.parametrize("theme", list(THEMES))
@pytest.mark.parametrize("lang", list(branding.LANGS))
def test_channel_art_matches_youtube_sizes(tmp_path, theme, lang):
    with Image.open(branding.avatar(tmp_path / "a.png", theme, lang)) as img:
        assert img.size == (800, 800)
    out = branding.banner(tmp_path / "b.jpg", theme=theme, lang=lang)
    with Image.open(out) as img:
        assert img.size == (2560, 1440) and img.format == "JPEG"
    assert out.stat().st_size < 6_000_000   # YouTube nhận banner tối đa 6 MB


def test_long_channel_name_wraps_or_is_rejected(tmp_path):
    max_w = 700
    f, rows = branding._fit_name("LUYỆN NÓI TIẾNG ANH MỖI NGÀY CÙNG TIT".split(), max_w)
    assert len(rows) == 2
    f, rows = branding._fit_name(["TIT", "SHADOWING"], max_w)
    assert len(rows) == 1 and f.size >= 96
    with pytest.raises(ValueError, match="quá dài"):
        branding.banner(tmp_path / "x.jpg", name="A" * 30 + " " + "B" * 30)
