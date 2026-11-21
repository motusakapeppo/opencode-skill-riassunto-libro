import pytest
from scripts.design_system import select_fonts, GOOGLE_FONTS


def test_select_fonts_classic():
    fonts = select_fonts("classic")
    assert "family" in fonts["body"]
    assert "url" in fonts


def test_select_fonts_royal():
    fonts = select_fonts("royal")
    assert fonts["body"]["family"] == "Cormorant Garamond"


def test_select_fonts_ocean():
    fonts = select_fonts("ocean")
    assert fonts["body"]["family"] == "Inter"


def test_google_fonts_dict():
    assert "serif_classic" in GOOGLE_FONTS
    assert "sans_modern" in GOOGLE_FONTS
    assert "display_decorative" in GOOGLE_FONTS
