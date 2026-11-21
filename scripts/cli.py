#!/usr/bin/env python3
"""
Riassunto-Libro CLI — Unified entry point for the book-to-essay pipeline.
Usage: python -m scripts.cli <file> [lingua] [options]
"""

import sys
import argparse
from pathlib import Path
from loguru import logger
from scripts.config import load_settings
from scripts.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        description="Riassunto-Libro — Book-to-essay pipeline"
    )
    parser.add_argument("file", help="Path to input document")
    parser.add_argument("lingua", nargs="?", default="it",
                        choices=["it", "en"], help="Output language")
    parser.add_argument("--deep-scan", action="store_true",
                        help="Force OCR on all pages")
    parser.add_argument("--stats", action="store_true",
                        help="Print statistics after completion")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (overrides config)")
    parser.add_argument("--config", default=None,
                        help="Path to config YAML file")
    parser.add_argument("--no-pdf", action="store_true",
                        help="Skip PDF generation (text only)")

    # Extraction tuning
    parser.add_argument("--ocr-dpi", type=int, default=None,
                        help="Base render DPI for OCR (default 200)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Parallel OCR workers (default: CPU count)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Ignore and do not write the extraction cache")
    parser.add_argument("--no-vision", action="store_true",
                        help="Never stage unreadable pages for the vision lane")
    parser.add_argument("--vision-first", action="store_true",
                        help="Send the whole book to the vision lane (short docs)")
    parser.add_argument("--vision-transcript", default=None,
                        help="Page->text JSON produced by the vision lane")

    args = parser.parse_args()

    # Load settings
    settings = load_settings(
        Path(args.config) if args.config else None
    )
    if args.output_dir:
        settings.output_dir = args.output_dir
    if args.ocr_dpi:
        settings.ocr_dpi = args.ocr_dpi
    if args.workers:
        settings.ocr_workers = args.workers
    if args.no_cache:
        settings.cache_enabled = False
    if args.no_vision:
        settings.vision_enabled = False
    if args.vision_first:
        settings.vision_first = True
    if args.vision_transcript:
        settings.vision_transcript = args.vision_transcript

    # Run pipeline
    result = run_pipeline(args.file, settings, args.lingua, args.deep_scan)

    # Machine-readable handoff line for the orchestrating agent
    if result.vision_manifest:
        print(f"VISION_REQUIRED:{result.vision_manifest} "
              f"pages={','.join(str(p) for p in result.vision_pages)}")

    # Stats
    if args.stats:
        print(f"\nStats: {result.total_chunks} chunks, "
              f"{result.processed_chunks} processed, "
              f"{result.coverage:.0f}% coverage, "
              f"{len(result.essay):,} chars")


if __name__ == "__main__":
    main()
