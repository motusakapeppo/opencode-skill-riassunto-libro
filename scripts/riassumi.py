#!/usr/bin/env python3
"""Deprecated entry point — kept so old commands keep working.

This script used to chain extract.py + pipeline_unificata.py and emit a DOCX.
The DOCX path was dropped: the skill's output is the PDF from scripts.renderer.
Usage: python scripts/riassumi.py <file> [lingua]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.cli import main as cli_main


def main() -> None:
    print(
        "[deprecated] riassumi.py → usa `python -m scripts.cli <file> [lingua]`.",
        file=sys.stderr,
    )
    cli_main()


if __name__ == "__main__":
    main()
