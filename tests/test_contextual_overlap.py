import pytest
from scripts.chunker import build_chunk_with_context
from scripts.models import Chunk
from scripts.config import Settings


def test_context_included():
    prev = Chunk(id=0, text="Testo precedente.", token_count=5)
    current = "Nuovo testo."
    result = build_chunk_with_context(current, prev, "Riassunto del precedente.", Settings())
    assert "[CONTESTO PRECEDENTE]" in result
    assert "Riassunto del precedente" in result
    assert "Nuovo testo." in result


def test_no_context():
    result = build_chunk_with_context("Solo testo.", None, None, Settings())
    assert "[CONTESTO PRECEDENTE]" not in result
    assert "Solo testo." in result
