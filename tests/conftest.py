import pytest
from pathlib import Path

@pytest.fixture
def sample_text():
    return Path(__file__).parent / "fixtures" / "sample.txt"

@pytest.fixture
def config_dict():
    return {
        "ollama_host": "https://ollama.com/v1",
        "ollama_api_key": "test-key",
        "model_map": "deepseek-v4.1-flash",
        "model_reduce": "deepseek-v4.1-flash",
        "model_proofread": "deepseek-v4.1-flash",
        "chunk_max_tokens": 24000,
        "chunk_overlap_paragraphs": 2,
        "output_dir": "riassunti",
        "tesseract_path": None,
        "poppler_path": None,
    }
