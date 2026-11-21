"""The tree must stay clean UTF-8: no BOM, no mojibake, no mixed EOL.

This is the guard for the class of bug that hit this repo once: PowerShell
text cmdlets re-encoded whole files to cp1252 and prepended a BOM, turning
em-dashes into "?" and accents into "?".
"""

from pathlib import Path

import pytest

from scripts.check_encoding import BOM, check_file, iter_files

ROOT = Path(__file__).resolve().parent.parent


def test_whole_tree_is_clean():
    bad = {}
    for path in iter_files([ROOT], set()):
        problems = check_file(path)
        if problems:
            bad[str(path.relative_to(ROOT))] = problems

    assert not bad, (
        "File di testo non puliti (UTF-8/BOM/EOL):\n"
        + "\n".join(f"  {p}: {', '.join(v)}" for p, v in sorted(bad.items()))
        + "\nEsegui: python scripts/check_encoding.py --fix"
    )


@pytest.mark.parametrize("payload,expected", [
    (BOM + b"# titolo\n", "bom"),
    ("prezzo \u20ac 5\n".encode("utf-8").replace(b"\xe2\x82\xac", b"\xe2\x82"), "invalid-utf8"),
    ("citt\u00e0 \u2014 fine\n".encode("utf-8"), None),
    ("\ufffd un errore\n".encode("utf-8"), "replacement-char"),
    ("testo \ufffd rotto\n".encode("utf-8"), "replacement-char"),
    (b"riga uno\r\ndue\n", "mixed-eol"),
])
def test_detects_damage(tmp_path, payload, expected):
    path = tmp_path / "sample.py"
    path.write_bytes(payload)
    problems = check_file(path)
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


def test_detects_mojibake(tmp_path):
    # "è" as UTF-8 bytes read back as cp1252, built from escapes on purpose.
    damaged = "\u00c3\u00a8 un errore\n".encode("utf-8")
    path = tmp_path / "sample.py"
    path.write_bytes(damaged)
    assert any("mojibake" in p for p in check_file(path))


def test_fix_strips_bom_and_normalises_eol(tmp_path):
    path = tmp_path / "sample.py"
    path.write_bytes(BOM + b"riga uno\r\nriga due\n")

    problems = check_file(path)
    assert "bom" in problems and "mixed-eol" in problems

    check_file(path, fix=True)
    assert path.read_bytes() == b"riga uno\nriga due\n"
    assert check_file(path) == []
