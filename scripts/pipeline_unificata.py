#!/usr/bin/env python3
"""Deprecated entry point — kept so old commands keep working.

The unified pipeline (28 KB, subprocess calls to extract.py) was replaced by
scripts.pipeline. This shim forwards to the current CLI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.cli import main as cli_main


def main() -> None:
    print(
        "[deprecated] pipeline_unificata.py → usa `python -m scripts.cli <file>`.",
        file=sys.stderr,
    )
    cli_main()


if __name__ == "__main__":
    main()
