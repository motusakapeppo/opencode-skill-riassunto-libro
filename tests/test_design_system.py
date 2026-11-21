import pytest
from scripts.design_system import DesignSpec, detect_theme, generate_design, generate_cover_css, generate_header_css


def test_design_spec_defaults():
    d = DesignSpec()
    assert d.primary == "#1a2744"
    assert d.font_size_body == 10.5


def test_detect_theme_classic():
    theme = detect_theme("storia_romana.pdf")
    assert theme == "classic"


def test_detect_theme_forest():
    theme = detect_theme("bianconi_ecologia.pdf")
    assert theme == "forest"


def test_detect_theme_royal():
    theme = detect_theme("rosand_venice.pdf")
    assert theme == "royal"


def test_generate_design():
    d = generate_design("classic")
    assert isinstance(d, DesignSpec)
    assert d.primary == "#1a2744"


def test_generate_cover_css():
    d = DesignSpec()
    css = generate_cover_css(d)
    assert ".cover" in css
    assert d.primary in css


def test_generate_header_css():
    d = DesignSpec()
    css = generate_header_css(d)
    assert "h1" in css
    assert "h2" in css
    assert "h3" in css
