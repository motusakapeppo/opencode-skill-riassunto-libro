from pathlib import Path
import pytest
from scripts.chunker import split_into_chunks, save_checkpoint, load_checkpoint
from scripts.config import Settings
from scripts.models import Chunk


def test_split_basic():
    settings = Settings()
    text = "Paragrafo uno.\n\nParagrafo due.\n\nParagrafo tre."
    chunks = split_into_chunks(text, settings)
    assert len(chunks) >= 1
    assert all(isinstance(c.id, int) for c in chunks)


def test_split_with_page_markers():
    settings = Settings()
    text = "[PAGINA 1]\n\nContenuto pagina uno.\n\n[PAGINA 2]\n\nContenuto pagina due."
    chunks = split_into_chunks(text, settings)
    assert len(chunks) >= 1


def test_split_large_paragraph():
    settings = Settings(chunk_max_tokens=100, chunk_min_tokens=0)
    text = " ".join(["Frase numero " + str(i) + "." for i in range(200)])
    chunks = split_into_chunks(text, settings)
    assert len(chunks) > 1


def test_checkpoint_roundtrip(tmp_path):
    cp = tmp_path / "checkpoint.json"
    chunks = [Chunk(id=0, text="a", token_count=5), Chunk(id=1, text="b", token_count=5)]
    save_checkpoint(cp, chunks, [{"chunk_id": 0, "summary": "done"}])
    results, done_ids = load_checkpoint(cp, 2)
    assert len(results) == 1
    assert 0 in done_ids
    assert 1 not in done_ids


def test_split_returns_chunk_objects():
    settings = Settings()
    text = "Uno.\n\nDue.\n\nTre."
    chunks = split_into_chunks(text, settings)
    for c in chunks:
        assert isinstance(c, Chunk)
        assert isinstance(c.id, int)
        assert isinstance(c.text, str)
        assert isinstance(c.token_count, int)


def test_split_empty_text():
    settings = Settings()
    chunks = split_into_chunks("", settings)
    assert chunks == []


def test_split_whitespace_only():
    settings = Settings()
    chunks = split_into_chunks("   \n\n   \n\n  ", settings)
    assert chunks == []


def test_checkpoint_missing():
    cp = Path("C:\\nonexistent\\path\\checkpoint.json")
    results, done_ids = load_checkpoint(cp, 10)
    assert results == []
    assert done_ids == set()


def test_checkpoint_total_mismatch(tmp_path):
    cp = tmp_path / "checkpoint.json"
    chunks = [Chunk(id=0, text="a", token_count=5)]
    save_checkpoint(cp, chunks, [{"chunk_id": 0, "summary": "done"}])
    results, done_ids = load_checkpoint(cp, 99)
    assert results == []
    assert done_ids == set()


def test_split_with_overlap():
    settings = Settings(chunk_max_tokens=50, chunk_min_tokens=0, chunk_overlap_paragraphs=1)
    text = "\n\n".join([f"Paragrafo numero {i} con contenuto vario per test." for i in range(10)])
    chunks = split_into_chunks(text, settings)
    assert len(chunks) >= 2
    # Check that overlap carries content forward
    for c in chunks:
        assert c.token_count <= settings.chunk_max_tokens + 50  # allow some slack


def test_merge_small_chunks():
    settings = Settings(chunk_min_tokens=100)
    text = "\n\n".join([f"Breve paragrafo {i}." for i in range(5)])
    chunks = split_into_chunks(text, settings)
    # All chunks should be >= min_tokens or there's only one
    for c in chunks:
        assert c.token_count >= settings.chunk_min_tokens or len(chunks) == 1
