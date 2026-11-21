"""
Shared entry point for the CLI and the legacy entry points.

The pipeline itself lives in scripts.pipeline; this module only handles the
things every entry point needs: settings overrides, output paths, the PDF
render and the single line the orchestrating agent reads.
"""

from pathlib import Path
from typing import Optional

from loguru import logger

from scripts.config import Settings, load_settings
from scripts.models import PipelineResult
from scripts.pipeline import run_pipeline


def run_document(
    file_path: str,
    lingua: str = "it",
    *,
    settings: Optional[Settings] = None,
    config_path: Optional[str] = None,
    deep_scan: bool = False,
    no_pdf: bool = False,
) -> tuple[PipelineResult, Optional[str]]:
    """Run extract → chunk → map → synthesis → proofread → render.

    Returns:
        (result, pdf_path or None)
    """
    if settings is None:
        settings = load_settings(Path(config_path) if config_path else None)

    result = run_pipeline(file_path, settings, lingua, deep_scan)

    # Machine-readable handoff line for the orchestrating agent
    if result.vision_manifest:
        print(
            f"VISION_REQUIRED:{result.vision_manifest} "
            f"pages={','.join(str(p) for p in result.vision_pages)}"
        )

    pdf_path: Optional[str] = None
    if not no_pdf:
        pdf_path = _render(result, file_path, settings)
        result.output_path = pdf_path

    return result, pdf_path


def _render(result: PipelineResult, file_path: str, settings: Settings) -> Optional[str]:
    """Render the PDF. The prose gate lives here, before typesetting."""
    from scripts.design_system import detect_theme, generate_design
    from scripts.extractor import estrai_metadati
    from scripts.renderer import render_pdf
    from scripts.style import StyleViolation

    out_dir = Path(settings.output_dir)
    if not out_dir.is_absolute():
        out_dir = Path(file_path).parent / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    titolo, autore = estrai_metadati(file_path)
    theme = detect_theme(Path(file_path).stem, result.essay)
    design = generate_design(theme, result.essay)
    pdf_path = out_dir / f"Riassunto_{Path(file_path).stem}.pdf"

    try:
        render_pdf(result.essay, str(pdf_path), design, settings, titolo, autore)
    except StyleViolation as exc:
        print(f"STYLE_VIOLATION:{exc}")
        raise SystemExit(2)

    print(f"PDF:{pdf_path}")
    return str(pdf_path)


def print_stats(result: PipelineResult) -> None:
    print(
        f"\nStats: {result.total_chunks} chunks, "
        f"{result.processed_chunks} processed, "
        f"{result.coverage:.0f}% coverage, "
        f"{len(result.essay):,} chars"
    )
    if result.proofread:
        logger.info(f"Score: {result.proofread.score}/100")
