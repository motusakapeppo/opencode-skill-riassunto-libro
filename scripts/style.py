"""
Style contract for the generated essay.

The skill produces two very different artefacts and they must not be conflated:

- ``prose`` (default) — a discursive essay for study. No bullet lists, no
  label-headings, no bibliographic metadata transcribed instead of narrated.
- ``notes`` — compact exam notes where lists are legitimate.

Everything here is deterministic and measurable: the LLM prompt states the
contract, and these functions verify it instead of trusting adjectives.
"""

import re
from dataclasses import dataclass, field

# A line that starts with a list marker. Bold-only lines ("**Termine** — ...")
# are NOT bullets: the Cronologia/Glossario sections rely on them.
BULLET_RE = re.compile(r"^\s{0,3}(?:[-*•–—]|\d{1,2}[.)])\s+(?=\S)")

# Bibliographic metadata that must never be transcribed in place of content.
BIBLIO_RE = re.compile(
    r"\b(?:ISSN|ISBN|DOI)\b"
    r"|\bdoi:\s*10\."
    r"|\bpp?\.\s*\d+"
    r"|\bvol\.\s*\d+"
    r"|\bpag(?:ina|ine)?\.?\s*\d+"
    r"|\btomo\s+[IVXLC\d]+",
    re.IGNORECASE,
)

# Label-headings the model invents when asked to "not miss anything":
# "### Concetti chiave", "### Esempi", "### Introduzione" as bare labels.
LABEL_HEADINGS = {
    "concetti chiave", "concetti principali", "esempi", "introduzione",
    "conclusione", "riassunto", "sintesi", "note", "osservazioni",
    "punti chiave", "key concepts", "examples", "introduction", "conclusion",
    "summary", "notes",
}

SECTION_HEADINGS = (
    "Da Ricordare",
    "Cronologia",
    "Glossario",
    "Opere Citati",
    "Scheda Riassuntiva",
    "Domande di Verifica",
)


class StyleViolation(RuntimeError):
    """Raised when prose mode gets a document that is structurally a list dump."""


@dataclass
class StyleStats:
    lines: int = 0
    bullet_lines: int = 0
    words: int = 0
    lists: int = 0
    label_headings: int = 0
    bibliographic: int = 0
    paragraphs: int = 0
    short_paragraphs: int = 0

    @property
    def bullet_ratio(self) -> float:
        return self.bullet_lines / self.lines if self.lines else 0.0

    @property
    def lists_per_1000_words(self) -> float:
        return (self.lists / self.words * 1000) if self.words else 0.0

    def is_bullet_dump(self, max_ratio: float = 0.03, max_lists_per_1000: float = 2.0) -> bool:
        """Spec threshold: a document that is structurally an outline."""
        return self.bullet_ratio > max_ratio or self.lists_per_1000_words > max_lists_per_1000

    def is_severe(self) -> bool:
        """Render gate: too far gone to be fixed by converting markers."""
        return self.bullet_lines >= 8 and (
            self.bullet_ratio > 0.10 or self.lists_per_1000_words > 2.0
        )

    def as_dict(self) -> dict:
        return {
            "lines": self.lines,
            "bullet_lines": self.bullet_lines,
            "bullet_ratio": round(self.bullet_ratio, 3),
            "lists": self.lists,
            "lists_per_1000_words": round(self.lists_per_1000_words, 2),
            "label_headings": self.label_headings,
            "bibliographic": self.bibliographic,
            "paragraphs": self.paragraphs,
            "short_paragraphs": self.short_paragraphs,
        }


def analyse_style(text: str) -> StyleStats:
    """Measure the document against the prose contract."""
    stats = StyleStats()
    body_lines = [ln for ln in (text or "").split("\n") if ln.strip()]
    stats.lines = len(body_lines)
    stats.words = len((text or "").split())

    in_list = False
    paragraphs = [p for p in (text or "").split("\n\n") if p.strip()]

    for line in body_lines:
        stripped = line.strip()
        if BULLET_RE.match(line):
            stats.bullet_lines += 1
            if not in_list:
                stats.lists += 1
                in_list = True
            continue
        in_list = False
        if stripped.startswith("#"):
            label = stripped.lstrip("#").strip().lower()
            if label in LABEL_HEADINGS:
                stats.label_headings += 1

    stats.bibliographic = len(BIBLIO_RE.findall(text or ""))
    stats.paragraphs = len(paragraphs)
    stats.short_paragraphs = sum(
        1 for p in paragraphs
        if not p.strip().startswith("#") and len(p.split()) < 25
    )
    return stats


def strip_bullet_markup(text: str) -> str:
    """Turn list blocks into paragraphs, keeping the content.

    Consecutive bullet lines become one paragraph: markers removed, sentence
    endings ensured, items joined with a space. Nothing is invented.
    """
    out: list[str] = []
    block: list[str] = []

    def flush() -> None:
        if not block:
            return
        items = []
        for item in block:
            cleaned = BULLET_RE.sub("", item).strip()
            if not cleaned:
                continue
            if not cleaned.endswith((".", "!", "?", ":", ";")):
                cleaned += "."
            items.append(cleaned)
        if items:
            out.append(" ".join(items))
        block.clear()

    for line in (text or "").split("\n"):
        if BULLET_RE.match(line):
            block.append(line)
            continue
        flush()
        out.append(line)
    flush()

    cleaned_text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned_text)


def enforce_prose(text: str, settings=None, *, convert: bool = True) -> tuple[str, StyleStats]:
    """Apply the prose contract.

    - minor lists are converted to paragraphs
    - a bullet dump raises StyleViolation instead of reaching the PDF
    - in notes mode the text is returned untouched
    """
    style = getattr(settings, "style", "prose") if settings is not None else "prose"
    stats = analyse_style(text)
    if style != "prose" or stats.bullet_lines == 0:
        return text, stats

    if stats.is_severe():
        raise StyleViolation(
            "Il documento e' un elenco, non un saggio: "
            f"{stats.bullet_lines}/{stats.lines} righe di elenco "
            f"({stats.bullet_ratio:.1%}), "
            f"{stats.lists_per_1000_words:.1f} elenchi ogni 1000 parole. "
            "Rigenera con style=prose (map senza sezioni extra) oppure "
            "imposta style=notes se vuoi appunti."
        )

    return (strip_bullet_markup(text) if convert else text), stats
