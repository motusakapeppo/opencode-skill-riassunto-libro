import pytest
from scripts.config import load_settings, Settings


def test_load_settings_defaults():
    settings = load_settings()
    assert settings.ollama_host == "https://ollama.com/v1"
    assert settings.model_map == "deepseek-v4.1-flash"


def test_env_override(monkeypatch):
    monkeypatch.setenv("RIASSUNTO_OLLAMA_HOST", "http://localhost:11435")
    settings = load_settings()
    assert settings.ollama_host == "http://localhost:11435"


def test_env_override_int(monkeypatch):
    monkeypatch.setenv("RIASSUNTO_CHUNK_MAX_TOKENS", "32000")
    settings = load_settings()
    assert settings.chunk_max_tokens == 32000


def test_env_override_bool(monkeypatch):
    monkeypatch.setenv("RIASSUNTO_PLAYWRIGHT_HEADLESS", "false")
    settings = load_settings()
    assert settings.playwright_headless is False
