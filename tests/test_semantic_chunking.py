import pytest
from scripts.chunker import find_section_boundaries, split_into_chunks
from scripts.config import Settings


def test_find_chapter_boundaries():
    text = "CAPITOLO 1\n\nTesto del primo capitolo.\n\nCAPITOLO 2\n\nTesto del secondo."
    boundaries = find_section_boundaries(text)
    assert len(boundaries) >= 2


def test_find_markdown_boundaries():
    text = "# Introduzione\n\nTesto.\n\n## Sezione 1\n\nTesto sezione."
    boundaries = find_section_boundaries(text)
    assert len(boundaries) >= 2


def test_semantic_chunking_respects_boundaries():
    text = "CAPITOLO 1\n\n" + "Parola. " * 500 + "\n\nCAPITOLO 2\n\n" + "Parola. " * 500
    settings = Settings(chunk_max_tokens=500, chunk_min_tokens=0)
    chunks = split_into_chunks(text, settings)
    assert len(chunks) >= 2
    # Find which chunks contain each heading
    ch1_idx = next(i for i, c in enumerate(chunks) if "CAPITOLO 1" in c.text)
    ch2_idx = next(i for i, c in enumerate(chunks) if "CAPITOLO 2" in c.text)
    assert ch1_idx < ch2_idx, "CAPITOLO 1 should appear before CAPITOLO 2"
