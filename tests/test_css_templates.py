import pytest
from scripts.css_templates import base_css, cover_css, headings_css, special_sections_css, concept_table_css, qa_css, all_css
from scripts.design_system import DesignSpec


def test_base_css_contains_page():
    design = DesignSpec()
    css = base_css(design)
    assert "@page" in css
    assert "A4" in css


def test_base_css_contains_font():
    design = DesignSpec()
    css = base_css(design)
    assert "Georgia" in css or "serif" in css


def test_cover_css():
    design = DesignSpec()
    css = cover_css(design)
    assert ".cover" in css


def test_headings_css():
    design = DesignSpec()
    css = headings_css(design)
    assert "h1" in css
    assert "h2" in css
    assert "h3" in css


def test_special_sections_css():
    design = DesignSpec()
    css = special_sections_css(design)
    assert ".section-ricordare" in css
    assert ".box-key" in css
    assert ".cronologia-item" in css


def test_concept_table_css():
    design = DesignSpec()
    css = concept_table_css(design)
    assert ".concept-table" in css


def test_qa_css():
    design = DesignSpec()
    css = qa_css(design)
    assert ".qa-block" in css


def test_all_css_combined():
    design = DesignSpec()
    css = all_css(design)
    assert "@page" in css
    assert ".cover" in css
    assert "h1" in css
    assert ".concept-table" in css
    assert ".qa-block" in css
