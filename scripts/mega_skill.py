#!/usr/bin/env python3
"""
MEGA-SKILL RIASSUNTO UNIVERSITARIO — Assemblea V6
4 Micro-Skill modulari: L'Occhio, Il Chirurgo, L'Equalizzatore, L'Impaginatore
Infrastruttura: Ollama Pro Cloud (deepseek-v4.1-flash:cloud) + Tesseract OCR 5.4 + pdfplumber
Tutto in D: — costo marginale zero
"""

import os, sys, re, json, time, subprocess, shutil, glob, tempfile, difflib
from pathlib import Path
from collections import Counter
import requests
import argparse

# ─────────── CONFIG ───────────
OLLAMA = "http://127.0.0.1:11434"
TESSERACT_PATH = r"D:\tesseract\tesseract.exe"
POPPLER_PATH = r"D:\poppler\poppler-24.08.0\Library\bin"
os.environ["Path"] += f";{POPPLER_PATH}"

# WeasyPrint: GTK DLLs path (da D: per non occupare C:)
GTK_PATH = r"D:\tesseract_gtk"
os.environ.setdefault("WEASYPRINT_DLL_DIRECTORIES", GTK_PATH)
os.environ["FONTCONFIG_PATH"] = GTK_PATH  # fonts.conf in D:\tesseract_gtk\
if GTK_PATH not in os.environ["PATH"]:
    os.environ["PATH"] = GTK_PATH + os.pathsep + os.environ["PATH"]

# ─────────── MICRO-SKILL 1: L'OCCHIO ───────────


def _tripla_soglia(testo):
    """Verifica se un frammento di testo è probabilmente una scansione (non testo nativo).
    Restituisce (is_scan: bool, metrics: dict).
    Tre metriche: (a) parole < 100, (b) rapporto alfabetico/non-alfabetico < 0.4,
    (c) lunghezza media parola < 3.5. Se ≥2 su 3 → scansione.
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


def diagnostica_avanzata(pdf_path):
    """Pre-flight check stile Claude: pdfinfo + pdffonts per capire struttura PDF."""
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)

    # Test testo prima pagina
    sample = reader.pages[0].extract_text()
    has_text = bool(sample and len(sample.strip()) > 30)

    # Stima pagine
    raw_pages = reader.get_num_pages()

    # Tenta pdftotext -layout per qualità colonne
    import subprocess, tempfile

    quality = "pdfplumber"
    with tempfile.TemporaryDirectory() as tmp:
        out_txt = os.path.join(tmp, "test_layout.txt")
        subprocess.run(
            ["pdftotext", "-layout", "-l", "3", pdf_path, out_txt],
            capture_output=True,
            timeout=30,
            env={**os.environ, "PATH": os.environ["Path"]},
        )
        if os.path.exists(out_txt):
            txt = open(out_txt, encoding="utf-8", errors="replace").read()
            if len(txt) > len(sample) * 1.5:  # pdftotext ha estratto meglio
                quality = "pdftotext-layout"

    return {
        "pagine": num_pages,
        "has_text": has_text,
        "quality": quality,
        "pdf_path": pdf_path,
    }


def diagnostica_e_estrai(pdf_path, deep_scan=False):
    """
    Pre-flight check: rileva se il PDF ha testo o e scansione usando tripla soglia.
    deep_scan=True forza OCR anche se testo rilevato.
    Restituisce sempre (testo, num_pagine).
    """
    print(f"[L'Occhio] Analisi: {os.path.basename(pdf_path)}")

    import subprocess, tempfile
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)
    # Campiona 3-5 pagine distribuite per decisione più robusta
    sample_pages = []
    page_indices = [0]
    if num_pages > 10:
        page_indices.append(num_pages // 2)
    if num_pages > 5:
        page_indices.append(min(num_pages - 1, 3))
    if num_pages > 20:
        page_indices.append(num_pages - 1)
    for pi in page_indices:
        t = reader.pages[pi].extract_text()
        if t:
            sample_pages.append(t)
    sample = "\n".join(sample_pages) if sample_pages else ""

    if deep_scan:
        print("[L'Occhio] --deep-scan: forzatura OCR")
        testo, _ = _estrai_ocr(pdf_path)
        return testo, num_pages

    if sample and len(sample.strip()) > 30:
        # Tripla soglia per rilevare scansioni
        is_scan, metrics = _tripla_soglia(sample)
        if is_scan:
            print(f"[L'Occhio] Tripla soglia: {metrics['sotto_soglia']}/3 sotto soglia")
            print(
                f"  Metrics: {metrics['parole']} parole, "
                f"rapp_alf={metrics['rapporto_alf']}, "
                f"avg_len={metrics['media_parola']}"
            )
            testo, _ = _estrai_ocr(pdf_path)
            return testo, num_pages

        with tempfile.TemporaryDirectory() as tmp:
            out_txt = os.path.join(tmp, "test.txt")
            r = subprocess.run(
                ["pdftotext", "-layout", "-l", "3", pdf_path, out_txt],
                capture_output=True,
                timeout=30,
            )
            if os.path.exists(out_txt):
                txt = open(out_txt, encoding="utf-8", errors="replace").read()
                if len(txt) > len(sample) * 1.3:
                    print(
                        "[L'Occhio] Testo rilevato, layout colonne preservato via pdftotext"
                    )
                    testo, _ = _estrai_pdftotext(pdf_path)
                    return testo, num_pages

        print("[L'Occhio] Testo rilevato → pdfplumber")
        testo, _ = _estrai_pdfplumber(pdf_path)
        return testo, num_pages
    else:
        print("[L'Occhio] Nessun testo → OCR Tesseract 5.4")
        testo, _ = _estrai_ocr(pdf_path)
        return testo, num_pages


def _estrai_pdftotext(pdf_path):
    """Estrazione con pdftotext -layout con marcatori di pagina."""
    import subprocess, tempfile, fitz

    # Prima ottieni il numero di pagine con PyMuPDF
    doc = fitz.open(pdf_path)
    num_pages = len(doc)
    doc.close()

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "full.txt")
        subprocess.run(["pdftotext", "-layout", pdf_path, out_path], timeout=120)
        if os.path.exists(out_path):
            result = open(out_path, encoding="utf-8", errors="replace").read()
            print(
                f"  Estratto: {len(result)} car via pdftotext -layout ({num_pages} pp)"
            )
            return result, num_pages
    return _estrai_pdfplumber(pdf_path)


def _estrai_pdfplumber(pdf_path):
    """Estrazione layout-aware con pdfplumber, con marcatori di pagina."""
    import pdfplumber

    testo = []
    num_pages = 0
    with pdfplumber.open(pdf_path) as pdf:
        num_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            t = page.extract_text()
            if t:
                testo.append(f"\n\n[PAGINA {i + 1}]\n\n{t}")
    result = "".join(testo)
    print(f"  Estratto: {len(result)} car via pdfplumber ({num_pages} pp)")
    return result, num_pages


def _estrai_ocr(pdf_path):
    """OCR parallelo con Tesseract 5.4, con marcatori di pagina."""
    from pdf2image import convert_from_path
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

    print("  Convertendo pagine in immagini (200 DPI)...")
    with tempfile.TemporaryDirectory() as tmpdir:
        images = convert_from_path(pdf_path, dpi=200, output_folder=tmpdir)
        print(f"  OCR su {len(images)} pagine con 4 thread paralleli...")

        def ocr_pagina(img_data):
            idx, img = img_data
            return idx, pytesseract.image_to_string(img, lang="ita")

        risultati = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            for idx, testo in executor.map(ocr_pagina, enumerate(images)):
                risultati.append((idx, testo))
                if (idx + 1) % 10 == 0:
                    print(f"    OCR {idx + 1}/{len(images)}...")

        risultati.sort(key=lambda x: x[0])
        result = "\n\n".join([f"\n\n[PAGINA {idx + 1}]\n\n{t}" for idx, t in risultati])

    print(f"  Estratto: {len(result)} car via OCR parallelo (cache pulita)")
    return result, len(images)
    return _estrai_pdfplumber(pdf_path)





def estrai_metadati(pdf_path):
    """Legge i metadati del PDF per il frontespizio."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(pdf_path)
        meta = reader.metadata
        titolo = meta.title if meta and meta.title else os.path.basename(pdf_path)
        autore = meta.author if meta and meta.author else "Autore sconosciuto"
        return titolo, autore
    except Exception:
        return os.path.basename(pdf_path), "Autore sconosciuto"


# ─────────── MICRO-SKILL 2: IL CHIRURGO ───────────


def chunking_con_overlap(testo, max_tok=24000, overlap_paragrafi=2):
    """Divide il testo in blocchi mantenendo overlap di contesto tra chunk."""
    print(f"[Il Chirurgo] Chunking con overlap di {overlap_paragrafi} paragrafi...")

    # Dividi per doppi a capo (preserva [PAGINA N])
    paragrafi = [p.strip() for p in re.split(r"\n\s*\n", testo) if p.strip()]
    chunks = []
    current, cur_tok, cid = [], 0, 0
    i = 0

    # Rileva le pagine coperte da ogni chunk

    while i < len(paragrafi):
        para = paragrafi[i]
        pt = len(para) // 5

        # Paragrafo gigante → split per frasi
        if pt > max_tok:
            if current:
                chunks.append(
                    {"id": cid, "text": "\n\n".join(current), "token_count": cur_tok}
                )
                cid += 1
                overlap = current[-overlap_paragrafi:] if overlap_paragrafi > 0 else []
                current = list(overlap)
                cur_tok = sum(len(p) // 5 for p in current)
            for sent in re.split(r"(?<=[.!?])\s+", para):
                st = len(sent) // 5
                if cur_tok + st > max_tok and current:
                    chunks.append(
                        {
                            "id": cid,
                            "text": "\n\n".join(current),
                            "token_count": cur_tok,
                        }
                    )
                    cid += 1
                    overlap = (
                        current[-overlap_paragrafi:] if overlap_paragrafi > 0 else []
                    )
                    current = list(overlap)
                    cur_tok = sum(len(p) // 5 for p in current)
                current.append(sent)
                cur_tok += st
            i += 1
            continue

        if cur_tok + pt > max_tok and current:
            chunks.append(
                {"id": cid, "text": "\n\n".join(current), "token_count": cur_tok}
            )
            cid += 1
            overlap = current[-overlap_paragrafi:] if overlap_paragrafi > 0 else []
            current = list(overlap)
            cur_tok = sum(len(p) // 5 for p in current)

        current.append(para)
        cur_tok += pt
        i += 1

    if current:
        chunks.append({"id": cid, "text": "\n\n".join(current), "token_count": cur_tok})

    # Merge chunk piccoli
    merged = []
    for c in chunks:
        if c["token_count"] < 800 and merged and merged[-1]["token_count"] + c["token_count"] <= max_tok:
            merged[-1]["text"] += "\n\n" + c["text"]
            merged[-1]["token_count"] += c["token_count"]
        else:
            merged.append(c)
    for i, m in enumerate(merged):
        m["id"] = i

    print(f"  {len(merged)} chunk finali")
    return merged


# ─────────── MICRO-SKILL 3: L'EQUALIZZATORE ───────────

PROMPT_MAP_SEMPLICE = """Riscrivi il testo in italiano SEMPLICE, CONCISO, completo.

Parla come un amico intelligente che spiega a uno stanco dopo lavoro. Frasi corte, parole di tutti i giorni.

TERMINI TECNICI: se usi parole specialistiche (recitativo, monodia, libretto...), aggiungi subito una brevissima spiegazione tra parentesi: "recitativo (canto parlato)", "libretto (testo dell'opera)".

GRASSETTO INTELLIGENTE: usa **grassetto** per evidenziare in modo strategico:
- **Nomi propri** di persone, luoghi, istituzioni importanti (es: **Monteverdi**, **Venezia**, **Teatro San Cassiano**)
- **Date e periodi** chiave (es: **1637**, **primo Seicento**)
- **Concetti portanti** che sono il tema centrale del discorso (es: **brevità**, **frequenza delle arie**, **recitativo**, **mercato dell'opera**)
- **Relazioni causali** e punti di svolta (es: **passaggio dall'opera di corte all'opera a pagamento**, **nascita del melodramma**)
- **Termini tecnici** alla loro prima occorrenza (es: **libretto**, **monodia**, **basso continuo**)

Regola d'oro: non più di 2-3 grassetti per paragrafo. Il grassetto deve GUIDARE l'occhio, non appesantire.

REGOLE:
1. COMPLETEZZA: ogni nome, data, concetto, evento deve restare.
2. PARLA SEMPLICE: come al bar. Frasi corte, parole comuni.
3. CONCISIONE: vai dritto al punto. Taglia fronzoli.
4. LUNGHEZZA: circa {target}.
5. ### per i titoli.
6. ZERO elenchi puntati. ZERO asterischi singoli. Solo **grassetto** va bene.
7. Alla fine del riassunto, aggiungi QUESTE SEZIONI nell'ordine:

### Da Ricordare
Scrivi 3-5 concetti chiave del testo, ognuno come frase breve. Formato: **Concetto** — spiegazione in una riga.

### Cronologia
Elenco delle date principali menzionate, in ordine cronologico. Formato: **Anno** — evento.

### Glossario
5-10 termini tecnici con definizione breve. Formato: **termine** — definizione.

### Opere Citati
Elenco delle opere, libri, articoli menzionati. Formato: **Titolo** (Autore, anno).

Poi: ### Scheda Riassuntiva (15 concetti, formato: Concetto: [termine] - [spiegazione]) e ### Domande di Verifica (5 domande, formato: Domanda: [domanda] - [risposta]).

Infine:
===ENTITA===
PERSONE: separato da |
DATE: separato da |
OPERE/EVENTI/CONCETTI: separato da |
===FINE ENTITA===

TESTO:
{testo}"""

PROMPT_MAP_EN_SEMPLICE = """Rewrite in simple, CONCISE, complete Italian.

Write like a smart friend explaining to a tired friend after work. Short sentences, everyday words.

TECHNICAL TERMS: when you use specialist words (recitative, monody, libretto...), add a quick explanation in parentheses: "recitative (sung speech)", "libretto (opera text)".

BOLD: use **word** to highlight important names, key dates, core concepts. Ex: **Monteverdi**, **1637**, **recitative**. Dont overdo it.

RULES:
1. COMPLETENESS: every name, date, concept, event must stay.
2. SIMPLE LANGUAGE: like at a bar. Short sentences, common words.
3. CONCISE: get to the point. Cut fluff.
4. LENGTH: about {target}.
5. Use ### for section titles.
6. ZERO bullet points. ZERO single asterisks. Only **bold** is fine.
7. At the end of the summary, add THESE SECTIONS in order:

### Da Ricordare
Write 3-5 key concepts from the text, each as a short phrase. Format: **Concept** — one-line explanation.

### Cronologia
List the main dates mentioned, in chronological order. Format: **Year** — event.

### Glossario
5-10 technical terms with short definitions. Format: **term** — definition.

### Opere Citati
List of works, books, articles mentioned. Format: **Title** (Author, year).

Then: ### Scheda Riassuntiva (15 concepts, format: Concetto: [term] - [explanation]) and ### Domande di Verifica (5 questions, format: Domanda: [question] - [answer]).

Finally:
===ENTITA===
PERSONE: list separated by |
DATE: list separated by |
OPERE/EVENTI/CONCETTI: list separated by |
===FINE ENTITA===

TEXT:
{testo}"""


def equalizzatore_map(chunk, prompt_template, chunk_index=0, max_chars=0):
    """Map: riassume un chunk con Ollama. Protocollo grounding zero allucinazioni.
    max_chars: se > 0, impone un limite duro al numero di caratteri dell'output.
    """
    prompt_base = prompt_template.replace("{testo}", chunk["text"])

    # STEP 1: Inietta grounding e citazioni
    grounding = (
        f"\n\nREGOLE DI SICUREZZA:\n"
        f"1. GROUNDING: basa la sintesi ESCLUSIVAMENTE sul testo qui sopra. Vietato usare conoscenze esterne.\n"
        f"2. ZERO ALLUCINAZIONI: non inventare collegamenti, eventi o nomi non presenti nel testo.\n"
        f"3. RIFIUTO: se il testo e irrilevante (indici, ringraziamenti, bibliografia vuota, o se le istruzioni dicono di saltarlo), "
        f"restituisci ESATTAMENTE: '[NESSUN CONTENUTO UTILE]' o '[SKIP]'\n"
        f"4. CITAZIONE: dopo ogni blocco narrativo, aggiungi ESATTAMENTE: [Fonte: Blocco {chunk_index + 1}]"
    )
    if max_chars > 0:
        grounding += (
            f"\n5. LUNGHEZZA MASSIMA: il riassunto NON DEVE superare {max_chars} caratteri. "
            f"Se superi questo limite, il testo verra troncato. Sii conciso."
        )
    prompt = prompt_base + grounding

    for attempt in range(5):
        try:
            resp = requests.post(
                f"{OLLAMA}/api/chat",
                json={
                    "model": "deepseek-v4.1-flash:cloud",
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"num_ctx": 32768, "temperature": 0.3},
                    "stream": False,
                },
                timeout=600,
            )
            content = resp.json().get("message", {}).get("content", "")

            entities = {"persone": [], "date": [], "opere": []}
            em = re.search(r"===ENTITA===\n(.*?)===FINE ENTITA===", content, re.DOTALL)
            if em:
                for line in em.group(1).strip().split("\n"):
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
                    elif line.startswith("OPERE") and ":" in line:
                        entities["opere"] = [
                            e.strip()
                            for e in line.split(":", 1)[1].split("|")
                            if e.strip()
                        ]
                clean = content[: em.start()].strip()
            else:
                clean = content.strip()

            # Troncamento duro: se max_chars > 0, taglia al limite
            # Rimuovi solo asterischi singoli (bullet), preserva **grassetto**
            summary = re.sub(r"(?<!\*)\*(?!\*)", "", clean)
            if max_chars > 0 and len(summary) > max_chars:
                # Taglia all'ultimo paragrafo completo entro il limite
                summary = summary[:max_chars]
                last_para = summary.rfind("\n\n")
                if last_para > max_chars * 0.7:
                    summary = summary[:last_para]
            return {"summary": summary, "entities": entities}
        except Exception as e:
            print(f"  Retry {attempt + 1}: {str(e)[:60]}")
            time.sleep(30 * (2 ** attempt))  # exponential backoff: 30s, 60s, 120s, 240s, 480s
    return None


def _contiene_skip(testo):
    """Verifica se il testo contiene marcatori di skip/nessun contenuto."""
    if not testo:
        return True
    skip_markers = ["[NESSUN CONTENUTO UTILE]", "[SKIP]", "NESSUN CONTENUTO UTILE"]
    for marker in skip_markers:
        if marker in testo:
            return True
    return False


def _verifica_citazioni(testo):
    """Verifica l'integrità delle citazioni [Fonte: Blocco N] con regex.
    Restituisce dict con conteggi e lista dettagliata.
    """
    if not testo:
        return {"ok": 0, "giallo": 0, "rosso": 0, "dettagli": []}
    citazioni = re.findall(r"\[Fonte:\s*Blocco\s*(\d+)\]", testo)
    dettagli = []
    ok = giallo = rosso = 0
    for c in citazioni:
        expected = f"[Fonte: Blocco {c}]"
        if expected in testo:
            ok += 1
            dettagli.append((c, 1.0, "OK"))
        else:
            rosso += 1
            dettagli.append((c, 0.0, "ROSSO"))
    return {"ok": ok, "giallo": giallo, "rosso": rosso, "dettagli": dettagli}


def _deduplica_testo(essay):
    """Three-level deduplication: paragraph, phrase, word.

    Level 1: Paragraph-level — detect near-duplicate paragraphs via SequenceMatcher.
    Level 2: Phrase-level — detect repeated 4-gram sentence openings.
    Level 3: Word-level — detect immediate word repetitions (4+ chars only).
    """
    import difflib

    if not essay:
        return essay

    # Level 1: Paragraph-level dedup
    paragraphs = essay.split('\n\n')
    deduped = []
    seen_paras = []
    for p in paragraphs:
        p_stripped = p.strip()
        if not p_stripped:
            deduped.append(p)
            continue
        is_dup = False
        for seen in seen_paras[-3:]:
            ratio = difflib.SequenceMatcher(None, p_stripped.lower(), seen.lower()).ratio()
            if ratio > 0.65:
                is_dup = True
                break
        if not is_dup:
            deduped.append(p)
            seen_paras.append(p_stripped)

    essay = '\n\n'.join(deduped)

    # Level 2: Phrase-level — detect repeated sentence openings (4-gram)
    sentences = re.split(r'(?<=[.!?])\s+', essay)
    seen_phrases = set()
    clean_sentences = []
    for sent in sentences:
        words = sent.split()
        if len(words) < 4:
            clean_sentences.append(sent)
            continue
        key = ' '.join(words[:4]).lower().strip('.,;:!?')
        if key in seen_phrases and len(key) > 15:
            continue  # skip near-duplicate sentence
        seen_phrases.add(key)
        clean_sentences.append(sent)
    essay = ' '.join(clean_sentences)

    # Level 3: Word-level immediate repetition (only words 4+ chars to avoid false positives)
    essay = re.sub(r"(\b\w{4,})\s+\1\b", r"\1", essay)

    return essay


def equalizzatore_reduce(results):
    """Reduce meccanico: concatena in ordine, pulisce citazioni e duplicazioni."""
    parts = []
    for r in results:
        t = r.get("summary", "")
        if not re.search(r"^#{1,3}\s+", t, re.MULTILINE):
            t = "### Sezione\n\n" + t
        parts.append(t)

    essay = "\n\n".join(parts)

    # Verifica citazioni con SequenceMatcher
    cit_report = _verifica_citazioni(essay)
    if cit_report["ok"] + cit_report["giallo"] + cit_report["rosso"] > 0:
        print(
            f"  Citazioni: {cit_report['ok']}✅ {cit_report['giallo']}⚠ {cit_report['rosso']}🔴"
        )
        if cit_report["rosso"] > 0:
            for c, r, s in cit_report["dettagli"]:
                if s == "ROSSO":
                    print(f"    🔴 Citazione Blocco {c}: ratio {r:.2f}")

    # Pulisci solo citazioni rotte (non note accademiche [1], [2])
    essay = re.sub(r"\[Fonte:\s*Blocco\s*[A-Za-z0-9]+\]", " ", essay)
    essay = _deduplica_testo(essay)
    essay = re.sub(r"  +", " ", essay)
    return essay


# ─────────── BOLDIFY INTELLIGENTE ───────────


def boldify_intelligente(essay, entities):
    """Applica **grassetto** strategico alle entità conosciute nel testo.

    Regole:
    - Persone: sempre in grassetto (nomi propri)
    - Date (4 cifre): sempre in grassetto
    - Opere/titoli: grassetto se sono titoli di opere, libri, articoli
    - Solo PRIMA occorrenza per paragrafo (evita rumore visivo)
    - Non applica grassetto a parole già in grassetto o dentro titoli ###
    - Ordine: prima le entità più lunghe (per evitare sovrapposizioni)
    - Salta parole corte (< 4 caratteri) e comuni
    """
    import re

    # Parole comuni da NON mettere in grassetto (evita rumore)
    SKIP_WORDS = {
        "anno",
        "anni",
        "dopo",
        "prima",
        "dove",
        "come",
        "cosa",
        "quel",
        "della",
        "degli",
        "delle",
        "dello",
        "nella",
        "negli",
        "nelle",
        "nello",
        "sulla",
        "sugli",
        "sulle",
        "sullo",
        "dalla",
        "dagli",
        "dalle",
        "dallo",
        "nella",
        "negli",
        "nelle",
        "nello",
    }

    # Costruisci lista di pattern ordinati per lunghezza decrescente
    all_terms = []
    for cat, terms in entities.items():
        for t in terms:
            t_clean = t.strip().rstrip(".,;:!?")
            if len(t_clean) > 3 and t_clean.lower() not in SKIP_WORDS:
                all_terms.append((len(t_clean), re.escape(t_clean), t_clean))
    all_terms.sort(reverse=True)

    # Applica grassetto riga per riga, saltando titoli e sezioni speciali
    lines = essay.split("\n")
    new_lines = []
    for line in lines:
        s = line.strip()
        # Salta titoli e sezioni speciali
        if s.startswith("#") or s.startswith("Concetto:") or s.startswith("Domanda:"):
            new_lines.append(line)
            continue
        # Salta righe già con grassetti
        if "**" in s:
            new_lines.append(line)
            continue
        # Applica grassetto: solo PRIMA occorrenza di ogni entità per riga
        result = line
        seen_in_line = set()
        for length, pattern, original in all_terms:
            if original.lower() in seen_in_line:
                continue
            # Pattern senza \b per gestire apostrofi e accenti italiani
            new_result = re.sub(
                r"(?<!\*)" + pattern + r"(?!\*)",
                r"**\g<0>**",
                result,
                count=1,  # solo prima occorrenza
            )
            if new_result != result:
                seen_in_line.add(original.lower())
                result = new_result
        new_lines.append(result)

    return "\n".join(new_lines)


# ─────────── THEME SYSTEM ───────────

from dataclasses import dataclass
from typing import Optional


@dataclass
class Theme:
    """Design theme for the impaginatore.
    
    Controls colors, typography, cover layout, header style, and decorations.
    """
    name: str
    primary: str = "#1a2744"       # headings, main color
    secondary: str = "#2c3e6b"     # h3, secondary elements
    accent: str = "#1a2744"        # borders, accents, drop cap
    background: str = "#faf8f3"    # page background
    text_color: str = "#1a1a1a"    # body text
    font_serif: str = "'Georgia', 'Palatino Linotype', 'Book Antiqua', 'Times New Roman', serif"
    font_sans: str = "'Helvetica Neue', Arial, sans-serif"
    cover_style: str = "classic"   # classic, modern, minimal, artistic
    header_style: str = "classic"  # classic, modern, underlined, decorative
    decoration: str = "none"       # none, subtle, ornate


THEMES = {
    "classic": Theme(
        name="classic",
        primary="#1a2744",
        secondary="#2c3e6b",
        accent="#1a2744",
        background="#faf8f3",
    ),
    "forest": Theme(
        name="forest",
        primary="#1b4332",
        secondary="#2d6a4f",
        accent="#2d6a4f",
        background="#f4f1ea",
    ),
    "royal": Theme(
        name="royal",
        primary="#3d1a4e",
        secondary="#6b2d5a",
        accent="#6b2d5a",
        background="#f8f4f0",
    ),
    "sunset": Theme(
        name="sunset",
        primary="#8b3a1a",
        secondary="#c45a2a",
        accent="#c45a2a",
        background="#fdf6ee",
    ),
    "ocean": Theme(
        name="ocean",
        primary="#0a3d5c",
        secondary="#1a6b8a",
        accent="#1a6b8a",
        background="#f0f4f8",
    ),
    "monochrome": Theme(
        name="monochrome",
        primary="#333333",
        secondary="#666666",
        accent="#555555",
        background="#fafafa",
    ),
}


def rileva_tema(filename: str, essay: str = "") -> Theme:
    """Detect the most appropriate theme from filename and optional content.
    
    First tries filename-based matching (specific author/book names),
    then falls back to content keyword analysis on the first 2000 chars.
    Returns THEMES["classic"] as default.
    """
    fp_lower = filename.lower()
    
    # Filename-based detection (specific known books/authors)
    if "bianconi" in fp_lower:
        return THEMES["forest"]
    if "rosand" in fp_lower or "venice" in fp_lower:
        return THEMES["royal"]
    if "ivanovich" in fp_lower or "cristoforo" in fp_lower or "bellina" in fp_lower:
        return THEMES["classic"]
    
    # Content-based detection
    if essay and len(essay) > 200:
        sample = essay[:2000].lower()
        
        # Topic → theme mapping with rich keyword sets
        topic_themes = [
            (["natura", "forest", "green", "environment", "ecologia", "naturale", 
              "piante", "alberi", "bosco", "giardino", "campagna", "paesaggio",
              "flora", "fauna", "selvatico", "verde", "prato", "foglie"], "forest"),
            (["arte", "pittura", "musica", "teatro", "opera", "barocco", 
              "rinascimento", "melodramma", "scultura", "affresco", "dipinto",
              "compositore", "libretto", "recitativo", "aria", "sinfonia",
              "palcoscenico", "spettacolo", "coreografia", "balletto"], "royal"),
            (["mare", "oceano", "acqua", "navigazione", "isola", "costiero", 
              "marino", "pesca", "vela", "onda", "corrente", "profondità",
              "spiaggia", "porto", "marittimo", "subacqueo"], "ocean"),
            (["sole", "tramonto", "calore", "fuoco", "estate", "mediterraneo", 
              "sicilia", "sardegna", "deserto", "luce", "caldo", "fiamma",
              "vulcano", "lava", "crepuscolo", "aurora"], "sunset"),
            (["filosofia", "logica", "matematica", "scienza", "teoria", 
              "struttura", "sistema", "metodo", "analisi", "concetto",
              "astratto", "ragionamento", "deduzione", "ipotesi", "paradigma"], "monochrome"),
            (["storia", "storico", "antico", "medievale", "moderno", "contemporaneo",
              "civiltà", "impero", "regno", "dinastia", "rivoluzione", "guerra",
              "pace", "trattato", "alleanza", "colonizzazione"], "classic"),
        ]
        
        for keywords, theme_name in topic_themes:
            if any(k in sample for k in keywords):
                return THEMES[theme_name]
    
    return THEMES["classic"]


# ─────────── MICRO-SKILL 4: L'IMPAGINATORE ───────────


def impaginatore_html(
    essay, output_path, titolo, autore="Autore sconosciuto", theme=None, colore_accento=None
):
    """Esporta in PDF via HTML+CSS — sistema di design editoriale professionale.

    Design system con classi CSS riutilizzabili:
    - Copertina con barra laterale, titolo grande, divisorio
    - Indice dei contenuti
    - Capitoli con titoli gerarchici
    - Box "Da ricordare" con accento colorato
    - Cronologia, Glossario, Opere citate
    - Tabella concetti (Scheda Riassuntiva)
    - Domande di verifica
    - Running header con titolo libro e sezione
    - Numerazione pagina
    - Colore accento personalizzabile per libro
    """
    # Theme resolution
    if theme is None and colore_accento is not None:
        import warnings
        warnings.warn("colore_accento is deprecated, use theme=Theme(...) instead", DeprecationWarning, stacklevel=2)
        theme = Theme(name="custom", accent=colore_accento, primary=colore_accento)
    elif theme is None:
        theme = THEMES["classic"]
    # Convenience aliases for CSS template
    accent = theme.accent
    colore_accento = theme.accent
    primary_color = theme.primary
    secondary_color = theme.secondary
    bg_color = theme.background
    text_color = theme.text_color
    font_serif = theme.font_serif
    font_sans = theme.font_sans

    # ── Theme-driven CSS variations ──
    
    # Cover style variations
    if theme.cover_style == "modern":
        cover_css = f"""
    .cover {{
        background: linear-gradient(135deg, {primary_color} 0%, {secondary_color} 100%);
    }}
    .cover-content {{
        padding: 6cm 3cm 3cm 3cm;
        text-align: center;
        max-width: 100%;
    }}
    .cover-label {{
        color: rgba(255,255,255,0.7);
        letter-spacing: 6pt;
    }}
    .cover-title {{
        color: white;
        font-size: 24pt;
        text-align: center;
        max-width: 100%;
    }}
    .cover-divider {{
        margin: 0.6cm auto;
        background: rgba(255,255,255,0.4);
    }}
    .cover-author {{
        color: rgba(255,255,255,0.8);
        text-align: center;
    }}
    .cover-note {{
        color: rgba(255,255,255,0.5);
        text-align: center;
    }}
    .cover-accent {{
        display: none;
    }}
    .cover::after {{
        display: none;
    }}
"""
    elif theme.cover_style == "minimal":
        cover_css = """
    .cover {
        background: white;
    }
    .cover-content {{
        padding: 4cm 3cm 3cm 3cm;
        max-width: 12cm;
    }}
    .cover-label {{
        color: #ccc;
        letter-spacing: 3pt;
    }}
    .cover-title {{
        color: #333;
        font-size: 20pt;
        font-weight: normal;
    }}
    .cover-divider {{
        width: 2cm;
        height: 1px;
        background: #ddd;
    }}
    .cover-author {{
        color: #999;
        font-style: normal;
    }}
    .cover-note {{
        display: none;
    }}
    .cover-accent {{
        display: none;
    }}
    .cover::after {{
        display: none;
    }}
"""
    elif theme.cover_style == "artistic":
        cover_css = f"""
    .cover {{
        background: linear-gradient(160deg, {bg_color} 0%, #f0ece2 40%, #e8e2d5 100%);
    }}
    .cover::before {{
        content: "";
        position: absolute;
        top: 0;
        right: 0;
        width: 40%;
        height: 100%;
        background: repeating-linear-gradient(
            45deg,
            transparent,
            transparent 20px,
            {accent}04 20px,
            {accent}04 21px
        );
        pointer-events: none;
    }}
    .cover-content {{
        padding: 5cm 3.5cm 3cm 4cm;
        max-width: 14cm;
    }}
    .cover-title {{
        font-size: 20pt;
        letter-spacing: 1pt;
    }}
    .cover-divider {{
        width: 4cm;
        height: 3px;
        background: linear-gradient(90deg, {accent}, transparent);
    }}
    .cover-accent {{
        width: 1.2cm;
        background: linear-gradient(180deg, {accent}, {secondary_color}, {accent});
    }}
    .cover::after {{
        display: block;
        width: 8cm;
        height: 8cm;
        background: radial-gradient(circle, {accent}10 0%, transparent 70%);
    }}
"""
    else:  # classic
        cover_css = ""  # No override needed — the base CSS already handles classic

    # Header style variations
    if theme.header_style == "modern":
        header_css = f"""
    h1, h2, h3 {{
        font-family: {font_sans};
        text-transform: uppercase;
        letter-spacing: 2pt;
        font-weight: 300;
    }}
    h1 {{
        font-size: 13pt;
        border-bottom: none;
        letter-spacing: 3pt;
    }}
    h2 {{
        font-size: 11pt;
    }}
    h3 {{
        font-size: 10pt;
        color: {secondary_color};
    }}
"""
    elif theme.header_style == "underlined":
        header_css = f"""
    h1 {{
        border-bottom: 3px double {accent}60;
        padding-bottom: 0.3cm;
    }}
    h2 {{
        border-bottom: 1px solid {accent}40;
        padding-bottom: 0.15cm;
    }}
    h3 {{
        border-bottom: 1px dotted {accent}30;
        padding-bottom: 0.1cm;
    }}
"""
    elif theme.header_style == "decorative":
        header_css = f"""
    h1::before {{
        content: "";
        display: block;
        width: 3cm;
        height: 2px;
        background: {accent};
        margin-bottom: 0.3cm;
    }}
    h1 {{
        border-bottom: none;
    }}
    h2::before {{
        content: "";
        display: block;
        width: 2cm;
        height: 1px;
        background: {accent}60;
        margin-bottom: 0.2cm;
    }}
    h3 {{
        border-left: 3px solid {accent}40;
        padding-left: 0.5cm;
    }}
"""
    else:  # classic
        header_css = ""  # No override needed

    # Decoration variations
    if theme.decoration == "subtle":
        decor_css = f"""
    .section-ricordare::after,
    .section-cronologia::after,
    .section-glossario::after,
    .section-opere::after,
    .section-scheda::after,
    .section-domande::after {{
        content: "";
        display: block;
        width: 100%;
        height: 1px;
        background: linear-gradient(90deg, {accent}40, transparent);
        margin-top: 0.15cm;
    }}
    .body-text + .section-ricordare,
    .body-text + .section-cronologia,
    .body-text + .section-glossario,
    .body-text + .section-opere,
    .body-text + .section-scheda,
    .body-text + .section-domande {{
        margin-top: 1.5cm;
    }}
"""
    elif theme.decoration == "ornate":
        decor_css = f"""
    .section-ricordare,
    .section-cronologia,
    .section-glossario,
    .section-opere,
    .section-scheda,
    .section-domande {{
        border-bottom: none;
        position: relative;
        padding-top: 0.5cm;
    }}
    .section-ricordare::before,
    .section-cronologia::before,
    .section-glossario::before,
    .section-opere::before,
    .section-scheda::before,
    .section-domande::before {{
        content: "❧";
        display: block;
        font-size: 14pt;
        color: {accent}60;
        text-align: center;
        margin-bottom: 0.2cm;
    }}
    .section-ricordare::after,
    .section-cronologia::after,
    .section-glossario::after,
    .section-opere::after,
    .section-scheda::after,
    .section-domande::after {{
        content: "";
        display: block;
        width: 60%;
        height: 1px;
        background: linear-gradient(90deg, transparent, {accent}50, transparent);
        margin: 0.2cm auto 0;
    }}
    .cover-divider {{
        height: 3px;
        background: linear-gradient(90deg, transparent, {accent}, transparent);
    }}
"""
    else:  # none
        decor_css = ""  # No override needed

    import html as html_mod

    BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

    def html_paragraph(line):
        """Converte una riga di testo in HTML con grassetti reali.
        Applica bold PRIMA di escape, così **non** viene convertito."""

        # Prima converti **grassetto** in <strong>, poi escapa il resto
        def replace_bold(m):
            return "<strong>" + html_mod.escape(m.group(1)) + "</strong>"

        if BOLD_RE.search(line):
            # Sostituisci ** con placeholder, escapa, poi ripristina
            parts = BOLD_RE.split(line)
            result = []
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    # Testo normale → escapa
                    result.append(html_mod.escape(part))
                else:
                    # Contenuto del grassetto → escapa e avvolgi in <strong>
                    result.append("<strong>" + html_mod.escape(part) + "</strong>")
            return "".join(result)
        return html_mod.escape(line)

    # Estrai primo titolo sezione per running header
    primo_titolo = ""
    for line in essay.split("\n"):
        s = line.strip()
        if s.startswith("### ") or s.startswith("## ") or s.startswith("# "):
            primo_titolo = html_mod.escape(s.lstrip("# ").strip())
            break

    # Costruisci body HTML
    body_parts = []

    # ── COPERTINA (stile libro) ──
    body_parts.append(f'<div class="cover">')
    body_parts.append(
        f'<div class="cover-accent" style="background: linear-gradient(180deg, {primary_color}, #4a6fa5, {primary_color});"></div>'
    )
    body_parts.append(f'<div class="cover-content">')
    body_parts.append(f'<p class="cover-label">RIASSUNTO DI STUDIO</p>')
    # Titolo con word-wrap per evitare overflow
    titolo_esc = html_mod.escape(titolo)
    if len(titolo) > 50:
        body_parts.append(f'<h1 class="cover-title cover-title-long">{titolo_esc}</h1>')
    else:
        body_parts.append(f'<h1 class="cover-title">{titolo_esc}</h1>')
    body_parts.append(
        f'<div class="cover-divider" style="background: {accent};"></div>'
    )
    if autore and autore != "Autore sconosciuto":
        body_parts.append(f'<p class="cover-author">{html_mod.escape(autore)}</p>')
    body_parts.append(
        f'<p class="cover-note">Elaborazione ad alta densità narrativa per studio universitario</p>'
    )
    body_parts.append(f"</div>")
    body_parts.append(f"</div>")

    # ── CORPO — elabora riga per riga ──
    tabella_aperta = False
    sezione_corrente = primo_titolo
    in_da_ricordare = False
    in_cronologia = False
    in_glossario = False
    in_opere = False

    for line in essay.split("\n"):
        s = line.strip()
        if not s:
            continue

        # Rileva sezioni speciali
        if s.startswith("### Da Ricordare"):
            body_parts.append(f'<h2 class="section-ricordare">Da Ricordare</h2>')
            in_da_ricordare = True
            in_cronologia = in_glossario = in_opere = False
            continue
        if s.startswith("### Cronologia"):
            body_parts.append(f'<h2 class="section-cronologia">Cronologia</h2>')
            in_cronologia = True
            in_da_ricordare = in_glossario = in_opere = False
            continue
        if s.startswith("### Glossario"):
            body_parts.append(f'<h2 class="section-glossario">Glossario</h2>')
            in_glossario = True
            in_da_ricordare = in_cronologia = in_opere = False
            continue
        if s.startswith("### Opere Citati"):
            body_parts.append(f'<h2 class="section-opere">Opere Citati</h2>')
            in_opere = True
            in_da_ricordare = in_cronologia = in_glossario = False
            continue
        if s.startswith("### Scheda Riassuntiva"):
            body_parts.append(f'<h2 class="section-scheda">Scheda Riassuntiva</h2>')
            in_da_ricordare = in_cronologia = in_glossario = in_opere = False
            continue
        if s.startswith("### Domande di Verifica"):
            body_parts.append(f'<h2 class="section-domande">Domande di Verifica</h2>')
            in_da_ricordare = in_cronologia = in_glossario = in_opere = False
            continue

        # Aggiorna sezione corrente per running header
        if s.startswith("### ") or s.startswith("## ") or s.startswith("# "):
            sezione_corrente = html_mod.escape(s.lstrip("# ").strip())
            in_da_ricordare = in_cronologia = in_glossario = in_opere = False

        # Sezione Da Ricordare → box key
        if in_da_ricordare:
            if s.startswith("**") and "—" in s:
                parts = s.split("—", 1)
                termine = parts[0].strip(" *")
                spiegazione = parts[1].strip()
                body_parts.append(
                    f'<div class="box-key"><p><strong>{html_mod.escape(termine)}</strong> — {html_paragraph(spiegazione)}</p></div>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue

        # Sezione Cronologia → lista
        if in_cronologia:
            if s.startswith("**") and "—" in s:
                parts = s.split("—", 1)
                anno = parts[0].strip(" *")
                evento = parts[1].strip()
                body_parts.append(
                    f'<p class="cronologia-item"><span class="cronologia-anno">{html_mod.escape(anno)}</span> — {html_paragraph(evento)}</p>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue

        # Sezione Glossario → definition list
        if in_glossario:
            if s.startswith("**") and "—" in s:
                parts = s.split("—", 1)
                termine = parts[0].strip(" *")
                definizione = parts[1].strip()
                body_parts.append(
                    f'<p class="glossario-item"><strong class="glossario-termine">{html_mod.escape(termine)}</strong> — {html_paragraph(definizione)}</p>'
                )
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue

        # Sezione Opere → lista
        if in_opere:
            if s.startswith("**") and "(" in s:
                body_parts.append(f'<p class="opere-item">{html_paragraph(s)}</p>')
            else:
                body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')
            continue

        # Concetti → tabella
        if s.startswith("Concetto:"):
            clean = s.replace("Concetto:", "").strip()
            if "-" in clean:
                termine, spiegazione = clean.split("-", 1)
                if not tabella_aperta:
                    body_parts.append('<table class="concept-table">')
                    body_parts.append("<tr><th>Concetto</th><th>Spiegazione</th></tr>")
                    tabella_aperta = True
                body_parts.append(
                    f"<tr><td><strong>{html_mod.escape(termine.strip())}</strong></td><td>{html_paragraph(spiegazione.strip())}</td></tr>"
                )
            else:
                body_parts.append(f"<p>{html_paragraph(clean)}</p>")
            continue

        if tabella_aperta and not s.startswith("Concetto:"):
            body_parts.append("</table>")
            tabella_aperta = False

        # Domande
        if s.startswith("Domanda:"):
            clean = s.replace("Domanda:", "").strip()
            if "-" in clean:
                quesito, risposta = clean.split("-", 1)
                body_parts.append(f'<div class="qa-block">')
                body_parts.append(
                    f'<p class="question"><strong>{html_mod.escape(quesito.strip())}</strong></p>'
                )
                body_parts.append(
                    f'<p class="answer">{html_paragraph(risposta.strip())}</p>'
                )
                body_parts.append(f"</div>")
            else:
                body_parts.append(f"<p>{html_paragraph(clean)}</p>")
            continue

        # Titoli
        if s.startswith("### "):
            body_parts.append(f"<h3>{html_mod.escape(s[4:])}</h3>")
        elif s.startswith("## "):
            body_parts.append(f"<h2>{html_mod.escape(s[3:])}</h2>")
        elif s.startswith("# "):
            body_parts.append(f"<h1>{html_mod.escape(s[2:])}</h1>")
        else:
            body_parts.append(f'<p class="body-text">{html_paragraph(s)}</p>')

    if tabella_aperta:
        body_parts.append("</table>")

    # ── CSS DA VERO LIBRO — dinamico, elegante, accogliente ──
    css = f"""
    @page {{
        size: A4;
        margin: 2.2cm 2.5cm 2.5cm 2.5cm;
        @top-left {{
            content: "";
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 7.5pt;
            color: #bbb;
            margin-top: 0.4cm;
            font-variant: small-caps;
            letter-spacing: 1.5pt;
        }}
        @top-right {{
            content: "";
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 7.5pt;
            color: #bbb;
            font-style: italic;
            margin-top: 0.4cm;
        }}
        @bottom-center {{
            content: "— " counter(page) " —";
            font-family: 'Georgia', 'Times New Roman', serif;
            font-size: 8pt;
            color: #ccc;
            letter-spacing: 1pt;
        }}
    }}
    @page :first {{
        @top-left {{ content: ""; }}
        @top-right {{ content: ""; }}
        @bottom-center {{ content: ""; }}
        margin: 0;
    }}
    @page :nth(2) {{
        @top-left {{ content: ""; }}
        @top-right {{ content: ""; }}
    }}
    body {{
        font-family: {font_serif};
        font-size: 10.5pt;
        line-height: 1.75;
        color: {text_color};
        text-align: justify;
        hyphens: auto;
        orphans: 3;
        widows: 3;
    }}

    /* ═══════════════════════════════════════
       COPERTINA — stile libro rilegato di pregio
       ═══════════════════════════════════════ */
    .cover {{
        position: relative;
        page-break-after: always;
        min-height: 29.7cm;
        background: linear-gradient(160deg, {bg_color} 0%, #f0ece2 40%, #e8e2d5 100%);
        margin: 0;
        padding: 0;
        overflow: hidden;
    }}
    .cover::after {{
        content: "";
        position: absolute;
        bottom: 0;
        right: 0;
        width: 6cm;
        height: 6cm;
        background: radial-gradient(circle, {primary_color}08 0%, transparent 70%);
        pointer-events: none;
    }}
    .cover-accent {{
        position: absolute;
        top: 0;
        left: 0;
        width: 0.8cm;
        height: 100%;
    }}
    .cover-content {{
        position: relative;
        padding: 5.5cm 3.5cm 3cm 4cm;
        max-width: 15cm;
    }}
    .cover-label {{
        font-family: 'Georgia', serif;
        font-size: 8.5pt;
        letter-spacing: 5pt;
        text-transform: uppercase;
        color: #999;
        margin-bottom: 1.5cm;
    }}
    .cover-title {{
        font-family: 'Georgia', serif;
        font-size: 22pt;
        font-weight: bold;
        color: #1a2744;
        line-height: 1.3;
        margin-bottom: 0.6cm;
        text-align: left;
        word-wrap: break-word;
        overflow-wrap: break-word;
        hyphens: none;
        max-width: 13cm;
    }}
    .cover-title-long {{
        font-size: 16pt;
        line-height: 1.35;
    }}
    .cover-divider {{
        width: 3.5cm;
        height: 2px;
        margin: 0.6cm 0;
    }}
    .cover-author {{
        font-family: 'Georgia', serif;
        font-size: 11pt;
        color: #777;
        margin-bottom: 2cm;
        text-align: left;
        font-style: italic;
    }}
    .cover-note {{
        font-family: 'Georgia', serif;
        font-size: 8pt;
        font-style: italic;
        color: #bbb;
        margin-top: 0.8cm;
        text-align: left;
    }}

    /* ═══════════════════════════════════════
       TITOLI — gerarchia tipografica
       ═══════════════════════════════════════ */
    h1, h2, h3 {{
        font-family: 'Georgia', 'Palatino Linotype', serif;
        color: {primary_color};
        page-break-after: avoid;
        font-weight: normal;
    }}
    h1 {{
        font-size: 15pt;
        margin-top: 1.8cm;
        margin-bottom: 0.5cm;
        padding-bottom: 0.25cm;
        border-bottom: 1px solid #d4d0c8;
        letter-spacing: 0.3pt;
        font-weight: bold;
    }}
    h2 {{
        font-size: 12.5pt;
        margin-top: 1cm;
        margin-bottom: 0.35cm;
        font-weight: bold;
    }}
    h3 {{
        font-size: 11pt;
        margin-top: 0.7cm;
        margin-bottom: 0.25cm;
        font-weight: bold;
        color: {secondary_color};
    }}

    /* ═══════════════════════════════════════
       SEZIONI SPECIALI — con bordo colorato
       ═══════════════════════════════════════ */
    .section-ricordare,
    .section-cronologia,
    .section-glossario,
    .section-opere,
    .section-scheda,
    .section-domande {{
        color: {primary_color};
        border-bottom: 2px solid {primary_color};
        padding-bottom: 0.25cm;
        margin-top: 1.2cm;
        font-size: 13pt;
        font-weight: bold;
        letter-spacing: 0.3pt;
    }}

    /* ═══════════════════════════════════════
       PARAGRAFI — tipografia fluida
       ═══════════════════════════════════════ */
    p.body-text {{
        text-indent: 1.5em;
        margin: 0.15em 0;
    }}
    p.body-text:first-of-type {{
        text-indent: 0;
    }}
    p.body-text:first-of-type::first-letter {{
        font-size: 2.8em;
        font-weight: bold;
        color: {accent};
        float: left;
        line-height: 0.8;
        margin-right: 0.15em;
        margin-top: 0.05em;
        margin-bottom: -0.15em;
        font-family: 'Georgia', serif;
        initial-letter: 2;
    }}
    p.body-text + p.body-text {{
        margin-top: 0.1em;
    }}

    /* ═══════════════════════════════════════
       BOX DA RICORDARE — card con accento
       ═══════════════════════════════════════ */
    .box-key {{
        margin: 0.7em 0;
        padding: 0.5em 1em;
        border-left: 4px solid {accent};
        background: linear-gradient(90deg, {accent}0a 0%, transparent 100%);
        page-break-inside: avoid;
        font-size: 10pt;
    }}
    .box-key p {{
        margin: 0.15em 0;
    }}

    /* ═══════════════════════════════════════
       CRONOLOGIA — timeline con pallini
       ═══════════════════════════════════════ */
    .cronologia-item {{
        margin: 0.35em 0;
        padding: 0.15em 0 0.15em 1.2em;
        border-left: 2px solid {accent}30;
        font-size: 10pt;
        position: relative;
    }}
    .cronologia-item::before {{
        content: "";
        position: absolute;
        left: -4px;
        top: 0.55em;
        width: 6px;
        height: 6px;
        background: {accent};
        border-radius: 50%;
    }}
    .cronologia-anno {{
        font-weight: bold;
        color: {accent};
        font-family: 'Georgia', serif;
        font-size: 10.5pt;
    }}

    /* ═══════════════════════════════════════
       GLOSSARIO — stile dizionario
       ═══════════════════════════════════════ */
    .glossario-item {{
        margin: 0.35em 0;
        padding: 0.25em 0.5em;
        border-bottom: 1px dotted #e0ddd5;
        font-size: 10pt;
    }}
    .glossario-termine {{
        color: {accent};
        font-size: 10.5pt;
    }}

    /* ═══════════════════════════════════════
       OPERE CITATE — bibliografia
       ═══════════════════════════════════════ */
    .opere-item {{
        margin: 0.25em 0;
        padding-left: 1.2em;
        text-indent: -1.2em;
        font-size: 9.5pt;
        color: #555;
    }}

    /* ═══════════════════════════════════════
       TABELLA CONCETTI — scheda riassuntiva
       ═══════════════════════════════════════ */
    .concept-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 1em 0;
        page-break-inside: avoid;
        font-size: 9.5pt;
    }}
    .concept-table th {{
        background-color: {primary_color};
        color: white;
        padding: 7px 12px;
        text-align: left;
        font-family: 'Georgia', serif;
        font-size: 9.5pt;
        font-weight: normal;
        letter-spacing: 0.8pt;
    }}
    .concept-table td {{
        border: 1px solid #d4d0c8;
        padding: 5px 12px;
        vertical-align: top;
    }}
    .concept-table tr:nth-child(even) td {{
        background-color: #f8f6f0;
    }}

    /* ═══════════════════════════════════════
       DOMANDE — box Q&A
       ═══════════════════════════════════════ */
    .qa-block {{
        margin: 1em 0;
        padding: 0.5em 1em;
        border-left: 4px solid {accent};
        background-color: #f8f6f0;
        page-break-inside: avoid;
    }}
    .question {{
        font-weight: bold;
        font-size: 10.5pt;
        margin-bottom: 0.25em;
        color: #1a2744;
    }}
    .answer {{
        font-size: 10pt;
        color: #444;
        line-height: 1.5;
    }}

    /* ═══════════════════════════════════════
       CITAZIONI
       ═══════════════════════════════════════ */
    blockquote {{
        margin: 0.8em 0;
        padding: 0.4em 1em 0.4em 1.5em;
        border-left: 3px solid {accent};
        background: #f8f6f0;
        font-style: italic;
        color: #555;
        font-size: 10pt;
    }}

    /* ═══════════════════════════════════════
       UTILITY
       ═══════════════════════════════════════ */
    .pagebreak {{
        page-break-after: always;
    }}
    strong {{ font-weight: bold; color: {primary_color}; }}
    em {{ font-style: italic; }}
    {cover_css}
    {header_css}
    {decor_css}
    """

    # Running header dinamico
    titolo_breve = html_mod.escape(titolo[:60])
    running_header = f"""
    @page {{
        @top-left {{
            content: "{titolo_breve}";
        }}
        @top-right {{
            content: "{primo_titolo}";
        }}
    }}
    """

    html_doc = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>{html_mod.escape(titolo)} — Riassunto</title>
<style>{css}
{running_header}</style>
</head>
<body>
{chr(10).join(body_parts)}
</body>
</html>"""

    # Salva HTML
    html_path = output_path.replace(".pdf", ".htm").replace(".docx", ".htm")
    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    # Esporta PDF via WeasyPrint
    pdf_path = output_path.replace(".docx", ".pdf")
    try:
        from weasyprint import HTML

        HTML(string=html_doc).write_pdf(pdf_path)
        pdf_size = os.path.getsize(pdf_path) / 1024
        print(f"  PDF salvato: {os.path.basename(pdf_path)} ({pdf_size:.0f} KB)")
    except Exception as e:
        print(f"  WeasyPrint fallito ({str(e)[:60]}), fallback Word...")
        try:
            import win32com.client

            word = win32com.client.Dispatch("Word.Application")
            word.Visible = False
            word.DisplayAlerts = False
            d = word.Documents.Open(os.path.abspath(html_path))
            d.SaveAs(os.path.abspath(pdf_path), FileFormat=17)
            d.Close()
            word.Quit()
            pdf_size = os.path.getsize(pdf_path) / 1024
            print(
                f"  PDF salvato via Word: {os.path.basename(pdf_path)} ({pdf_size:.0f} KB)"
            )
        except Exception as e2:
            print(f"  Word fallito: {str(e2)[:60]}")

    # Pulisci HTML temporaneo
    if os.path.exists(html_path):
        os.remove(html_path)

    # Conta caratteri dal testo originale (per report)
    total = len(essay)
    print(f"  {total:,} car (~{total // 2500} pagine)")


# ─────────── PIPELINE COMPLETA ───────────


def processa_libro(
    file_path,
    lingua="it",
    cartella_uscita="riassunti 2.0",
    syllabus=None,
    deep_scan=False,
    stats=False,
):
    """Pipeline completa: 4 micro-skill + SCOUT per filtro syllabus.

    syllabus: dict con { "capitoli": [1,2,3], "letture": [1,2,3], "pagine": [(7,32)] }
              oppure None per includere tutto.
    deep_scan: forza OCR anche su PDF con testo rilevato.
    stats: stampa statistiche a fine elaborazione.
    """
    fp = Path(file_path)
    if not fp.exists():
        print(f"ERRORE: {fp} non trovato")
        return

    base = os.path.dirname(os.path.abspath(file_path))
    out_dir = os.path.join(base, cartella_uscita)
    os.makedirs(out_dir, exist_ok=True)

    t0 = time.time() if stats else None
    pagine_scansionate = 0

    print(f"\n{'=' * 60}")
    print(f"📚 {fp.name}")
    if syllabus:
        parti = []
        if syllabus.get("capitoli"):
            parti.append(f"Capp. {', '.join(str(x) for x in syllabus['capitoli'])}")
        if syllabus.get("letture"):
            parti.append(f"Lett. {', '.join(str(x) for x in syllabus['letture'])}")
        if syllabus.get("pagine"):
            parti.append(
                f"Pagg. {', '.join(f'{s}-{e}' for s, e in syllabus['pagine'])}"
            )
        print(f"📋 Syllabus: {'; '.join(parti)}")
    print(f"{'=' * 60}")

    # FASE 0: SCOUT — Estrai pagine una per una con pdfplumber
    print("\n🔍 [FASE 0] Scout — Estrazione pagina per pagina")
    pagine_testo = {}
    pagine_filtrate_da_toc = False

    ext = fp.suffix.lower()
    if ext == ".md":
        with open(file_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
        num_pages = max(1, len(raw) // 2500)
        pagine_testo[0] = raw
    elif ext == ".pdf":
        import pdfplumber

        with pdfplumber.open(str(fp)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text()
                if t and t.strip():
                    pagine_testo[i] = t
        num_pages = len(pdf.pages)
        print(f"  Estratte {len(pagine_testo)} pagine con testo via pdfplumber")
    elif ext in (".epub", ".mobi", ".azw", ".azw3"):
        try:
            import ebooklib
            from ebooklib import epub
            from bs4 import BeautifulSoup

            book = epub.read_epub(str(fp))
            raw = ""
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    raw += soup.get_text() + "\n\n"
            num_pages = max(1, len(raw) // 2500)
            pagine_testo[0] = raw
            print(f"  Estratto: {len(raw)} car via ebooklib ({num_pages} pp stimate)")
        except ImportError:
            print("  ebooklib non installato. Installa: pip install ebooklib beautifulsoup4")
            return
    elif ext in (".docx", ".doc"):
        try:
            from docx import Document

            doc = Document(str(fp))
            raw = "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            num_pages = max(1, len(raw) // 2500)
            pagine_testo[0] = raw
            print(f"  Estratto: {len(raw)} car via python-docx ({num_pages} pp stimate)")
        except ImportError:
            print("  python-docx non installato. Installa: pip install python-docx")
            return
    elif ext in (".html", ".htm"):
        try:
            from bs4 import BeautifulSoup

            with open(file_path, encoding="utf-8", errors="replace") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
            raw = soup.get_text()
            num_pages = max(1, len(raw) // 2500)
            pagine_testo[0] = raw
            print(f"  Estratto: {len(raw)} car via BeautifulSoup ({num_pages} pp stimate)")
        except ImportError:
            print("  beautifulsoup4 non installato. Installa: pip install beautifulsoup4")
            return
    elif ext == ".rtf":
        try:
            import stripmagic
            with open(file_path, encoding="utf-8", errors="replace") as f:
                raw = stripmagic.strip(f.read())
            num_pages = max(1, len(raw) // 2500)
            pagine_testo[0] = raw
            print(f"  Estratto: {len(raw)} car via stripmagic ({num_pages} pp stimate)")
        except ImportError:
            print("  stripmagic non installato. Installa: pip install stripmagic")
            return
    else:
        raw, num_pages = diagnostica_e_estrai(str(fp), deep_scan=deep_scan)
        pagine_testo[0] = raw

    if not pagine_testo:
        print("ERRORE: Nessun testo estratto")
        return

    # FASE 0b: CALCOLA OFFSET tra pagine PDF e pagine reali
    offset = 0
    offset_calcolato = False
    toc_pagine = {}
    if syllabus and syllabus.get("pagine"):
        # Campiona le prime 30 pagine con testo per trovare numeri di pagina reali
        pagine_campionate = sorted(pagine_testo.keys())[:30]
        sequenze_trovate = []

        for pdf_pg in pagine_campionate:
            testo = pagine_testo[pdf_pg]
            # Cerca numeri isolati nelle ultime/intime righe della pagina
            righe = testo.strip().split("\n")
            for riga in righe[-5:]:  # ultime 5 righe
                riga = riga.strip()
                # Pattern: numero isolato di 1-4 cifre
                m = re.match(r"^(\d{1,4})\s*$", riga)
                if m:
                    sequenze_trovate.append((pdf_pg, int(m.group(1))))
                    break
            if len(sequenze_trovate) >= 3:
                # Verifica che sia una sequenza coerente (1,2,3 o I,II,III)
                ultime = sequenze_trovate[-3:]
                if (
                    ultime[1][1] - ultime[0][1] == 1
                    and ultime[2][1] - ultime[1][1] == 1
                ):
                    offset = ultime[0][0] - ultime[0][1]
                    offset_calcolato = True
                    print(
                        f"  Offset calcolato: PDF pagina {ultime[0][0]} = stampata {ultime[0][1]} → offset {offset}"
                    )
                    break

    if not offset_calcolato and syllabus:
        # Fallback: cerca TOC con LLM
        print("  Offset non trovato numericamente. Ricerca TOC semantico...")
        prime_pagine = "\n\n".join(
            [pagine_testo.get(i, "") for i in sorted(pagine_testo.keys())[:20]]
        )
        toc_prompt = (
            "Analizza le PRIME PAGINE di un libro. Cerca l'INDICE/SOMMARIO.\n"
            "Per ogni voce, restituisci: CAPITOLO [X]: [pagina]\n"
            "Le pagine iniziali (introduzione, prefazione) hanno spesso numeri romani (I, II, III...).\n"
            "Rispondi SOLO con l'elenco.\n\n" + prime_pagine[:20000]
        )
        try:
            resp = requests.post(
                f"{OLLAMA}/api/chat",
                json={
                    "model": "deepseek-v4.1-flash:cloud",
                    "messages": [{"role": "user", "content": toc_prompt}],
                    "options": {"num_ctx": 65536, "temperature": 0.1},
                    "stream": False,
                },
                timeout=120,
            )
            toc_raw = resp.json().get("message", {}).get("content", "")
            print(f"  TOC rilevato:\n{toc_raw[:500]}")

            # Parsing TOC: estrai {nome_capitolo: pagina_reale}
            toc_pagine = {}
            for line in toc_raw.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # Pattern per "CAPITOLO X: PAGINA" (solo numeri)
                m = re.search(
                    r"(?:CAPITOLO|Cap\.)\s+(\d+)\s*[:\-–]\s*(\d+)\s*$",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    k, v = m.group(1), int(m.group(2))
                    if k not in toc_pagine or v < toc_pagine[k]:
                        toc_pagine[k] = v
                    continue
                # Pattern per "LETTURA X: PAGINA"
                m = re.search(
                    r"(?:Lettura|Reading)\s+(\d+)\s*[:\-–]\s*(\d+)\s*$",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    k, v = m.group(1), int(m.group(2))
                    toc_pagine[f"L{m.group(1)}"] = v  # lettura con prefisso L
                    continue
                # Pattern: "X. TITOLO: PAGINA" (numero-punto all'inizio)
                m = re.match(r"^(\d{1,3})\.\s+(?:.*?)\s*[:\-–]\s*(\d+)\s*$", line)
                if m:
                    k, v = m.group(1), int(m.group(2))
                    if k not in toc_pagine or v < toc_pagine[k]:
                        toc_pagine[k] = v
                    continue
                # Pattern 2: "CAPITOLO X: PAGINA" (semplice senza titolo)
                m = re.search(
                    r"(?:CAPITOLO|Lettura|Reading)\s+(\d+)\s*[:\-–]\s*(\d+)\s*$",
                    line,
                    re.IGNORECASE,
                )
                if m:
                    toc_pagine[m.group(1)] = int(m.group(2))
                    continue
                # Pattern 3: "X. TITOLO: PAGINA" (numero-punto all'inizio)
                m = re.match(r"^(\d{1,3})\.\s+(?:.*?)\s*[:\-–]\s*(\d+)\s*$", line)
                if m:
                    toc_pagine[m.group(1)] = int(m.group(2))
                    continue
                # Pattern 4: "X: PAGINA" (numero semplice all'inizio riga)
                m = re.match(r"^(\d{1,3})\s*[:\-–]\s*(\d+)\s*$", line)
                if m:
                    toc_pagine[m.group(1)] = int(m.group(2))

            print(f"  TOC pagine: {toc_pagine}")

            # Mappa pagine reali a pagine PDF cercando nel testo
            if toc_pagine:
                # Trova offset dal primo capitolo
                cap1_label = None
                for label in toc_pagine:
                    if label in ["1", "I", "1"]:
                        cap1_label = label
                        break

                if cap1_label is None:
                    cap1_label = min(toc_pagine.keys(), key=lambda k: toc_pagine[k])

                real_page = toc_pagine[cap1_label]
                cap_number = {
                    "I": 1,
                    "II": 2,
                    "III": 3,
                    "IV": 4,
                    "V": 5,
                    "VI": 6,
                    "VII": 7,
                    "VIII": 8,
                    "IX": 9,
                    "X": 10,
                    "XI": 11,
                    "XII": 12,
                    "XIII": 13,
                }.get(
                    cap1_label.upper(),
                    int(cap1_label) if cap1_label.isdigit() else None,
                )

                if cap_number is not None:
                    # Scansiona le prime 50 pagine PDF per trovare il titolo del capitolo
                    for pdf_pg in sorted(pagine_testo.keys())[:50]:
                        testo = pagine_testo[pdf_pg][:400]
                        if re.search(
                            rf"(?:CAPITOLO|Capitolo|Cap\.)\s+{cap_number}\b",
                            testo,
                            re.IGNORECASE,
                        ):
                            offset = pdf_pg - (real_page - 1)
                            offset_calcolato = True
                            print(
                                f"  Offset calcolato: PDF pg {pdf_pg} = reale {real_page} (Cap.{cap_number}) → offset {offset}"
                            )
                            break

                # Costruisci mappa capitoli in pagine PDF
                if offset_calcolato:
                    capitoli_pdf = {}
                    for label, real_pg in sorted(
                        toc_pagine.items(), key=lambda x: x[1]
                    ):
                        pdf_pg = real_pg + offset
                        capitoli_pdf[label] = pdf_pg
                    print(
                        f"  Capitoli mappati a PDF: {dict(list(capitoli_pdf.items())[:5])}..."
                    )

                    # Filtra pagine per syllabus
                    capi_richiesti = set(syllabus.get("capitoli", []))
                    letture_richieste = set(syllabus.get("letture", []))
                    pagine_da_tenere = set()

                    # Trova intervalli per capitoli richiesti
                    toc_sorted = sorted(toc_pagine.items(), key=lambda x: x[1])
                    for i, (label, real_start) in enumerate(toc_sorted):
                        if i + 1 < len(toc_sorted):
                            real_end = toc_sorted[i + 1][1] - 1
                        else:
                            real_end = real_start + 30

                        pdf_start = real_start + offset
                        pdf_end = real_end + offset

                        # Determina se questo capitolo è richiesto
                        num = {
                            "I": 1,
                            "II": 2,
                            "III": 3,
                            "IV": 4,
                            "V": 5,
                            "VI": 6,
                            "VII": 7,
                            "VIII": 8,
                            "IX": 9,
                            "X": 10,
                            "XI": 11,
                            "XII": 12,
                            "XIII": 13,
                        }.get(label.upper(), int(label) if label.isdigit() else None)

                        is_lettura = (
                            "LETTURA" in label
                            or "READING" in label
                            or "Lettur" in label
                        )
                        is_richiesto = False
                        if is_lettura and num in letture_richieste:
                            is_richiesto = True
                        elif not is_lettura and num in capi_richiesti:
                            is_richiesto = True

                        if is_richiesto:
                            pagine_da_tenere.update(range(pdf_start, pdf_end + 1))
                            print(
                                f"  📗 Includo: {label} → PDF pp.{pdf_start}-{pdf_end}"
                            )
                        else:
                            print(
                                f"  📕 Escludo: {label} → PDF pp.{pdf_start}-{pdf_end}"
                            )

                    if pagine_da_tenere:
                        pagine_testo = {
                            k: v
                            for k, v in pagine_testo.items()
                            if k in pagine_da_tenere
                        }
                        print(f"  🔍 Dopo filtro TOC: {len(pagine_testo)} pagine")

                        # Salta il vecchio filtro syllabus
                        pagine_filtrate_da_toc = True

        except Exception as e:
            print(f"  TOC LLM fallito: {e}")
            pagine_filtrate_da_toc = False

    if not offset_calcolato and not toc_pagine:
        pagine_filtrate_da_toc = False

    # FASE 1: FILTRA PAGINE per SYLLABUS (solo se TOC non ha gia filtrato)
    if (
        not pagine_filtrate_da_toc
        and syllabus
        and (
            syllabus.get("capitoli")
            or syllabus.get("letture")
            or syllabus.get("pagine")
        )
    ):
        pagine_da_tenere = set()

        # Filtro per capitoli con regex diretta sul testo pagina per pagina
        capi_richiesti = set(syllabus.get("capitoli", []))
        letture_richieste = set(syllabus.get("letture", []))
        capitoli_trovati = {}
        cap_corrente = None

        for pdf_pg in sorted(pagine_testo.keys()):
            testo = pagine_testo[pdf_pg][:300]
            m = re.search(r"(?:CAPITOLO|Capitolo|Cap\.)\s+(\d+)", testo, re.IGNORECASE)
            if m:
                num = int(m.group(1))
                if cap_corrente is not None and cap_corrente in capitoli_trovati:
                    capitoli_trovati[cap_corrente] = (
                        capitoli_trovati[cap_corrente][0],
                        pdf_pg - 1,
                    )
                cap_corrente = num
                if num not in capitoli_trovati:
                    capitoli_trovati[num] = (pdf_pg, pdf_pg + 20)

        if cap_corrente and cap_corrente in capitoli_trovati:
            capitoli_trovati[cap_corrente] = (
                capitoli_trovati[cap_corrente][0],
                max(pagine_testo.keys()),
            )

        for cap_num, (start, end) in capitoli_trovati.items():
            include = cap_num in capi_richiesti
            print(
                f"  {'📗' if include else '📕'} Capitolo {cap_num}: PDF pp.{start}-{end}"
            )
            if include:
                pagine_da_tenere.update(range(start, end + 1))

        # Cerca anche Letture
        lettura_corrente = None
        letture_trovate = {}
        for pdf_pg in sorted(pagine_testo.keys()):
            testo = pagine_testo[pdf_pg][:300]
            m = re.search(r"(?:Lettura|Reading|Lett\.)\s+(\d+)", testo, re.IGNORECASE)
            if m:
                num = int(m.group(1))
                if lettura_corrente is not None and lettura_corrente in letture_trovate:
                    letture_trovate[lettura_corrente] = (
                        letture_trovate[lettura_corrente][0],
                        pdf_pg - 1,
                    )
                lettura_corrente = num
                if num not in letture_trovate:
                    letture_trovate[num] = (pdf_pg, pdf_pg + 10)

        if lettura_corrente and lettura_corrente in letture_trovate:
            letture_trovate[lettura_corrente] = (
                letture_trovate[lettura_corrente][0],
                max(pagine_testo.keys()),
            )

        for num, (start, end) in letture_trovate.items():
            include = num in letture_richieste
            print(f"  {'📗' if include else '📕'} Lettura {num}: PDF pp.{start}-{end}")
            if include:
                pagine_da_tenere.update(range(start, end + 1))

        if pagine_da_tenere:
            pagine_testo = {
                k: v for k, v in pagine_testo.items() if k in pagine_da_tenere
            }
            print(
                f"  🔍 Dopo filtro syllabus: {len(pagine_testo)} pagine su {num_pages}"
            )

    # Assembla testo filtrato
    raw = "\n\n".join(
        [f"\n\n[PAGINA {k}]\n\n{v}" for k, v in sorted(pagine_testo.items())]
    )

    if not raw or len(raw) < 100:
        print("ERRORE: Testo insufficiente dopo filtro syllabus")
        return

    # SKILL 2: Il Chirurgo
    print("\n🟢 [2/4] Il Chirurgo — Chunking con overlap")
    chunks = chunking_con_overlap(raw)

    # Rileva pagine PDF coperte da ogni chunk
    for chunk in chunks:
        pagine = [int(m) for m in re.findall(r"\[PAGINA (\d+)\]", chunk["text"])]
        chunk["pdf_pages"] = (min(pagine), max(pagine)) if pagine else None

    # ── HYBRID TOC: FILTRO SYLLABUS ──
    desc_syllabus = ""
    if syllabus and (
        syllabus.get("capitoli") or syllabus.get("letture") or syllabus.get("pagine")
    ):
        # Costruisci descrizione syllabus per il prompt Map
        parti = []
        if syllabus.get("capitoli"):
            parti.append(f"Capitoli: {', '.join(str(x) for x in syllabus['capitoli'])}")
        if syllabus.get("letture"):
            parti.append(f"Letture: {', '.join(str(x) for x in syllabus['letture'])}")
        if syllabus.get("pagine"):
            parti.append(f"Pagine: {', '.join(f'{s}-{e}' for s, e in syllabus['pagine'])}")
        desc_syllabus = "; ".join(parti)

        # Step 1: LLM TOC sulle prime pagine
        prime_pagine = raw[:50000]
        toc_prompt = (
            "Analizza le PRIME PAGINE di un libro. Cerca il TABLE OF CONTENTS / INDICE.\n"
            "Per ogni voce dell'indice, restituisci:\n"
            "CAPITOLO [numero/romano]: [pagina]\n\n"
            "Cerca anche eventuali LETTURE (Reading/Lettura).\n"
            "Le pagine dell'introduzione/prefazione sono spesso in numeri romani (I, II, III...).\n"
            "Rispondi SOLO con l'elenco, niente spiegazioni.\n\n"
            "PRIME PAGINE:\n" + prime_pagine[:25000]
        )
        struttura_raw = ""
        try:
            resp = requests.post(
                f"{OLLAMA}/api/chat",
                json={
                    "model": "deepseek-v4.1-flash:cloud",
                    "messages": [{"role": "user", "content": toc_prompt}],
                    "options": {"num_ctx": 65536, "temperature": 0.1},
                    "stream": False,
                },
                timeout=120,
            )
            struttura_raw = resp.json().get("message", {}).get("content", "")
            print(f"  Struttura rilevata:\n{struttura_raw[:600]}")
        except Exception as e:
            print(f"  TOC LLM fallito: {e}")

        # Step 2: Parsing TOC → {label: real_page}
        toc_map = {}
        # Pattern flessibile: matcha "X - Titolo: pagina" o "Capitolo X: pagina"
        for line in struttura_raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Pattern 1: "CAPITOLO/Lettura X: pagina" o "X - Titolo: pagina"
            m = re.search(
                r"(?:Capitolo|Cap\.|Lettura|Reading|Sezione)\s+([IVXLCDM\d]+)\s*[:\-–]\s*(\d+)",
                line,
                re.IGNORECASE,
            )
            if m:
                toc_map[m.group(1).upper()] = int(m.group(2))
                continue
            # Pattern 2: "I - TITOLO: 5" (capitolo romano/arabo all'inizio riga)
            m = re.match(
                r"([IVXLCDM\d]{1,4})\s*[:\-–\.]\s+(?:.*?)\s*[:\-–]\s*(\d+)\s*$", line
            )
            if m:
                toc_map[m.group(1).upper()] = int(m.group(2))
                continue
            # Pattern 3: "PREMESSA: VII" (parole con pagina romana)
            for numeral in ["VII", "VI", "IX", "VIII", "X", "XI", "XII", "XIII"]:
                if numeral in line and re.search(rf":\s*{numeral}\s*$", line):
                    toc_map[numeral] = line.split(":")[0].strip()[:20]
                    break

        print(f"  TOC mappa: {toc_map}")

        # Step 3: Costruisci elenco pagine PDF da tenere
        pagine_da_tenere = set()

        # Aggiungi tutte le pagine del PDF (default) se il syllabus richiede capitoli specifici
        if toc_map:
            # Capitoli richiesti
            richiesti = set()
            for c in syllabus.get("capitoli", []):
                richiesti.add(str(c).upper())
            for l in syllabus.get("letture", []):
                richiesti.add(str(l).upper())

        # SKILL 3: L'Equalizzatore
    print("\n🟢 [3/4] L'Equalizzatore — Map-Reduce")

    # Calcolo adattivo pagine target
    raw_chars = len(raw)
    raw_pages = max(1, raw_chars // 2500)  # stima pagine originali
    if raw_pages < 50:
        target_pages = max(3, int(raw_pages * 0.35))  # libri piccoli: 35%
    elif raw_pages < 200:
        target_pages = max(10, int(raw_pages * 0.25))  # libri medi: 25%
    else:
        target_pages = min(
            50, max(20, int(raw_pages * 0.12))
        )  # libri grandi: 12%, max 50
    print(
        f"  Pagine originali stimate: ~{raw_pages}pp → target output: ~{target_pages}pp"
    )

    prompt = PROMPT_MAP_EN_SEMPLICE if lingua == "en" else PROMPT_MAP_SEMPLICE
    # NON sostituire {target} qui — lo facciamo per-chunk

    # Checkpoint
    book_id = re.sub(r"[^a-zA-Z0-9_-]", "", fp.stem.replace(" ", "_")[:50])
    cp_file = os.path.join(base, "checkpoints", f"{book_id}_v6_checkpoint.json")
    os.makedirs(os.path.join(base, "checkpoints"), exist_ok=True)

    results = []
    if os.path.exists(cp_file):
        saved = json.load(open(cp_file, encoding="utf-8"))
        if saved.get("total") == len(chunks):
            results = saved.get("results", [])
            print(f"  Checkpoint: {len(results)}/{len(chunks)}")

    done_ids = {r["chunk_id"] for r in results}

    # Target per chunk in caratteri
    total_tok = sum(c["token_count"] for c in chunks)
    target_chars_total = target_pages * 2500

    for chunk in chunks:
        cid = chunk["id"]
        if cid in done_ids:
            continue

        # Target proporzionale per questo chunk
        chunk_target = int(target_chars_total * chunk["token_count"] / total_tok)
        chunk_target = max(chunk_target, 3000)
        chunk_pages = max(1, chunk_target // 2500)

        prompt_chunk = prompt.replace(
            "{target}", f"{chunk_pages} pagine (circa {chunk_target} caratteri)"
        )

        # Inietta syllabus nel prompt Map se presente
        if desc_syllabus:
            prompt_chunk += f"\n\nISTRUZIONI SUL PROGRAMMA D'ESAME:\n{desc_syllabus}\n\nSe il testo di questo blocco NON corrisponde a quanto richiesto dal programma, ignoralo e restituisci '[SKIP]'. Se invece corrisponde, riassumilo normalmente."

        print(
            f"  Map {cid + 1}/{len(chunks)} ({chunk['token_count']} tok, target ~{chunk_pages}pp)..."
        )
        # Limite duro: 2x il target per evitare esplosioni (tipo Cristoforo I: 193K invece di 17K)
        max_chars = chunk_target * 2
        out = equalizzatore_map(chunk, prompt_chunk, chunk_index=cid, max_chars=max_chars)
        if out:
            if _contiene_skip(out.get("summary", "")):
                print(f"    ⚠ Chunk {cid + 1} saltato (nessun contenuto utile)")
                continue
            out["chunk_id"] = cid
            results.append(out)
            json.dump(
                {"total": len(chunks), "results": results},
                open(cp_file, "w", encoding="utf-8"),
                ensure_ascii=False,
                indent=2,
            )
            print(f"    Fatto: {len(out['summary'])} car")

    if not results:
        print("ERRORE: Nessun chunk processato")
        return

    print(f"  Completati {len(results)}/{len(chunks)} chunk")

    # Reduce
    essay = equalizzatore_reduce(results)

    # Metadati per copertina
    titolo_libro = fp.stem
    autore_libro = "Autore sconosciuto"
    if fp.suffix.lower() == ".pdf":
        titolo_libro, autore_libro = estrai_metadati(str(fp))
        print(f"  Metadati: {titolo_libro[:60]} — {autore_libro[:40]}")

    # SKILL 4: L'Impaginatore
    print(f"\n🟢 [4/4] L'Impaginatore — Export .docx")
    out_name = f"Riassunto_{book_id}.docx"
    out_path = os.path.join(out_dir, out_name)
    # Rilevamento tema automatico
    theme = rileva_tema(str(fp), essay)

    # Boldify intelligente: applica **grassetto** alle entità conosciute
    all_entities = {"persone": set(), "date": set(), "opere": set()}
    for r in results:
        for cat in ["persone", "date", "opere"]:
            for ent in r.get("entities", {}).get(cat, []):
                e = ent.strip().rstrip(".,;:")
                if e and len(e) > 2:
                    all_entities[cat].add(e)
    essay = boldify_intelligente(essay, all_entities)

    impaginatore_html(
        essay, out_path, titolo_libro, autore_libro, theme=theme
    )

    entities_path = out_path.replace(".docx", "_entities.json")
    with open(entities_path, "w", encoding="utf-8") as f:
        json.dump(
            {k: sorted(v) for k, v in all_entities.items()},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"  Entità salvate: {sum(len(v) for v in all_entities.values())} termini")

    print(f"\n{'=' * 60}")
    print(f"✅ COMPLETATO: {out_path}")
    print(f"{'=' * 60}")

    # Stats
    if stats and t0:
        elapsed = time.time() - t0
        print(f"\n📊 STATS: {num_pages} pp | {len(chunks)} chunk | {elapsed:.0f}s")

    # Export PDF via Word
    pdf_path = out_path.replace(".docx", ".pdf")
    try:
        import win32com.client

        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        doc_word = word.Documents.Open(os.path.abspath(out_path))
        doc_word.SaveAs(os.path.abspath(pdf_path), FileFormat=17)  # 17 = PDF
        doc_word.Close()
        word.Quit()
        pdf_size = os.path.getsize(pdf_path) / 1024
        print(f"  PDF salvato: {os.path.basename(pdf_path)} ({pdf_size:.0f} KB)")
    except Exception as e:
        print(f"  PDF export via Word non disponibile (il PDF è già stato generato da WeasyPrint)")

    # Pulisci checkpoint solo dopo TUTTI gli export
    if os.path.exists(cp_file):
        os.remove(cp_file)
        print("  Checkpoint pulito.")


# BoldHacker disattivato — grassetti gestiti via ** nel testo → HTML <strong>
# print("  Grassetti integrati nell'HTML via ** → <strong>")


# ─────────── MAIN ───────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Mega-Skill Riassunto Universitario V8"
    )
    parser.add_argument("file", help="Percorso del file (PDF, EPUB, DOCX, MD, TXT...)")
    parser.add_argument(
        "lingua", nargs="?", default="it", help="Lingua output: it (default) o en"
    )
    parser.add_argument(
        "--deep-scan", action="store_true", help="Forza OCR su tutto il PDF"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Stampa statistiche a fine elaborazione"
    )
    parser.add_argument(
        "--cartella",
        default="riassunti 2.0",
        help="Cartella output (default: riassunti 2.0)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"ERRORE: File non trovato: {args.file}")
        sys.exit(1)

    processa_libro(
        args.file,
        args.lingua,
        args.cartella,
        deep_scan=args.deep_scan,
        stats=args.stats,
    )
