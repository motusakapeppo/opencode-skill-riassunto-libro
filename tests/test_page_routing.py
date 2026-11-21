"""Regression tests for page-level routing, cache and vision handoff.

Fast and offline: no Tesseract calls, no LLM calls.
"""

import json

import fitz
import pytest

from scripts.config import Settings
from scripts.extractor import (
    _join_pages,
    _page_quality,
    apply_vision,
    extract_document,
    load_vision_transcript,
)


BODY = (
    "Il teatro musicale veneziano del Seicento nasce attorno al mercato dell'opera. "
    "Il San Cassiano apre nel 1637 e Monteverdi vi contribuisce con opere pensate "
    "per un pubblico pagante, dove la brevita delle arie conta piu della trama. " * 3
)


def _make_pdf(path, text_pages=3, image_pages=1):
    doc = fitz.open()
    for _ in range(text_pages):
        page = doc.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), BODY, fontsize=10)
    for _ in range(image_pages):
        # A page with no text layer, only an image: must route to OCR/vision.
        page = doc.new_page()
        rect = page.rect
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), 0)
        pix.set_rect(pix.irect, (250, 250, 250))
        page.insert_image(rect, pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


def test_join_pages_emits_markers():
    joined = _join_pages(["uno", "due"])
    assert "[PAGINA 1]" in joined and "[PAGINA 2]" in joined
    assert joined.index("[PAGINA 1]") < joined.index("[PAGINA 2]")


@pytest.mark.parametrize("text,ok,reason", [
    ("", False, "empty"),
    ("   \n\n  ", False, "empty"),
    ("12 34 56 78 90 " * 10, False, "no_words"),
    ("a1 b2 c3 " * 40, False, "garbled"),
    (BODY, True, "ok"),
    ("Capitolo primo", True, "ok"),  # short title page is legitimate
])
def test_page_quality(text, ok, reason):
    got_ok, got_reason = _page_quality(text)
    assert got_ok is ok
    assert got_reason == reason


def test_apply_vision_replaces_only_known_pages():
    assert apply_vision(["a", "b", "c"], {2: " B "}) == ["a", "B", "c"]
    assert apply_vision(["a"], {7: "x"}) == ["a"]
    assert apply_vision(["a", "b"], {1: "   "}) == ["a", "b"]


def test_extraction_routes_ocr_and_caches(tmp_path):
    pdf = _make_pdf(tmp_path / "misto.pdf", text_pages=3, image_pages=1)
    settings = Settings(output_dir=str(tmp_path / "out"), vision_enabled=False)

    first = extract_document(str(pdf), settings)
    assert first.num_pages == 4
    assert "Monteverdi" in first.pages[0]
    # Only the image page can have needed OCR (0 or 1 pages, never all).
    assert all(p == 4 for p in first.ocr_pages)
    assert not first.needs_vision

    second = extract_document(str(pdf), settings)
    assert second.cache_hit is True
    assert second.text == first.text


def test_vision_manifest_and_transcript_roundtrip(tmp_path, monkeypatch):
    import scripts.extractor as extractor

    pdf = _make_pdf(tmp_path / "scan.pdf", text_pages=2, image_pages=1)
    settings = Settings(output_dir=str(tmp_path / "out"), cache_enabled=False)

    monkeypatch.setattr(extractor, "_tesseract_cmd", lambda s: None)
    staged = extract_document(str(pdf), settings)
    assert staged.vision_pages == [3]
    manifest_path = staged.vision_manifest
    assert manifest_path and json.loads(open(manifest_path, encoding="utf-8").read())["pages"][0]["page"] == 3
    assert (tmp_path / "out" / ".vision" / "scan" / "page-0003.png").exists()

    import os
    manifest = json.loads(open(manifest_path, encoding="utf-8").read())
    with open(manifest["transcript"], "w", encoding="utf-8") as fh:
        json.dump({"pages": {"3": "Testo trascritto dalla vision."}}, fh)

    merged = extract_document(str(pdf), settings)
    assert "+vision" in merged.method
    assert merged.pages[2] == "Testo trascritto dalla vision."
    assert merged.vision_pages == []
    assert load_vision_transcript(str(pdf), settings)[3].startswith("Testo trascritto")

