import pytest
from pathlib import Path
from scripts.renderer import build_html
from scripts.design_system import DesignSpec


def test_build_html_basic():
    essay = "### Introduzione\n\nTesto del saggio.\n\n### Da Ricordare\n\n**Concetto** — spiegazione."
    design = DesignSpec()
    html = build_html(essay, design, "Test Book", "Test Author")
    assert "<!DOCTYPE html>" in html
    assert "<h3>Introduzione</h3>" in html
    assert "<strong>Concetto</strong>" in html
    assert "Test Book" in html
    assert "Test Author" in html


def test_build_html_bold():
    essay = "**Monteverdi** compose l'**Orfeo**."
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "<strong>Monteverdi</strong>" in html
    assert "<strong>Orfeo</strong>" in html


def test_build_html_concept_table():
    essay = "### Scheda Riassuntiva\n\nConcetto: Termine - Spiegazione"
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "<table" in html
    assert "Termine" in html
    assert "Spiegazione" in html


def test_build_html_qa():
    essay = "### Domande di Verifica\n\nDomanda: Quesito? - Risposta."
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "Quesito?" in html
    assert "Risposta." in html


def test_build_html_cronologia():
    essay = "### Cronologia\n\n**1607** — Prima dell'Orfeo."
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "cronologia-anno" in html
    assert "1607" in html
    assert "Orfeo" in html


def test_build_html_glossario():
    essay = "### Glossario\n\n**Recitativo** — Stile di canto."
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "glossario-termine" in html
    assert "Recitativo" in html
    assert "Stile di canto" in html


def test_build_html_opere():
    essay = "### Opere Citati\n\n**Monteverdi (1607)** — L'Orfeo."
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "opere-item" in html
    assert "Monteverdi" in html


def test_build_html_cover_title_long():
    essay = "Testo."
    design = DesignSpec()
    long_title = "A" * 60
    html = build_html(essay, design, long_title)
    assert "cover-title-long" in html


def test_build_html_no_autore():
    essay = "Testo."
    design = DesignSpec()
    html = build_html(essay, design, "Test")
    assert "Autore sconosciuto" not in html


def test_build_html_google_fonts():
    essay = "Testo."
    design = DesignSpec(google_fonts_url="https://fonts.googleapis.com/css2?family=Libre+Baskerville")
    html = build_html(essay, design, "Test")
    assert "fonts.googleapis.com" in html
