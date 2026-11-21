#!/usr/bin/env python3
"""
Unified text extraction module for riassunto-libro.

Merges L'Occhio (mega_skill.py) with the format-specific extractors (extract.py).

Functions:
    extract_text(file_path, settings, deep_scan=False, lingua="it") -> (text, num_pages, method)
        Tuple API, kept for compatibility; delegates to extract_document().

    extract_document(file_path, settings, deep_scan=False, lingua="it") -> ExtractionResult
        Main entry point; page-aware (page texts, OCR pages, vision pages).

    _page_quality(text) -> (ok, reason)
        Per-page gate used to route OCR and the vision lane.

    _extract_pdf_result(pdf_path, settings, deep_scan, lingua) -> ExtractionResult
        PDF entry point: cache -> PyMuPDF text layer -> routed OCR -> vision handoff.

    _ocr_pages(doc, page_indices, settings, lingua) -> {page_index: text}
        Batched rendering + parallel Tesseract with DPI escalation.

    load_vision_transcript(pdf_path, settings) -> {page_number: text}
        Reads transcript.json produced by the agent's vision pass.

    _tripla_soglia(testo) -> (is_scan, metrics)
        Detects if text fragment is likely a scan (not native text).

    _estrai_pdftotext(pdf_path, settings) -> (text, num_pages)
        Legacy helper: pdftotext -layout whole document.

    _estrai_pdfplumber(pdf_path) -> (text, num_pages)
        Legacy fallback when PyMuPDF is unavailable.

    _estrai_ocr(pdf_path, settings) -> (text, num_pages)
        Legacy helper: OCR the whole document (--deep-scan callers).

    estrai_metadati(pdf_path) -> (title, author)
        Read PDF metadata for front matter.

    extract_epub(epub_path) -> (text, method)
        Extract EPUB via ebooklib or zipfile fallback.

    extract_docx(docx_path) -> (text, method)
        Extract DOCX via python-docx or zipfile fallback.

    extract_html(html_path) -> (text, method)
        Extract HTML via BeautifulSoup or stdlib parser.

    extract_rtf(rtf_path) -> (text, method)
        Extract RTF via striprtf or regex fallback.
"""

import hashlib
import html
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

# ---------------------------------------------------------------------------
#  Text file reading (encoding fallback chain)
# ---------------------------------------------------------------------------

TEXT_EXTENSIONS = {".txt", ".text", ".md", ".markdown", ".rst", ".adoc", ".asciidoc"}
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
CALIBRE_EBOOK_EXTENSIONS = {".mobi", ".azw", ".azw3"}
SUPPORTED_EXTENSIONS = {
    ".pdf", ".epub", ".docx", ".rtf",
    *TEXT_EXTENSIONS,
    *HTML_EXTENSIONS,
    *CALIBRE_EBOOK_EXTENSIONS,
}


def _read_text_file(path: str) -> Optional[str]:
    """Read a text file trying multiple encodings."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return Path(path).read_text(encoding=encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as exc:
            logger.error("Cannot read {}: {}", path, exc)
            return None
    logger.warning("Could not decode {} with any encoding", path)
    return None


# ---------------------------------------------------------------------------
#  _tripla_soglia — scan detection
# ---------------------------------------------------------------------------

def _tripla_soglia(testo: str) -> tuple[bool, dict]:
    """Verifica se un frammento di testo è probabilmente una scansione.

    Tre metriche:
      (a) parole < 100
      (b) rapporto alfabetico/non-alfabetico < 0.4
      (c) lunghezza media parola < 3.5

    Se ≥2 su 3 → scansione.
    Returns (is_scan, metrics_dict).
    """
    if not testo or not testo.strip():
        return True, {
            "parole": 0,
            "rapporto_alf": 0,
            "media_parola": 0,
            "sotto_soglia": 3,
        }

    parole = [p for p in testo.split() if any(c.isalpha() for c in p)]
    num_parole = len(parole)
    tot_car = len(testo)

    # (a) parole totali < 100
    soglia_a = num_parole < 100

    # (b) rapporto caratteri alfabetici / non-alfabetici < 0.4
    alfabetici = sum(1 for c in testo if c.isalpha())
    non_alfabetici = max(tot_car - alfabetici, 1)
    rapporto_alf = alfabetici / non_alfabetici
    soglia_b = rapporto_alf < 0.4

    # (c) lunghezza media parola < 3.5
    if num_parole > 0:
        media_parola = sum(len(p) for p in parole) / num_parole
    else:
        media_parola = 0
    soglia_c = media_parola < 3.5

    sotto_soglia = sum([soglia_a, soglia_b, soglia_c])
    metrics = {
        "parole": num_parole,
        "rapporto_alf": round(rapporto_alf, 2),
        "media_parola": round(media_parola, 1),
        "sotto_soglia": sotto_soglia,
    }
    return sotto_soglia >= 2, metrics


# ---------------------------------------------------------------------------
#  PDF extraction helpers
# ---------------------------------------------------------------------------

def _estrai_pdftotext(pdf_path: str, settings) -> tuple[str, int]:
    """Extract via pdftotext -layout with page markers (legacy fallback path)."""
    try:
        import fitz  # PyMuPDF

        try:
            doc = fitz.open(pdf_path)
            num_pages = len(doc)
            doc.close()
        except Exception as exc:
            logger.error("PyMuPDF failed to open {}: {}", pdf_path, exc)
            num_pages = 0
    except ImportError:
        num_pages = 0
        logger.warning("PyMuPDF unavailable — page count unknown")

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "full.txt")
        try:
            subprocess.run(
                ["pdftotext", "-layout", pdf_path, out_path],
                timeout=120,
                capture_output=True,
            )
        except FileNotFoundError:
            logger.warning("pdftotext not found — falling back to pdfplumber")
            return _estrai_pdfplumber(pdf_path)
        except subprocess.TimeoutExpired:
            logger.warning("pdftotext timed out — falling back to pdfplumber")
            return _estrai_pdfplumber(pdf_path)

        if os.path.exists(out_path):
            try:
                result = Path(out_path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.error("Cannot read pdftotext output: {}", exc)
                return _estrai_pdfplumber(pdf_path)
            logger.info("Extracted {} chars via pdftotext -layout ({} pp)", len(result), num_pages)
            return result, num_pages

    return _estrai_pdfplumber(pdf_path)


def _estrai_pdfplumber(pdf_path: str) -> tuple[str, int]:
    """Extract layout-aware text with pdfplumber, with page markers."""
    import pdfplumber

    testo: list[str] = []
    num_pages = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            num_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t:
                    testo.append(f"\n\n[PAGINA {i + 1}]\n\n{t}")
    except Exception as exc:
        logger.error("pdfplumber failed on {}: {}", pdf_path, exc)
        return "", 0

    result = "".join(testo)
    logger.info("Extracted {} chars via pdfplumber ({} pp)", len(result), num_pages)
    return result, num_pages


# ---------------------------------------------------------------------------
#  PDF extraction — per-page routing, streaming OCR, vision handoff
# ---------------------------------------------------------------------------

OCR_CACHE_VERSION = 4
PAGE_MIN_ALPHA = 40
PAGE_MARKER = "\n\n[PAGINA {n}]\n\n"


@dataclass
class ExtractionResult:
    """Extraction outcome, page-aware so OCR and vision can be routed per page."""

    text: str = ""
    num_pages: int = 0
    method: str = "failed"
    pages: list[str] = field(default_factory=list)
    ocr_pages: list[int] = field(default_factory=list)
    vision_pages: list[int] = field(default_factory=list)
    vision_dir: Optional[str] = None
    cache_hit: bool = False

    @property
    def vision_manifest(self) -> Optional[str]:
        if self.vision_dir and self.vision_pages:
            manifest = os.path.join(self.vision_dir, "manifest.json")
            if os.path.exists(manifest):
                return manifest
        return None

    @property
    def needs_vision(self) -> bool:
        return bool(self.vision_pages)


def _join_pages(pages: list[str]) -> str:
    """Assemble page texts with the [PAGINA N] markers the chunker expects."""
    return "".join(
        PAGE_MARKER.format(n=i + 1) + (p or "") for i, p in enumerate(pages)
    )


def apply_vision(pages: list[str], transcript: dict[int, str]) -> list[str]:
    """Replace page texts with the vision transcript where available (1-indexed)."""
    merged = list(pages)
    for page, text in transcript.items():
        if 1 <= page <= len(merged) and (text or "").strip():
            merged[page - 1] = text.strip()
    return merged


def _page_quality(text: str) -> tuple[bool, str]:
    """Per-page gate: is this page text usable as book content?

    Deliberately looser than _tripla_soglia, which decides whole-document
    strategy: a two-line chapter title page is legitimate, garbage is not.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False, "empty"
    alpha = sum(1 for c in stripped if c.isalpha())
    parole = [p for p in stripped.split() if any(c.isalpha() for c in p)]
    if not parole:
        return False, "no_words"
    rapporto = alpha / max(len(stripped) - alpha, 1)
    media = sum(len(p) for p in parole) / len(parole)
    if alpha < PAGE_MIN_ALPHA:
        # Sparse page: legitimate when it reads like a few real words (title
        # page, section divider), garbage when it does not.
        if len(parole) >= 2 and media >= 3.5 and rapporto >= 0.6:
            return True, "ok"
        return False, "too_few_letters"
    if rapporto < 0.4 or media < 3.0:
        return False, "garbled"
    return True, "ok"


def _alpha_score(text: str) -> int:
    return sum(1 for c in (text or "") if c.isalpha())


def _page_has_images(page) -> bool:
    try:
        return bool(page.get_images(full=False))
    except Exception:
        return False


def _render_page_gray(page, dpi: int):
    """Render a page straight to 8-bit grayscale, skipping the PNG round-trip."""
    import fitz
    from PIL import Image

    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def _preprocess_gray(img):
    """Contrast normalisation — a few microseconds, helps aged or faint scans."""
    from PIL import ImageOps

    return ImageOps.autocontrast(img, cutoff=1)


def _tesseract_lang(settings, lingua: str = "it") -> str:
    forced = getattr(settings, "ocr_lang", None)
    if forced:
        return forced
    return {"it": "ita", "en": "eng"}.get((lingua or "it").lower(), "ita")


def _tesseract_cmd(settings) -> Optional[str]:
    candidate = getattr(settings, "tesseract_path", None) or r"D:\tesseract\tesseract.exe"
    if candidate and os.path.exists(candidate):
        return candidate
    return shutil.which("tesseract")


def _tesseract_languages(settings) -> set[str]:
    """Languages actually installed. A missing lang used to fail silently."""
    import pytesseract

    cmd = _tesseract_cmd(settings)
    if not cmd:
        return set()
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        return set(pytesseract.get_languages(config=""))
    except Exception as exc:
        logger.warning("Cannot list Tesseract languages: {}", exc)
        return set()


def _pdftotext_exe(settings) -> Optional[str]:
    found = shutil.which("pdftotext")
    if found:
        return found
    poppler = getattr(settings, "poppler_path", None) or r"D:\poppler"
    for candidate in (
        os.path.join(poppler, "pdftotext.exe"),
        os.path.join(poppler, "Library", "bin", "pdftotext.exe"),
        os.path.join(poppler, "bin", "pdftotext.exe"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def _run_tesseract(img, lang: str, psm: int, settings) -> str:
    import pytesseract

    cmd = _tesseract_cmd(settings)
    if not cmd:
        raise RuntimeError("tesseract not found")
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        return pytesseract.image_to_string(img, lang=lang, config=f"--psm {psm}")
    except Exception as exc:
        logger.warning("Tesseract failed: {}", exc)
        return ""


def _ocr_pages(doc, page_indices: list[int], settings, lingua: str = "it") -> dict[int, str]:
    """OCR only the requested pages: batched rendering, parallel OCR, DPI escalation.

    Rendering stays serial (PyMuPDF documents are not thread-safe, and rendering
    is ~20x cheaper than OCR); only Tesseract runs in parallel.
    """
    if not page_indices:
        return {}

    workers = int(getattr(settings, "ocr_workers", 0) or 0) or (os.cpu_count() or 4)
    workers = max(1, min(workers, len(page_indices)))
    dpi = int(getattr(settings, "ocr_dpi", 200) or 200)
    dpi_max = max(dpi, int(getattr(settings, "ocr_dpi_max", 300) or dpi))
    psm = int(getattr(settings, "ocr_psm", 3) or 3)
    preprocess = bool(getattr(settings, "ocr_preprocess", True))
    lang = _tesseract_lang(settings, lingua)

    available = _tesseract_languages(settings)
    if available and lang not in available:
        fallback = "eng" if "eng" in available else None
        if not fallback:
            logger.error(
                "Tesseract has no usable language model (asked '{}', installed: {}). "
                "Install {}.traineddata in the tessdata folder — pages go to vision.",
                lang, ", ".join(sorted(available)) or "none", lang,
            )
            return {}
        logger.warning(
            "Tesseract model '{}' not installed (have: {}) — falling back to 'eng'. "
            "Install {}.traineddata for correct accuracy.",
            lang, ", ".join(sorted(available)), lang,
        )
        lang = fallback

    logger.info(
        "OCR: {} pages, {} workers, {} DPI (lang={}, psm={})",
        len(page_indices), workers, dpi, lang, psm,
    )

    out: dict[int, str] = {}

    def _one(item):
        idx, img = item
        return idx, _run_tesseract(img, lang, psm, settings)

    batch_size = max(workers * 2, 8)
    for start in range(0, len(page_indices), batch_size):
        chunk = page_indices[start:start + batch_size]
        rendered = []
        for idx in chunk:
            try:
                img = _render_page_gray(doc[idx], dpi)
            except Exception as exc:
                logger.warning("Cannot render page {}: {}", idx + 1, exc)
                out[idx] = ""
                continue
            if preprocess:
                img = _preprocess_gray(img)
            rendered.append((idx, img))
        if rendered:
            with ThreadPoolExecutor(max_workers=min(workers, len(rendered))) as pool:
                for idx, txt in pool.map(_one, rendered):
                    out[idx] = txt or ""
        del rendered
        logger.info("  OCR {}/{} pages", min(start + batch_size, len(page_indices)), len(page_indices))

    # Escalation pass: garbage at the base DPI gets one denser attempt.
    if dpi_max > dpi:
        retry = [
            i for i in page_indices
            if i in out and _page_quality(out[i])[1] == "garbled"
        ]
        if retry:
            logger.info("OCR escalation: {} pages at {} DPI", len(retry), dpi_max)
            for idx in retry:
                try:
                    img = _render_page_gray(doc[idx], dpi_max)
                except Exception:
                    continue
                if preprocess:
                    img = _preprocess_gray(img)
                second = _run_tesseract(img, lang, psm, settings)
                if _alpha_score(second) > _alpha_score(out[idx]):
                    out[idx] = second

    return out


# ---------------------------------------------------------------------------
#  Extraction cache
# ---------------------------------------------------------------------------

def _cache_file(pdf_path: str, settings) -> Path:
    root = getattr(settings, "cache_dir", None)
    base = Path(root) if root else Path(pdf_path).parent / ".riassunto-cache"
    st = os.stat(pdf_path)
    key = hashlib.sha1(
        f"{os.path.abspath(pdf_path)}|{st.st_size}|{st.st_mtime_ns}|{OCR_CACHE_VERSION}".encode()
    ).hexdigest()[:16]
    return base / f"{Path(pdf_path).stem}-{key}.json"


def _load_cache(pdf_path: str, settings) -> Optional[dict]:
    if not bool(getattr(settings, "cache_enabled", True)):
        return None
    try:
        path = _cache_file(pdf_path, settings)
    except OSError:
        return None
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Ignoring unreadable cache {}: {}", path.name, exc)
        return None
    if data.get("version") != OCR_CACHE_VERSION or not data.get("pages"):
        return None
    logger.info("Cache hit: {}", path.name)
    return data


def _save_cache(pdf_path: str, settings, pages: list[str], num_pages: int,
                method: str, ocr_pages: list[int]) -> None:
    if not bool(getattr(settings, "cache_enabled", True)):
        return
    try:
        path = _cache_file(pdf_path, settings)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": OCR_CACHE_VERSION,
            "num_pages": num_pages,
            "method": method,
            "ocr_pages": ocr_pages,
            "pages": pages,
        }, ensure_ascii=False), encoding="utf-8")
        logger.info("Cached extraction: {}", path.name)
    except Exception as exc:
        logger.warning("Cannot write cache: {}", exc)


# ---------------------------------------------------------------------------
#  Vision lane — staging for the orchestrating agent
# ---------------------------------------------------------------------------

def _vision_dir(pdf_path: str, settings) -> Path:
    out = Path(getattr(settings, "output_dir", "riassunti") or "riassunti")
    base = out if out.is_absolute() else Path(pdf_path).parent / out
    return base / ".vision" / Path(pdf_path).stem


def load_vision_transcript(pdf_path: str, settings) -> dict[int, str]:
    """Read the page -> text transcript produced by the vision lane, if any."""
    candidates: list[Path] = []
    explicit = getattr(settings, "vision_transcript", None)
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(_vision_dir(pdf_path, settings) / "transcript.json")

    for path in candidates:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Unreadable vision transcript {}: {}", path.name, exc)
            continue
        raw = data.get("pages", data) if isinstance(data, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        out: dict[int, str] = {}
        for key, value in raw.items():
            text = value.get("text") if isinstance(value, dict) else value
            if not isinstance(text, str) or not text.strip():
                continue
            digits = "".join(c for c in str(key) if c.isdigit())
            if not digits:
                continue
            out[int(digits)] = text.strip()
        if out:
            logger.info("Vision transcript: {} pages from {}", len(out), path.name)
            return out
    return {}


def _stage_vision_pages(doc, pdf_path: str, settings,
                        page_indices: list[int]) -> tuple[Optional[str], list[int]]:
    """Render the pages that failed OCR and write a manifest for the agent.

    Python cannot call a vision model, so this stages the images and hands the
    job to the orchestrating agent: page images never enter the pipeline's
    context, only the resulting transcript does.
    """
    cap = int(getattr(settings, "vision_max_pages", 40) or 0)
    selected = page_indices[:cap] if cap > 0 else list(page_indices)
    skipped = len(page_indices) - len(selected)

    vdir = _vision_dir(pdf_path, settings)
    vdir.mkdir(parents=True, exist_ok=True)
    dpi = max(300, int(getattr(settings, "ocr_dpi_max", 300) or 300))

    entries = []
    for idx in selected:
        name = f"page-{idx + 1:04d}.png"
        try:
            _render_page_gray(doc[idx], dpi).save(vdir / name, format="PNG")
        except Exception as exc:
            logger.warning("Cannot stage page {} for vision: {}", idx + 1, exc)
            continue
        entries.append({"page": idx + 1, "image": name})

    if not entries:
        return None, []

    manifest = vdir / "manifest.json"
    manifest.write_text(json.dumps({
        "source": os.path.abspath(pdf_path),
        "title": Path(pdf_path).stem,
        "pages": entries,
        "skipped": skipped,
        "instructions": (
            "Leggi ogni immagine e trascrivi il testo della pagina fedelmente, "
            "senza riassumere. Salva in transcript.json come "
            "{\"pages\": {\"12\": \"testo della pagina 12\"}}."
        ),
        "transcript": str(vdir / "transcript.json"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.warning("VISION_REQUIRED {} pages -> {}", len(entries), manifest)
    return str(manifest), [e["page"] for e in entries]


# ---------------------------------------------------------------------------
#  PDF extraction
# ---------------------------------------------------------------------------

def _pdftotext_pages(pdf_path: str, num_pages: int, settings) -> list[str]:
    """Extract per-page text with pdftotext -layout (recovers column order)."""
    exe = _pdftotext_exe(settings)
    if not exe:
        return []
    timeout = max(120, min(900, num_pages // 2 + 60))
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "full.txt")
        try:
            subprocess.run([exe, "-layout", pdf_path, out], capture_output=True, timeout=timeout)
        except Exception as exc:
            logger.warning("pdftotext failed: {}", exc)
            return []
        try:
            raw = Path(out).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    parts = raw.split("\f")
    if parts and not parts[-1].strip():
        parts.pop()
    return parts


def _pdftotext_wins(pdf_path: str, pages: list[str], settings) -> bool:
    """Probe 3 pages: only pay for pdftotext when it beats PyMuPDF on layout."""
    if not bool(getattr(settings, "pdf_layout_probe", True)):
        return False
    exe = _pdftotext_exe(settings)
    if not exe or len(pages) < 3:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "probe.txt")
        try:
            subprocess.run(
                [exe, "-layout", "-l", "3", pdf_path, out],
                capture_output=True, timeout=60,
            )
            probe = Path(out).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return False
    base = sum(len(p or "") for p in pages[:3])
    return base > 0 and len(probe) > base * 1.15


def _extract_pdf_fresh(doc, pdf_path: str, settings, deep_scan: bool,
                       lingua: str, num_pages: int,
                       transcript: dict[int, str]) -> ExtractionResult:
    pages: list[str] = []
    for i in range(num_pages):
        try:
            pages.append(doc[i].get_text("text") or "")
        except Exception as exc:
            logger.warning("Text extraction failed on page {}: {}", i + 1, exc)
            pages.append("")

    method = "pymupdf"
    if _pdftotext_wins(pdf_path, pages, settings):
        layout_pages = _pdftotext_pages(pdf_path, num_pages, settings)
        if layout_pages:
            for i, txt in enumerate(layout_pages[:num_pages]):
                if txt and (len(txt) > len(pages[i]) or not _page_quality(pages[i])[0]):
                    pages[i] = txt
            method = "pdftotext-layout"
            logger.info("Layout: pdftotext -layout used for {} pages", num_pages)

    # Per-page routing: only pages without a usable text layer go to OCR.
    need: list[int] = []
    for i in range(num_pages):
        if _page_quality(pages[i])[0]:
            continue
        if deep_scan or _page_has_images(doc[i]):
            need.append(i)

    covered = {p - 1 for p in transcript}
    if covered:
        before = len(need)
        need = [i for i in need if i not in covered]
        if before != len(need):
            logger.info("Vision transcript already covers {} OCR pages", before - len(need))

    ocr_pages: list[int] = []
    vision_pages: list[int] = []
    vision_first = bool(getattr(settings, "vision_first", False))
    vision_first_cap = int(getattr(settings, "vision_first_max_pages", 30) or 30)

    if vision_first and num_pages <= vision_first_cap and not covered and need:
        logger.info("--vision-first: {} pages staged for the vision lane", num_pages)
        _, staged = _stage_vision_pages(doc, pdf_path, settings, list(range(num_pages)))
        vision_pages = staged

    if need:
        if _tesseract_cmd(settings) is None:
            logger.warning("Tesseract not found — {} pages go straight to vision", len(need))
            vision_pages = vision_pages or need
        else:
            ocr_text = _ocr_pages(doc, need, settings, lingua)
            ocr_pages = sorted(i + 1 for i in ocr_text)   # 1-based, as reported to users
            for i, txt in ocr_text.items():
                if (txt or "").strip() and _alpha_score(txt) >= _alpha_score(pages[i]):
                    pages[i] = txt
            failed = [i for i in need if not _page_quality(pages[i])[0]]
            if failed:
                if bool(getattr(settings, "vision_enabled", True)):
                    vision_pages = sorted(set(vision_pages) | set(failed))
                else:
                    logger.warning("{} pages still unreadable after OCR", len(failed))
            method = "ocr" if len(need) == num_pages else f"{method}+ocr"

    manifest, staged = (None, vision_pages)
    if vision_pages and bool(getattr(settings, "vision_enabled", True)):
        manifest, staged = _stage_vision_pages(doc, pdf_path, settings, vision_pages)

    return ExtractionResult(
        text=_join_pages(pages),
        num_pages=num_pages,
        method=method,
        pages=pages,
        ocr_pages=ocr_pages,
        vision_pages=staged if manifest else [],
        vision_dir=str(_vision_dir(pdf_path, settings)) if manifest else None,
    )


def _extract_pdf_result(pdf_path: str, settings, deep_scan: bool = False,
                        lingua: str = "it") -> ExtractionResult:
    """PDF entry point: cache → text layer → routed OCR → vision handoff."""
    logger.info("Analisi: {}", os.path.basename(pdf_path))
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF missing — falling back to pdftotext/pdfplumber")
        text, num_pages = _estrai_pdftotext(pdf_path, settings)
        if not text.strip():
            text, num_pages = _estrai_pdfplumber(pdf_path)
        return ExtractionResult(text=text, num_pages=num_pages, method="pdftotext")

    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        logger.error("Cannot open PDF {}: {}", pdf_path, exc)
        return ExtractionResult(method="error")

    try:
        num_pages = len(doc)
        if num_pages == 0:
            logger.error("PDF has no pages: {}", pdf_path)
            return ExtractionResult(method="error")

        transcript = load_vision_transcript(pdf_path, settings)
        cached = _load_cache(pdf_path, settings)

        if cached and int(cached.get("num_pages", 0)) == num_pages:
            pages = [p or "" for p in cached["pages"]][:num_pages]
            pages += [""] * (num_pages - len(pages))
            result = ExtractionResult(
                num_pages=num_pages,
                method=str(cached.get("method", "cache")),
                pages=pages,
                ocr_pages=list(cached.get("ocr_pages", [])),
                cache_hit=True,
            )
        else:
            result = _extract_pdf_fresh(
                doc, pdf_path, settings, deep_scan, lingua, num_pages, transcript
            )
            _save_cache(
                pdf_path, settings, result.pages, num_pages,
                result.method, result.ocr_pages,
            )

        if transcript:
            result.pages = apply_vision(result.pages, transcript)
            if "+vision" not in result.method:
                result.method = f"{result.method}+vision"
            result.vision_pages = []
            result.vision_dir = None
        elif result.cache_hit and bool(getattr(settings, "vision_enabled", True)):
            # A cached run must still re-stage pages that stayed unreadable,
            # otherwise the handoff is lost on every re-run.
            unreadable = [
                i for i in range(num_pages)
                if not _page_quality(result.pages[i])[0]
                and (i + 1 in result.ocr_pages or _page_has_images(doc[i]))
            ]
            if unreadable:
                manifest, staged = _stage_vision_pages(doc, pdf_path, settings, unreadable)
                if manifest:
                    result.vision_pages = staged
                    result.vision_dir = str(_vision_dir(pdf_path, settings))

        result.text = _join_pages(result.pages)
        logger.info(
            "Extracted {} chars via {} ({} pp, {} OCR, {} vision)",
            len(result.text), result.method, result.num_pages,
            len(result.ocr_pages), len(result.vision_pages),
        )
        return result
    finally:
        doc.close()


def _estrai_ocr(pdf_path: str, settings) -> tuple[str, int]:
    """Legacy entry point: OCR the whole document (used by --deep-scan callers)."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        indices = list(range(len(doc)))
        texts = _ocr_pages(doc, indices, settings)
        pages = [texts.get(i, "") for i in indices]
    finally:
        doc.close()
    return _join_pages(pages), len(pages)


# ---------------------------------------------------------------------------
#  Metadata extraction
# ---------------------------------------------------------------------------

def estrai_metadati(pdf_path: str) -> tuple[str, str]:
    """Read PDF metadata for front matter. Returns (title, author)."""
    name = Path(pdf_path).name
    if Path(pdf_path).suffix.lower() != ".pdf":
        return name, "Autore sconosciuto"

    from pypdf import PdfReader

    try:
        reader = PdfReader(pdf_path)
        meta = reader.metadata
        titolo = meta.title if meta and meta.title else name
        autore = meta.author if meta and meta.author else "Autore sconosciuto"
        return titolo, autore
    except Exception as exc:
        logger.warning("No metadata in {}: {}", Path(pdf_path).name, exc)
        return name, "Autore sconosciuto"


# ---------------------------------------------------------------------------
#  EPUB extraction
# ---------------------------------------------------------------------------

def _extract_with_ebooklib(epub_path: str) -> Optional[str]:
    """Extract EPUB via ebooklib + BeautifulSoup."""
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(epub_path)
        parts: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            parts.append(soup.get_text(separator="\n"))
        return "\n\n".join(parts)
    except ImportError:
        return None
    except Exception as exc:
        logger.error("ebooklib extraction failed: {}", exc)
        return None


def _extract_epub_with_zipfile(epub_path: str) -> Optional[str]:
    """stdlib-only EPUB extractor: unzip → parse HTML files."""
    try:
        with zipfile.ZipFile(epub_path) as zf:
            names = zf.namelist()
            # Read OPF spine to get reading order
            spine_order: list[str] = []
            opf_files = [n for n in names if n.endswith(".opf")]
            if opf_files:
                opf_text = zf.read(opf_files[0]).decode("utf-8", errors="replace")
                spine_order = re.findall(
                    r'href=["\']([^"\']+\.(?:xhtml|html))["\']', opf_text
                )

            html_files = spine_order or sorted(
                n for n in names if n.endswith((".html", ".xhtml"))
            )
            if not html_files:
                return None

            parts: list[str] = []
            for name in html_files:
                try:
                    raw = zf.read(name).decode("utf-8", errors="replace")
                    parser = _HTMLTextExtractor()
                    parser.feed(raw)
                    parts.append(parser.get_text())
                except Exception as exc:
                    logger.warning("Skipping {} in EPUB: {}", name, exc)
                    continue
            return "\n\n".join(parts) if parts else None
    except Exception as exc:
        logger.error("ZIP-based EPUB extraction failed: {}", exc)
        return None


def extract_epub(epub_path: str) -> tuple[str, str]:
    """Return (text, method) for an EPUB file."""
    logger.info("Trying ebooklib + BeautifulSoup4...")
    text = _extract_with_ebooklib(epub_path)
    if text and text.strip():
        logger.info("EPUB extracted via ebooklib ({} chars)", len(text))
        return text, "ebooklib"

    logger.info("ebooklib not available, trying stdlib zipfile parser...")
    text = _extract_epub_with_zipfile(epub_path)
    if text and text.strip():
        logger.info("EPUB extracted via zipfile ({} chars)", len(text))
        return text, "zipfile"

    logger.error("Could not extract text from EPUB")
    return "", "failed"


# ---------------------------------------------------------------------------
#  DOCX extraction
# ---------------------------------------------------------------------------

def _extract_docx_with_python_docx(docx_path: str) -> Optional[str]:
    """Extract DOCX via python-docx."""
    try:
        import docx

        document = docx.Document(docx_path)
        parts: list[str] = [p.text for p in document.paragraphs if p.text]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append("\t".join(cells))
        return "\n".join(parts)
    except ImportError:
        return None
    except Exception as exc:
        logger.error("python-docx extraction failed: {}", exc)
        return None


def _extract_docx_with_zipfile(docx_path: str) -> Optional[str]:
    """Extract DOCX via stdlib ZIP/XML parsing."""
    try:
        import xml.etree.ElementTree as ET

        with zipfile.ZipFile(docx_path) as zf:
            xml_bytes = zf.read("word/document.xml")
        root = ET.fromstring(xml_bytes)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        parts: list[str] = []
        for paragraph in root.iter(f"{namespace}p"):
            texts = [
                node.text
                for node in paragraph.iter(f"{namespace}t")
                if node.text
            ]
            if texts:
                parts.append("".join(texts))
        return "\n".join(parts) if parts else None
    except Exception as exc:
        logger.error("ZIP-based DOCX extraction failed: {}", exc)
        return None


def extract_docx(docx_path: str) -> tuple[str, str]:
    """Return (text, method) for a DOCX file."""
    logger.info("Trying python-docx...")
    text = _extract_docx_with_python_docx(docx_path)
    if text and text.strip():
        logger.info("DOCX extracted via python-docx ({} chars)", len(text))
        return text, "python-docx"

    logger.info("python-docx not available, trying stdlib DOCX parser...")
    text = _extract_docx_with_zipfile(docx_path)
    if text and text.strip():
        logger.info("DOCX extracted via zipfile ({} chars)", len(text))
        return text, "zipfile-docx"

    logger.error("Could not extract text from DOCX")
    return "", "failed"


# ---------------------------------------------------------------------------
#  HTML extraction
# ---------------------------------------------------------------------------

class _HTMLTextExtractor(html.parser.HTMLParser):
    """Minimal HTML → plain text converter using stdlib only."""

    SKIP_TAGS = {"script", "style", "head"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in ("p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "div"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        return html.unescape("".join(self._parts))


def _extract_html_content(raw_html: str) -> str:
    """Convert HTML string to plain text."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_html, "html.parser")
        for element in soup(["script", "style", "head"]):
            element.decompose()
        return soup.get_text(separator="\n")
    except ImportError:
        parser = _HTMLTextExtractor()
        parser.feed(raw_html)
        return parser.get_text()


def extract_html(html_path: str) -> tuple[str, str]:
    """Return (text, method) for an HTML file."""
    raw = _read_text_file(html_path)
    if raw is None:
        logger.error("Could not read HTML file: {}", html_path)
        return "", "failed"

    # Determine which method will be used
    try:
        import bs4  # noqa: F401
        method = "beautifulsoup"
    except ImportError:
        method = "stdlib"

    text = _extract_html_content(raw)
    if text.strip():
        logger.info("HTML extracted via {} ({} chars)", method, len(text))
        return text, method

    logger.error("Could not extract text from HTML")
    return "", "failed"


# ---------------------------------------------------------------------------
#  RTF extraction
# ---------------------------------------------------------------------------

def _strip_rtf_fallback(raw: str) -> str:
    """Basic regex-based RTF cleanup."""
    raw = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)
    raw = re.sub(r"\\par[d]?", "\n", raw)
    raw = re.sub(r"\\tab", "\t", raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", raw)
    raw = raw.replace("{", "").replace("}", "")
    return html.unescape(raw)


def extract_rtf(rtf_path: str) -> tuple[str, str]:
    """Return (text, method) for an RTF file."""
    raw = _read_text_file(rtf_path)
    if raw is None:
        logger.error("Could not read RTF file: {}", rtf_path)
        return "", "failed"

    try:
        from striprtf.striprtf import rtf_to_text

        text = rtf_to_text(raw)
        if text.strip():
            logger.info("RTF extracted via striprtf ({} chars)", len(text))
            return text, "striprtf"
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("striprtf failed: {}", exc)

    text = _strip_rtf_fallback(raw)
    logger.info("RTF extracted via regex fallback ({} chars)", len(text))
    return text, "rtf-regex"


# ---------------------------------------------------------------------------
#  Plain text / Markdown / reStructuredText / AsciiDoc
# ---------------------------------------------------------------------------

def _extract_plain_text(file_path: str) -> tuple[str, str]:
    """Read plain text files with encoding fallback."""
    text = _read_text_file(file_path)
    if text is None:
        logger.error("Could not read text file: {}", file_path)
        return "", "failed"
    return text, "plain-text"


# ---------------------------------------------------------------------------
#  Calibre ebook-convert fallback
# ---------------------------------------------------------------------------

def _extract_with_ebook_convert(input_path: str, settings) -> Optional[str]:
    """Try Calibre's ebook-convert as a fallback for unsupported formats."""
    if not shutil.which("ebook-convert"):
        return None

    output_dir = Path(getattr(settings, "output_dir", tempfile.gettempdir()))
    output_path = output_dir / "ebook-convert-output.txt"
    try:
        result = subprocess.run(
            ["ebook-convert", input_path, str(output_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0 and output_path.exists():
            text = output_path.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                return text
    except subprocess.TimeoutExpired:
        logger.warning("ebook-convert timed out for {}", input_path)
    except Exception as exc:
        logger.warning("ebook-convert failed: {}", exc)
    return None


# ---------------------------------------------------------------------------
#  Main entry point
# ---------------------------------------------------------------------------

def extract_document(
    file_path: str,
    settings,
    deep_scan: bool = False,
    lingua: str = "it",
) -> ExtractionResult:
    """Extract a document, page-aware where the format allows it.

    Unlike extract_text(), this returns the full ExtractionResult: page texts,
    which pages went through OCR, and which pages the vision lane should read.
    """
    path = Path(file_path)
    if not path.exists():
        logger.error("File not found: {}", file_path)
        return ExtractionResult(method="failed")

    ext = path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf_result(str(path), settings, deep_scan=deep_scan, lingua=lingua)

    text, method = "", "failed"
    if ext == ".epub":
        text, method = extract_epub(str(path))
    elif ext == ".docx":
        text, method = extract_docx(str(path))
    elif ext in HTML_EXTENSIONS:
        text, method = extract_html(str(path))
    elif ext == ".rtf":
        text, method = extract_rtf(str(path))
    elif ext in TEXT_EXTENSIONS:
        text, method = _extract_plain_text(str(path))
    elif ext in CALIBRE_EBOOK_EXTENSIONS:
        logger.info("Trying ebook-convert for {}...", ext)
        converted = _extract_with_ebook_convert(str(path), settings)
        text, method = (converted, "ebook-convert") if converted else ("", "failed")
        if not converted:
            logger.error("Could not extract {}: no Calibre or conversion failed", ext)
    else:
        logger.error("Unsupported file extension: {}", ext)

    return ExtractionResult(text=text, num_pages=0, method=method)


def extract_text(
    file_path: str,
    settings,
    deep_scan: bool = False,
    lingua: str = "it",
) -> tuple[str, int, str]:
    """Extract text from a document file.

    Returns:
        (text, num_pages, method). Methods include 'pymupdf',
        'pdftotext-layout', 'ocr', 'pymupdf+ocr', '*+vision', 'ebooklib',
        'zipfile', 'python-docx', 'zipfile-docx', 'beautifulsoup', 'stdlib',
        'striprtf', 'rtf-regex', 'plain-text', 'ebook-convert', 'failed'.
    """
    result = extract_document(file_path, settings, deep_scan=deep_scan, lingua=lingua)
    return result.text, result.num_pages, result.method
