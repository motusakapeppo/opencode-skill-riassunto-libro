#!/usr/bin/env python3
"""Text extraction only — useful for debugging a document before a full run.

Usage:
    python scripts/extract.py <file>            # prints the extracted text
    python scripts/extract.py <file> --meta     # prints method/pages/OCR info only
    python scripts/extract.py <file> --json     # page texts as JSON
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import load_settings
from scripts.extractor import extract_document


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text from a document")
    parser.add_argument("file", help="Path to the document")
    parser.add_argument("--meta", action="store_true",
                        help="Print extraction metadata instead of the text")
    parser.add_argument("--json", action="store_true",
                        help="Print page texts as JSON")
    parser.add_argument("--deep-scan", action="store_true",
                        help="Force OCR on the PDF")
    args = parser.parse_args()

    result = extract_document(args.file, load_settings(), deep_scan=args.deep_scan)

    if args.json:
        print(json.dumps({
            "method": result.method,
            "num_pages": result.num_pages,
            "ocr_pages": result.ocr_pages,
            "vision_pages": result.vision_pages,
            "vision_dir": result.vision_dir,
            "pages": result.pages,
        }, ensure_ascii=False, indent=2))
        return

    if args.meta:
        print(f"method: {result.method}")
        print(f"pages: {result.num_pages}")
        print(f"chars: {len(result.text):,}")
        print(f"ocr_pages: {result.ocr_pages}")
        if result.vision_pages:
            print(f"vision_pages: {result.vision_pages} → {result.vision_dir}")
        return

    print(result.text)


if __name__ == "__main__":
    main()
