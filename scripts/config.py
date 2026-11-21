"""
Configuration module for riassunto-libro.
Loads settings from YAML file + environment variable overrides.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any
import os
import yaml


@dataclass
class Settings:
    """All configurable settings for the riassunto-libro pipeline."""
    ollama_host: str = "https://ollama.com/v1"
    ollama_api_key: str = field(default_factory=lambda: os.environ.get("OLLAMA_API_KEY", ""))
    model_map: str = "deepseek-v4.1-flash"
    model_reduce: str = "deepseek-v4.1-flash"
    model_proofread: str = "deepseek-v4.1-flash"
    chunk_max_tokens: int = 24000
    chunk_overlap_paragraphs: int = 2
    chunk_min_tokens: int = 800
    output_dir: str = "riassunti"
    tesseract_path: Optional[str] = None
    poppler_path: Optional[str] = None
    playwright_headless: bool = True
    log_level: str = "INFO"
    max_retries: int = 5
    retry_base_delay: int = 30

    # --- PDF extraction / OCR ---
    ocr_dpi: int = 200                      # base render DPI for Tesseract
    ocr_dpi_max: int = 300                 # escalation DPI for garbage pages
    ocr_workers: int = 0                   # 0 = os.cpu_count()
    ocr_lang: Optional[str] = None         # None = derive from output language
    ocr_psm: int = 3
    ocr_preprocess: bool = True            # grayscale autocontrast before OCR
    cache_enabled: bool = True             # skip re-extraction on re-runs
    cache_dir: Optional[str] = None        # None = <file dir>/.riassunto-cache
    pdf_layout_probe: bool = True          # probe pdftotext -layout for columns

    # --- Vision lane (agent reads page images that OCR could not handle) ---
    vision_enabled: bool = True            # stage unreadable pages for the agent
    vision_first: bool = False             # send whole short book to vision
    vision_first_max_pages: int = 30
    vision_max_pages: int = 40             # cap on pages staged per run
    vision_transcript: Optional[str] = None


def _find_config() -> Optional[Path]:
    """Find config file: env var override, or config.yaml in skill root."""
    env_path = os.environ.get("RIASSUNTO_CONFIG")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    
    # Look for config.yaml in parent directories up to the skill root
    # Start from this file's directory
    current = Path(__file__).parent.parent  # scripts/../ = skill root
    candidate = current / "config.yaml"
    if candidate.exists():
        return candidate
    
    return None


def _env_override(key: str, current: Any) -> Any:
    """Check RIASSUNTO_{KEY} env var, return override or current."""
    env_key = f"RIASSUNTO_{key.upper()}"
    val = os.environ.get(env_key)
    if val is None:
        return current
    if isinstance(current, bool):
        return val.lower() in ("1", "true", "yes")
    if isinstance(current, int):
        return int(val)
    if isinstance(current, str):
        return val
    return val


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """Load settings from YAML file with env var overrides.
    
    Resolution order (later wins):
    1. Default values in Settings dataclass
    2. YAML config file
    3. Environment variables RIASSUNTO_*
    """
    settings = Settings()
    
    # Try to find and load YAML config
    if config_path is None:
        config_path = _find_config()
    
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
        if yaml_data:
            for key, value in yaml_data.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
    
    # Apply env var overrides
    for field_name in settings.__dataclass_fields__:
        current = getattr(settings, field_name)
        overridden = _env_override(field_name, current)
        setattr(settings, field_name, overridden)
    
    return settings
