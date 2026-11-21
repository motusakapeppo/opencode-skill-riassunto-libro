"""Regression tests — ensure backward compatibility with legacy modules and CLI."""

import pytest
import subprocess
import sys
from pathlib import Path


def test_cli_help():
    """CLI should show help without errors."""
    skill_root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "scripts.cli", "--help"],
        capture_output=True, text=True,
        cwd=str(skill_root),
    )
    assert result.returncode == 0
    assert "usage" in result.stdout.lower() or "usage" in result.stderr.lower()


def test_cli_nonexistent_file():
    """CLI should report error for missing file."""
    skill_root = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "scripts.cli", "nonexistent.pdf"],
        capture_output=True, text=True,
        cwd=str(skill_root),
    )
    assert result.returncode != 0


def test_legacy_imports():
    """Old scripts should still be importable."""
    import importlib
    for module in ["scripts.extract", "scripts.mega_skill", "scripts.pipeline_unificata", "scripts.riassumi"]:
        try:
            importlib.import_module(module)
        except ImportError as e:
            pytest.fail(f"Legacy module {module} failed to import: {e}")


def test_new_modules_importable():
    """All new modules should be importable."""
    import importlib
    for module in ["scripts.config", "scripts.models", "scripts.pipeline",
                   "scripts.extractor", "scripts.chunker", "scripts.llm_engine",
                   "scripts.design_system", "scripts.proofreader",
                   "scripts.cli"]:
        try:
            importlib.import_module(module)
        except ImportError as e:
            pytest.fail(f"New module {module} failed to import: {e}")
