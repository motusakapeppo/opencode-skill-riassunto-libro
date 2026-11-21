"""End-to-end integration tests for the riassunto-libro pipeline."""

import pytest
from pathlib import Path
from scripts.config import Settings, load_settings
from scripts.pipeline import run_pipeline
from scripts.models import PipelineResult


def test_pipeline_with_sample_text(sample_text, tmp_path):
    """Run full pipeline on sample.txt and verify output structure.
    
    This test requires Ollama to be running — skip if not available.
    """
    settings = Settings()
    settings.output_dir = str(tmp_path)
    
    import requests
    try:
        headers = {"Authorization": f"Bearer {settings.ollama_api_key}"} if settings.ollama_api_key else {}
        requests.get(f"{settings.ollama_host}/models", headers=headers, timeout=10)
    except (requests.ConnectionError, requests.Timeout):
        pytest.skip("Ollama not available")
    
    result = run_pipeline(str(sample_text), settings)
    
    assert isinstance(result, PipelineResult)
    assert len(result.essay) > 100
    assert result.total_chunks > 0
    assert result.processed_chunks > 0
    assert result.coverage > 0


def test_pipeline_output_structure(sample_text, tmp_path):
    """Run pipeline and verify essay structure."""
    settings = Settings()
    settings.output_dir = str(tmp_path)
    
    import requests
    try:
        headers = {"Authorization": f"Bearer {settings.ollama_api_key}"} if settings.ollama_api_key else {}
        requests.get(f"{settings.ollama_host}/models", headers=headers, timeout=10)
    except (requests.ConnectionError, requests.Timeout):
        pytest.skip("Ollama not available")
    
    result = run_pipeline(str(sample_text), settings)
    
    # Verify required sections
    assert "### Da Ricordare" in result.essay
    assert "### Scheda Riassuntiva" in result.essay
    assert "### Domande di Verifica" in result.essay


@pytest.mark.timeout(300)  # 5 min for LLM calls
def test_pipeline_entities_extracted(sample_text, tmp_path):
    """Run pipeline and verify entities are extracted."""
    settings = Settings()
    settings.output_dir = str(tmp_path)
    
    import requests
    try:
        headers = {"Authorization": f"Bearer {settings.ollama_api_key}"} if settings.ollama_api_key else {}
        requests.get(f"{settings.ollama_host}/models", headers=headers, timeout=10)
    except (requests.ConnectionError, requests.Timeout):
        pytest.skip("Ollama not available")
    
    result = run_pipeline(str(sample_text), settings)
    
    total_entities = (len(result.entities.persone) +
                      len(result.entities.date) +
                      len(result.entities.opere))
    assert total_entities > 0
