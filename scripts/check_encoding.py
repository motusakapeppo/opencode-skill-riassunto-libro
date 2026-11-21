#!/usr/bin/env python3
"""
Encoding guard — fails if any text file is not clean UTF-8.

Written after PowerShell 5.1 text cmdlets (Get-Content / Set-Content /
-replace) silently re-encoded whole files from cp1252 and prepended a BOM,
turning em-dashes and accented letters into "?" and "?".

Checks:
  BOM             UTF-8/UTF-16 byte order mark
  invalid-utf8    bytes that are not valid UTF-8
  replacement     U+FFFD REPLACEMENT CHARACTER (data loss marker)
  mojibake        UTF-8 read back as cp1252 ("Ã¨", "â€”", "Â ")
  nfd             decomposed accents instead of NFC (breaks search/diff)
  crlf            CRWindows line endings (.gitattributes asks for LF)
  mixed-eol       CRLF and LF in the same file

Usage:
    python scripts/check_encoding.py                # whole tree
    python scripts/check_encoding.py --staged       # only git-staged files
    python scripts/check_encoding.py --fix          # strip BOM, normalise EOL
    python scripts/check_encoding.py path1 path2
"""

import argparse
import subprocess
import sys
import unicodedata
from pathlib import Path

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".json", ".css", ".html",
    ".htm", ".rst", ".cfg", ".ini", ".sh", ".bat", ".ps1", ".cff", ".lock",
}
TEXT_NAMES = {".gitignore", ".gitattributes", ".editorconfig", "requirements"}
SKIP_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", ".riassunto-cache",
    ".vision", "riassunti", ".omo", "node_modules",
}
# UTF-8 read back as cp1252. Written as escapes so this file never contains the
# damaged sequences it looks for.
MOJIBAKE = tuple(
    code.encode("utf-8").decode("latin-1") for code in ("è", "ù", "à", "é", "ì", "ò")
) + ("â€”", "â€œ", "â€™", "Â ", "ï¿½", "Ã—")

BOM = b"\xef\xbb\xbf"
BOM_UTF16 = (b"\xff\xfe", b"\xfe\xff")


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


def iter_files(roots: list[Path], skip: set[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if root.is_file():
            if is_text_file(root):
                out.append(root)
            continue
        for path in root.rglob("*"):
            if not path.is_file() or not is_text_file(path):
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path in skip:
                continue
            out.append(path)
    return sorted(set(out))


def check_file(path: Path, fix: bool = False) -> list[str]:
    problems: list[str] = []
    raw = path.read_bytes()

    if raw.startswith(BOM_UTF16):
        problems.append("bom-utf16")
    elif raw.startswith(BOM):
        problems.append("bom")
        if fix:
            raw = raw[len(BOM):]
            path.write_bytes(raw)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        problems.append(f"invalid-utf8@{exc.start}")
        return problems

    if "\ufffd" in text:
        problems.append(f"replacement-char x{text.count(chr(0xFFFD))}")

    if path.name != "check_encoding.py":
        for token in MOJIBAKE:
            count = text.count(token)
            if count:
                problems.append(f"mojibake {token!r} x{count}")

    if unicodedata.normalize("NFC", text) != text:
        problems.append("nfd-accents")

    has_crlf = "\r\n" in text
    has_lf = "\n" in text.replace("\r\n", "")
    if has_crlf and has_lf:
        problems.append("mixed-eol")
    elif has_crlf:
        problems.append("crlf")
    if has_crlf and fix:
        path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))
        problems = [p for p in problems if p not in ("mixed-eol", "crlf")]

    return problems


def staged_files(root: Path) -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            cwd=str(root), capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    files = []
    for line in out.splitlines():
        path = root / line.strip()
        if path.is_file() and is_text_file(path):
            files.append(path)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail on non-clean UTF-8 text files")
    parser.add_argument("paths", nargs="*", help="Files or directories (default: repo root)")
    parser.add_argument("--staged", action="store_true", help="Only git-staged files")
    parser.add_argument("--fix", action="store_true", help="Strip BOM and normalise EOL")
    parser.add_argument("--quiet", action="store_true", help="Only the summary line")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    if args.staged:
        targets = staged_files(root)
        roots: list[Path] = []
    elif args.paths:
        roots = [Path(p) for p in args.paths]
        targets = []
    else:
        roots = [root]
        targets = []

    files = sorted(set(it for it in list(targets)) ) if targets else iter_files(roots, set())
    if not files:
        if not args.quiet:
            print("Nessun file di testo da controllare.")
        return 0

    failures = 0
    for path in files:
        problems = check_file(path, fix=args.fix)
        if problems:
            failures += 1
            rel = path.relative_to(root) if str(path).startswith(str(root)) else path
            print(f"{rel}: {', '.join(problems)}")

    if failures:
        print(f"\n{failures}/{len(files)} file non puliti.")
        if not args.fix:
            print("Correzione automatica possibile solo per BOM/EOL: --fix")
            print("Per caratteri corrotti (?, U+FFFD, mojibake) serve ripristinare il contenuto.")
        return 1

    if not args.quiet:
        print(f"OK: {len(files)} file di testo, UTF-8 pulito, nessun BOM.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
