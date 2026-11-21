from scripts.models import Chunk, EntitySet, MapResult, ProofreadResult, PipelineResult


def test_chunk_defaults():
    c = Chunk(id=0, text="hello", token_count=5)
    assert c.pdf_pages is None


def test_entity_set():
    e = EntitySet(persone=["Monteverdi"], date=["1637"])
    assert "Monteverdi" in e.persone
    assert "1637" in e.date


def test_map_result_defaults():
    r = MapResult(chunk_id=0, summary="text", entities=EntitySet(), token_count=10)
    assert r.coverage == 100
    assert r.integration == ""


def test_proofread_result():
    r = ProofreadResult(score=85)
    assert r.score == 85
    assert r.issues == []
    assert r.suggestions == []


def test_pipeline_result():
    r = PipelineResult(
        essay="test", entities=EntitySet(),
        total_chunks=5, processed_chunks=5, coverage=100.0
    )
    assert r.proofread is None
