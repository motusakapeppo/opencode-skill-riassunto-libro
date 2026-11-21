import pytest
from scripts.pipeline import run_pipeline
from scripts.config import Settings


def test_pipeline_nonexistent_file():
    """run_pipeline should raise FileNotFoundError for missing files."""
    settings = Settings()
    with pytest.raises(FileNotFoundError, match="File not found"):
        run_pipeline("nonexistent.pdf", settings)
