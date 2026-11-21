#!/usr/bin/env python3
"""Deprecated entry point — kept so old commands keep working.

The monolithic implementation (93 KB, old prompts, whole-book OCR) was replaced
by scripts.pipeline + scripts.extractor. This shim forwards to the current
pipeline so the two can never drift apart again.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.cli import main as cli_main


def main() -> None:
    print(
        "[deprecated] mega_skill.py → usa `python -m scripts.cli <file>`; "
        "stesso comportamento, argomenti compatibili.",
        file=sys.stderr,
    )
    cli_main()


if __name__ == "__main__":
    main()
