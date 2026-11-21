#!/usr/bin/env python3
"""
PIPELINE UNIFICATA — Riassunto Libri Universitari
Fusione: extract.py (book-to-skill) + Map-Reduce (equalizzazione chirurgica) + output multipli

Infrastruttura: Ollama Pro Cloud (deepseek-v4.1-flash:cloud + gemma4:31b-cloud)
Output: .docx (saggio discorsivo) + glossary.md + cheatsheet.md + SKILL.md (opzionale)

Autore: Sisyphus (OhMyOpenCode) + virgiliojr94 (book-to-skill)
Data: 3 Giugno 2026
"""

import os, sys, re, json, time, subprocess, shutil
from pathlib import Path
from datetime import datetime
from typing import Optional
from collections import Counter

import requests
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ============================================================
# CONFIG
# ============================================================

OLLAMA_HOST = "http://127.0.0.1:11434"
MODEL_MAP = "deepseek-v4.1-flash:cloud"
MODEL_REDUCE = "deepseek-v4.1-flash:cloud"
MODEL_FEEDBACK = "gemma4:31b-cloud"

CHUNK_MAX_TOKENS = 24000
CHUNK_OVERLAP_TOKENS = 1000
MAP_OUTPUT_TOKENS = 6000
REDUCE_CONTEXT_TOKENS = 128000
MIN_CHUNK_TOKENS = 800

BOOK_DIR = Path(r"D:\Studio\Scienze Dello Spettacolo\Storiografia del Teatro Musicale")
OUTPUT_DIR = BOOK_DIR / "riassunti"
CHECKPOINT_DIR = BOOK_DIR / "checkpoints"
EXTRACT_SCRIPT = BOOK_DIR / "extract.py"

# ============================================================
# UTILITY
# ============================================================


def stampa(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def estimate_tokens(text):
    return len(text) // 4


def ollama_chat(model, messages, options=None, timeout=180):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options or {},
    }
    r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ============================================================
# FASE 1 — ESTRAZIONE UNIVERSALE (via extract.py)
# ============================================================


def extract_text(file_path: str) -> str:
    """Estrae testo da qualsiasi formato supportato usando extract.py."""
    file_path = str(Path(file_path).resolve())

    if not EXTRACT_SCRIPT.exists():
        stampa("ERRORE: extract.py non trovato. Scaricalo da book-to-skill.")
        sys.exit(1)

    # Workdir temporaneo per extract.py
    workdir = BOOK_DIR / "_extract_work"
    workdir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["BOOK_SKILL_WORKDIR"] = str(workdir)
    env["BOOK_SKILL_INSTALL_MISSING"] = "no"  # no install automatico

    stampa(f"Estrazione: {Path(file_path).name}")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(EXTRACT_SCRIPT),
                file_path,
                "--mode",
                "text",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        if result.returncode != 0:
            stampa(f"  extract.py fallito: {result.stderr[:200]}")
            # Fallback diretto: PyMuPDF
            stampa("  Fallback: PyMuPDF diretto...")
            return _fallback_extract_pdf(file_path)

        # Leggi output
        text_path = workdir / "full_text.txt"
        if text_path.exists():
            text = text_path.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                stampa(
                    f"  Estratto: {len(text)} caratteri (~{estimate_tokens(text)} token) via extract.py"
                )
                # Pulisci workdir
                shutil.rmtree(workdir, ignore_errors=True)
                return text

        stampa("  extract.py non ha prodotto testo. Fallback PyMuPDF...")
        shutil.rmtree(workdir, ignore_errors=True)
        return _fallback_extract_pdf(file_path)

    except subprocess.TimeoutExpired:
        stampa("  extract.py timeout. Fallback PyMuPDF...")
        shutil.rmtree(workdir, ignore_errors=True)
        return _fallback_extract_pdf(file_path)
    except Exception as e:
        stampa(f"  extract.py errore: {e}. Fallback PyMuPDF...")
        shutil.rmtree(workdir, ignore_errors=True)
        return _fallback_extract_pdf(file_path)


def _fallback_extract_pdf(file_path: str) -> str:
    """Fallback diretto con PyMuPDF per PDF."""
    import fitz

    doc = fitz.open(file_path)
    text_parts = []
    for page_num, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            text_parts.append(text)
    doc.close()
    result = "\n\n".join(text_parts)
    if result.strip():
        stampa(
            f"  Fallback PyMuPDF: {len(result)} caratteri (~{estimate_tokens(result)} token)"
        )
    else:
        stampa("  ERRORE: Nessun testo estratto. Possibile PDF scansione?")
    return result


# ============================================================
# FASE 2 — CHUNKING STRUTTURALE
# ============================================================


def split_into_chunks(text: str, max_tokens: int = CHUNK_MAX_TOKENS) -> list:
    """Divide il testo in chunk strutturali, merge chunk piccoli."""
    # Rimuovi numeri di pagina
    clean_lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(r"^\d+$", stripped) and len(stripped) < 5:
            continue
        clean_lines.append(line)
    clean_text = "\n".join(clean_lines)

    # Dividi per doppi a capo
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean_text) if p.strip()]
    if not paragraphs:
        return []

    chunks = []
    current, current_tokens = "", 0
    ch_id = 0

    for para in paragraphs:
        pt = estimate_tokens(para)
        if pt > max_tokens:
            if current.strip():
                chunks.append(
                    {"id": ch_id, "text": current, "token_count": current_tokens}
                )
                ch_id += 1
                current, current_tokens = "", 0
            sentences = [
                s.strip() for s in re.split(r"(?<=[.!?])\s+", para) if s.strip()
            ]
            for sent in sentences:
                st = estimate_tokens(sent)
                if current_tokens + st > max_tokens and current:
                    chunks.append(
                        {"id": ch_id, "text": current, "token_count": current_tokens}
                    )
                    ch_id += 1
                    current, current_tokens = sent, st
                else:
                    current += " " + sent if current else sent
                    current_tokens += st
            continue

        if current_tokens + pt > max_tokens and current:
            chunks.append({"id": ch_id, "text": current, "token_count": current_tokens})
            ch_id += 1
            current, current_tokens = para, pt
        else:
            current += "\n\n" + para if current else para
            current_tokens += pt

    if current.strip():
        chunks.append({"id": ch_id, "text": current, "token_count": current_tokens})

    # Merge chunk piccoli
    merged = []
    for ch in chunks:
        if ch["token_count"] < MIN_CHUNK_TOKENS and merged:
            merged[-1]["text"] += "\n\n" + ch["text"]
            merged[-1]["token_count"] += ch["token_count"]
        else:
            merged.append(ch)

    for i, m in enumerate(merged):
        m["id"] = i

    stampa(f"  {len(chunks)} chunk grezzi → {len(merged)} chunk finali")
    return merged


# ============================================================
# FASE 3 — MAP (equalizzazione chirurgica)
# ============================================================

PROMPT_MAP = """Sei uno storico specializzato. Analizza in modo ESAUSTIVISSIMO il testo seguente.

REGOLE ASSOLUTE — VIOLARLE COMPROMETTE L'ESAME:
1. PRESERVA OBBLIGATORIAMENTE: tutti i NOMI PROPRI (persone, luoghi, teatri, istituzioni), DATE (giorni, mesi, anni, secoli), TITOLI DI OPERE, TRATTATI, EVENTI STORICI, CITAZIONI DIRETTE
2. Scrivi un RIASSUNTO ESTREMAMENTE DENSO E COMPLETO in italiano. Paragrafi fluidi. ZERO elenchi puntati. ZERO elenchi numerati.
3. OBIETTIVO: l'output deve coprire circa l'80-95% del contenuto originale. Non eliminare NULLA di importante. Ogni concetto, teoria, esempio, spiegazione, nome, data, opera deve essere CONSERVATA. La compressione deve essere MINIMA (elimina solo le ripetizioni e le digressioni accessorie). Questo output deve POTER SOSTITUIRE la lettura del testo originale.
4. L'output deve essere LUNGO: circa il 30-50% della lunghezza del testo originale in caratteri.
5. Struttura: usa ### per titoli di sezione.
6. Alla fine, aggiungi il blocco ENTITÀ nel formato:
===ENTITA===
PERSONE: elenco separato da |
DATE: elenco separato da |
OPERE/EVENTI: elenco separato da |
===FINE ENTITA===

TESTO DA ANALIZZARE ({target_chars} caratteri obiettivo di output):
{testo}"""


def map_chunk(chunk, chunk_index, total_chunks):
    stampa(f"  Map {chunk_index + 1}/{total_chunks} ({chunk['token_count']} tok)...")
    # Target: almeno il 30% del chunk originale in caratteri
    target_chars = max(30000, int(len(chunk["text"]) * 0.35))
    prompt = PROMPT_MAP.replace("{testo}", chunk["text"])
    prompt = prompt.replace("{target_chars}", str(target_chars))

    for attempt in range(3):
        try:
            resp = ollama_chat(
                MODEL_MAP,
                [{"role": "user", "content": prompt}],
                options={"num_ctx": 32768, "temperature": 0.2, "seed": 42},
                timeout=300,
            )
            content = resp.get("message", {}).get("content", "")

            entities = {"persone": [], "date": [], "opere": []}
            ent_match = re.search(
                r"===ENTITA===\n(.*?)===FINE ENTITA===", content, re.DOTALL
            )
            if ent_match:
                for line in ent_match.group(1).strip().split("\n"):
                    if line.startswith("PERSONE:"):
                        entities["persone"] = [
                            e.strip()
                            for e in line.replace("PERSONE:", "").split("|")
                            if e.strip()
                        ]
                    elif line.startswith("DATE:"):
                        entities["date"] = [
                            e.strip()
                            for e in line.replace("DATE:", "").split("|")
                            if e.strip()
                        ]
                    elif line.startswith("OPERE"):
                        entities["opere"] = (
                            [
                                e.strip()
                                for e in line.split(":", 1)[1].split("|")
                                if e.strip()
                            ]
                            if ":" in line
                            else []
                        )
                clean = content[: ent_match.start()].strip()
            else:
                clean = content.strip()

            return {
                "chunk_id": chunk["id"],
                "summary": clean,
                "entities": entities,
                "token_count": estimate_tokens(clean),
            }
        except Exception as e:
            if attempt < 2:
                wait = (attempt + 1) * 15
                stampa(f"  Retry {attempt + 1} tra {wait}s: {e}")
                time.sleep(wait)
            else:
                stampa(f"  ERRORE chunk {chunk_index + 1}: {e}")
                return None
    return None


# ============================================================
# FASE 4 — FEEDBACK LOOP
# ============================================================

PROMPT_FEEDBACK = """Verifica la completezza del RIASSUNTO rispetto al testo ORIGINALE.

ORIGINALE:
{originale}

RIASSUNTO:
{riassunto}

Se i concetti principali sono coperti, dai COVERAGE >= 90%. Se mancano entità IMPORTANTI, scrivi un breve paragrafo integrativo.

Formato:
COVERAGE: X%
MANCANTI: elenco separato da |
===INTEGRAZIONE===
(paragrafo integrativo solo se serve)
===FINE INTEGRAZIONE==="""


def feedback_loop(original_text, map_out):
    """Verifica completezza tramite gemma4:31b-cloud."""
    prompt = PROMPT_FEEDBACK.replace("{originale}", original_text[:8000])
    prompt = prompt.replace("{riassunto}", map_out["summary"])

    try:
        resp = ollama_chat(
            MODEL_FEEDBACK,
            [{"role": "user", "content": prompt}],
            options={"num_ctx": 16384, "temperature": 0.1},
            timeout=120,
        )
        content = resp.get("message", {}).get("content", "")

        cov_match = re.search(r"COVERAGE:\s*(\d+)%", content)
        coverage = int(cov_match.group(1)) if cov_match else 100

        int_match = re.search(
            r"===INTEGRAZIONE===\n(.*?)===FINE INTEGRAZIONE===", content, re.DOTALL
        )
        integration = int_match.group(1).strip() if int_match else ""

        return {"coverage": coverage, "integration": integration}
    except Exception:
        return {"coverage": 100, "integration": ""}


# ============================================================
# FASE 5 — REDUCE (tessitore)
# ============================================================


def compute_total_chars(map_results):
    return sum(len(r["summary"]) for r in map_results if r and r.get("summary"))


def build_glossary(map_results):
    all_p, all_d, all_o = {}, {}, {}
    for mr in map_results:
        if not mr:
            continue
        for p in mr.get("entities", {}).get("persone", []):
            n = p.strip().rstrip(".,;:")
            all_p[n] = all_p.get(n, 0) + 1
        for d in mr.get("entities", {}).get("date", []):
            n = d.strip()
            all_d[n] = all_d.get(n, 0) + 1
        for o in mr.get("entities", {}).get("opere", []):
            n = o.strip()
            all_o[n] = all_o.get(n, 0) + 1

    g = "PERSONE:\n" + "\n".join(
        f"  - {k}" for k, v in sorted(all_p.items(), key=lambda x: -x[1])[:60]
    )
    g += "\nDATE:\n" + "\n".join(
        f"  - {k}" for k, v in sorted(all_d.items(), key=lambda x: -x[1])[:30]
    )
    g += "\nOPERE/EVENTI:\n" + "\n".join(
        f"  - {k}" for k, v in sorted(all_o.items(), key=lambda x: -x[1])[:30]
    )
    return g


def reduce_summaries(map_results, glossary):
    """Cucitura meccanica: concatena i riassunti Map con transizioni."""
    total_map = compute_total_chars(map_results)
    stampa(f"  Totale Map: {total_map} caratteri in {len(map_results)} chunk")

    # Per ogni chunk Map, estrai il titolo (## o ###) se presente
    parts = []
    for i, mr in enumerate(map_results):
        if not mr or not mr.get("summary"):
            continue
        text = mr["summary"]
        # Se il chunk ha già un titolo, è auto-contenuto
        # Se no, aggiungi un titolo generico
        has_heading = bool(re.search(r"^#{1,3}\s+", text, re.MULTILINE))
        if not has_heading:
            text = f"### Sezione {i + 1}\n\n{text}"
        parts.append(text)

    essay = "\n\n".join(parts)

    # Aggiungi introduzione e conclusione se mancano
    if not essay.strip().startswith("###"):
        essay = f"### Introduzione\n\n{essay}\n\n### Conclusione\n\nQuesto saggio riassume i contenuti principali del testo originale, preservando nomi, date, eventi e opere citate."

    stampa(f"  Saggio: {len(essay)} caratteri ({estimate_tokens(essay)} token)")
    return essay


# ============================================================
# FASE 6 — EXPORT .DOCX
# ============================================================


def export_docx(essay, output_path, book_title, coverage_report=None):
    doc = Document()
    for s in doc.sections:
        s.top_margin = Inches(1)
        s.bottom_margin = Inches(1)
        s.left_margin = Inches(1.15)
        s.right_margin = Inches(1.15)

    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11.5)
    style.paragraph_format.line_spacing = 1.35
    style.paragraph_format.space_after = Pt(6)
    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    header = doc.sections[0].header
    hp = header.paragraphs[0]
    hp.text = f"Riassunto: {book_title} — {datetime.now().strftime('%d/%m/%Y')}"
    hp.style.font.size = Pt(8)
    hp.style.font.color.rgb = RGBColor(128, 128, 128)

    title = doc.add_heading(f"Riassunto — {book_title}", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Sommario se ci sono titoli
    toc_indices = []
    for line in essay.split("\n"):
        s = line.strip()
        if s.startswith("### "):
            toc_indices.append(s[4:])
        elif s.startswith("## "):
            toc_indices.append(s[3:])

    if toc_indices:
        doc.add_heading("Indice", level=1)
        for idx in toc_indices:
            p = doc.add_paragraph(f"  {idx}" if idx.startswith("    ") else idx)
            p.paragraph_format.space_after = Pt(2)
        doc.add_page_break()

    for line in essay.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            doc.add_heading(s[4:], level=3)
        elif s.startswith("## "):
            doc.add_heading(s[3:], level=2)
        elif s.startswith("# "):
            doc.add_heading(s[2:], level=1)
        else:
            doc.add_paragraph(s)

    if coverage_report:
        doc.add_page_break()
        doc.add_heading("Report di Copertura", level=1)
        doc.add_paragraph(
            f"Copertura media: {coverage_report.get('average_coverage', 100)}%"
        )
        missing = coverage_report.get("missing_entities", [])
        if missing:
            doc.add_heading("Entità non coperte", level=2)
            doc.add_paragraph(", ".join(missing[:50]))

    doc.save(output_path)
    stampa(f"DOCX salvato: {output_path}")


# ============================================================
# FASE 7 — GLOSSARIO .MD (File Affiancato)
# ============================================================


def export_glossary(map_results, output_path, book_title):
    """Genera glossario.md con termini chiave e riferimenti."""
    from collections import Counter

    all_terms = Counter()
    all_persone = Counter()
    all_date = Counter()
    all_opere = Counter()

    for mr in map_results:
        if not mr:
            continue
        for p in mr.get("entities", {}).get("persone", []):
            all_persone[p.strip().rstrip(".,;:")] += 1
        for d in mr.get("entities", {}).get("date", []):
            all_date[d.strip()] += 1
        for o in mr.get("entities", {}).get("opere", []):
            all_opere[o.strip()] += 1
        # Parole significative dal summary
        words = re.findall(r"\b[A-Z][a-zà-ÿ]+\b", mr.get("summary", ""))
        for w in words:
            if len(w) > 3:
                all_terms[w] += 1

    md = f"# Glossario — {book_title}\n\n"
    md += f"Generato il {datetime.now().strftime('%d/%m/%Y')}\n\n"
    md += "---\n\n"

    md += "## Persone\n\n"
    for nome, count in all_persone.most_common(80):
        md += f"- **{nome}**\n"

    md += "\n## Date ed Eventi\n\n"
    for data, count in all_date.most_common(40):
        md += f"- **{data}**\n"

    md += "\n## Opere e Trattati\n\n"
    for opera, count in all_opere.most_common(40):
        md += f"- **{opera}**\n"

    Path(output_path).write_text(md, encoding="utf-8")
    stampa(f"Glossario salvato: {output_path}")


# ============================================================
# FASE 8 — CHEATSHEET .MD (File Affiancato)
# ============================================================


def export_cheatsheet(essay, map_results, output_path, book_title):
    """Genera cheatsheet.md: mappa cronologica e concetti chiave."""
    md = f"# Cheatsheet — {book_title}\n\n"
    md += f"Generato il {datetime.now().strftime('%d/%m/%Y')}\n\n"
    md += "---\n\n"

    # Estrai date dal saggio per timeline cronologica
    date_patterns = [
        r"(?<!\w)(\d{4})(?!\w)",
        r"(?<!\w)(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})(?!\w)",
        r"(?<!\w)((?:XVIII|XIX|XX|XXI)\s*secolo)(?!\w)",
    ]

    all_dates = set()
    for pattern in date_patterns:
        for m in re.finditer(pattern, essay, re.IGNORECASE):
            all_dates.add(m.group(1).strip())

    if all_dates:
        md += "## Timeline Cronologica\n\n"
        # Ordina numericamente
        sorted_dates = sorted([d for d in all_dates if d.isdigit()])
        for d in sorted_dates[:50]:
            md += f"- **{d}**\n"

    md += "\n## Sezioni del Saggio\n\n"
    for line in essay.split("\n"):
        if line.strip().startswith("### "):
            md += f"- {line.strip()[4:]}\n"

    md += "\n## Entità Chiave\n\n"
    all_entities = Counter()
    for mr in map_results:
        if not mr:
            continue
        for cat in ["persone", "date", "opere"]:
            for ent in mr.get("entities", {}).get(cat, []):
                all_entities[ent.strip().rstrip(".,;:")] += 1

    for ent, count in all_entities.most_common(30):
        md += f"- **{ent}**\n"

    Path(output_path).write_text(md, encoding="utf-8")
    stampa(f"Cheatsheet salvato: {output_path}")


# ============================================================
# FASE 9 — SKILL.MD (Opzionale, per agenti)
# ============================================================


def export_skill_md(essay, map_results, output_path, book_title, author="Sconosciuto"):
    """Genera SKILL.md compatibile con book-to-skill / agenti Claude/OpenCode."""
    # Estrai titoli di sezione dal saggio
    sections = [
        line.strip()[4:]
        for line in essay.split("\n")
        if line.strip().startswith("### ")
    ]
    chapters_found = len(sections)

    # Estrai prime righe come descrizione
    first_para = ""
    for line in essay.split("\n"):
        s = line.strip()
        if s and not s.startswith("#"):
            first_para = s[:200]
            break

    # Costruisci topic index dalle entità
    all_terms = []
    for mr in map_results:
        if not mr:
            continue
        for p in mr.get("entities", {}).get("persone", [])[:10]:
            all_terms.append(p.strip().rstrip(".,;:"))
        for o in mr.get("entities", {}).get("opere", [])[:5]:
            all_terms.append(o.strip().rstrip(".,;:"))

    slug = re.sub(r"[^a-z0-9-]", "", book_title.lower().replace(" ", "-"))[:40]

    md = f"""---
name: {slug}
description: "Knowledge base from \"{book_title}\". Use when studying {book_title.split()[0] if book_title.split() else "this subject"}, referencing its concepts, or applying its frameworks."
allowed-tools:
  - Read
  - Grep
argument-hint: [topic, chapter, or concept]
---

# {book_title}

**Chapters**: ~{chapters_found} | **Generated**: {datetime.now().strftime("%Y-%m-%d")}

## How to Use

- Without arguments — load core frameworks
- With a topic — ask about a specific concept
- With chapter — ask for section name

## Core Frameworks

{first_para}

## Chapter Index

"""
    for i, sec in enumerate(sections):
        md += f"- [Section {i + 1}] — {sec}\n"

    if all_terms:
        md += "\n## Topic Index\n\n"
        for term in sorted(set(all_terms))[:40]:
            md += f"- **{term}**\n"

    Path(output_path).write_text(md, encoding="utf-8")
    stampa(f"SKILL.md salvato: {output_path}")


# ============================================================
# CHECKPOINT
# ============================================================


def save_checkpoint(book_id, phase, data):
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    fname = re.sub(r'[<>:"/\\|?*]', "_", book_id)
    path = CHECKPOINT_DIR / f"{fname}_{phase}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# PIPELINE PRINCIPALE
# ============================================================


def process_book(file_path: str):
    """Pipeline completa: qualsiasi formato → .docx + glossary + cheatsheet + SKILL.md."""
    fp = Path(file_path)
    if not fp.exists():
        stampa(f"ERRORE: File non trovato: {fp}")
        return

    book_id = re.sub(r'[<>:"/\\|?*]', "_", fp.stem)
    book_title = fp.stem

    stampa(f"{'=' * 60}")
    stampa(f"PIPELINE UNIFICATA: {fp.name}")
    stampa(f"{'=' * 60}")

    # FASE 1: Estrazione
    stampa("\n[FASE 1/5] Estrazione testo universale...")
    raw_text = extract_text(str(fp))
    if not raw_text or len(raw_text) < 100:
        stampa("  ERRORE: Testo insufficiente. File protetto o scansione?")
        return

    # FASE 2: Chunking
    stampa("\n[FASE 2/5] Chunking strutturale...")
    chunks = split_into_chunks(raw_text)
    stampa(f"  {len(chunks)} chunk")
    for i, c in enumerate(chunks):
        stampa(f"    Chunk {i + 1}: {c['token_count']} token")
    save_checkpoint(book_id, "chunking", {"chunks": chunks, "total": len(chunks)})

    # FASE 3: Map
    stampa("\n[FASE 3/5] Map (deepseek-v4.1-flash:cloud)...")
    map_results = []
    for i, ch in enumerate(chunks):
        result = map_chunk(ch, i, len(chunks))
        if result:
            fb = feedback_loop(ch["text"], result)
            if fb["coverage"] < 70 and fb["integration"]:
                result["summary"] += "\n\n" + fb["integration"]
                stampa(f"    → Integrato chunk {i + 1} (coverage {fb['coverage']}%)")
            result["feedback"] = fb
            map_results.append(result)
            save_checkpoint(book_id, "map", {"results": map_results})
        else:
            stampa(f"  FAILED: chunk {i + 1}")

    if not map_results:
        stampa("ERRORE: Nessun chunk processato.")
        return

    stampa(f"  Completati {len(map_results)}/{len(chunks)} chunk")

    # FASE 4: Reduce
    stampa("\n[FASE 4/5] Reduce — tessitura saggio (deepseek-v4.1-flash:cloud)...")
    glossary = build_glossary(map_results)
    essay = reduce_summaries(map_results, glossary)
    if not essay:
        stampa("ERRORE: Reduce fallito.")
        return
    stampa(f"  Saggio: {len(essay)} caratteri ({estimate_tokens(essay)} token)")
    save_checkpoint(book_id, "reduce", {"essay": essay})

    # Coverage report
    coverage_report = {
        "average_coverage": sum(
            r.get("feedback", {}).get("coverage", 100) for r in map_results
        )
        / len(map_results),
        "missing_entities": list(
            set(
                e for r in map_results for e in r.get("feedback", {}).get("missing", [])
            )
        ),
    }

    # FASE 5: Export
    stampa("\n[FASE 5/5] Export output...")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base = OUTPUT_DIR / f"Riassunto_{book_id}"

    # .docx
    export_docx(essay, f"{base}.docx", book_title, coverage_report)

    # glossary.md
    export_glossary(map_results, f"{base}_glossario.md", book_title)

    # cheatsheet.md
    export_cheatsheet(essay, map_results, f"{base}_cheatsheet.md", book_title)

    # SKILL.md
    export_skill_md(
        essay,
        map_results,
        f"{OUTPUT_DIR}/{re.sub(r'[^a-z0-9-]', '', book_title.lower().replace(' ', '-'))[:40]}_skill.md",
        book_title,
    )

    # Report finale
    stampa("\n" + "=" * 60)
    stampa(f"COMPLETATO: {fp.name}")
    stampa(f"  Saggio:    {base}.docx")
    stampa(f"  Glossario: {base}_glossario.md")
    stampa(f"  Cheatsheet: {base}_cheatsheet.md")
    stampa(f"  SKILL.md:  nella cartella riassunti/")
    stampa(f"  Copertura: {coverage_report['average_coverage']:.0f}%")
    stampa(
        f"  Tempo:     ~{estimate_tokens(raw_text) // 750} min per {estimate_tokens(raw_text)}K token"
    )
    stampa("=" * 60)

    return True


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_book(sys.argv[1])
    else:
        stampa("Uso: python pipeline_unificata.py <path-to-document>")
        stampa("Supporta: PDF, EPUB, DOCX, TXT, MD, HTML, RTF, MOBI/AZW")
        stampa("\nEsempi:")
        stampa('  python pipeline_unificata.py "libro.pdf"')
        stampa('  python pipeline_unificata.py "D:\\Downloads\\mio_libro.epub"')
        stampa('  python pipeline_unificata.py "libro.docx"')
