"""
Pipeline orchestrator — connects extract → chunk → map → reduce → render.

Unified entry point replacing:
- processa_libro() from mega_skill.py
- process_book() from pipeline_unificata.py
"""

from pathlib import Path
from typing import Optional
from loguru import logger
from scripts.config import Settings, load_settings
from scripts.models import Chunk, MapResult, EntitySet, PipelineResult
from scripts.extractor import extract_document, estrai_metadati
from scripts.chunker import split_into_chunks
from scripts.llm_engine import map_chunk, reduce_results, boldify_intelligente

# ---------------------------------------------------------------------------
#  Prompt templates (from mega_skill.py lines 354-440)
# ---------------------------------------------------------------------------

PROMPT_MAP_IT = """Riscrivi il testo in italiano SEMPLICE, CONCISO, completo.

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

PROMPT_MAP_EN = """Rewrite in simple, CONCISE, complete Italian.

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


def run_pipeline(
    file_path: str,
    settings: Optional[Settings] = None,
    lingua: str = "it",
    deep_scan: bool = False,
    syllabus: Optional[dict] = None,
) -> PipelineResult:
    """Run the complete pipeline: extract → chunk → map → reduce.

    Args:
        file_path: Path to input document.
        settings: Configuration (loaded from defaults if None).
        lingua: 'it' or 'en' — controls prompt language and entity markers.
        deep_scan: Force OCR even if text detected (PDF only).
        syllabus: Optional dict with 'capitoli', 'letture', 'pagine' filters
                  (reserved for future use, currently logged but not applied).

    Returns:
        PipelineResult with essay text, entities, and stats.

    Raises:
        FileNotFoundError: If file_path does not exist.
        RuntimeError: If no chunks were processed successfully.
    """
    if settings is None:
        settings = load_settings()

    fp = Path(file_path)
    if not fp.exists():
        raise FileNotFoundError(f"File not found: {fp}")

    logger.info(f"Pipeline started: {fp.name}")

    # Log syllabus if provided (reserved for future filtering)
    if syllabus:
        logger.info(f"Syllabus filters provided: {syllabus}")

    # Phase 1: Extract (page-aware: text layer → routed OCR → vision handoff)
    extraction = extract_document(file_path, settings, deep_scan, lingua)
    raw_text = extraction.text
    num_pages = extraction.num_pages
    method = extraction.method
    logger.info(f"Extracted: {len(raw_text)} chars via {method} ({num_pages} pp)")

    if extraction.ocr_pages:
        logger.info(
            f"OCR routed to {len(extraction.ocr_pages)}/{num_pages} pages "
            f"(text layer kept on the rest)"
        )

    if extraction.needs_vision:
        manifest = extraction.vision_manifest
        logger.warning(
            f"Vision lane: {len(extraction.vision_pages)} pages unreadable after OCR "
            f"→ staged at {manifest or extraction.vision_dir}"
        )
        logger.warning(
            "Run the vision pass (read the images, write transcript.json) then "
            "re-run with --vision-transcript to merge a clean text layer."
        )

    if not raw_text.strip():
        raise RuntimeError(
            "No text extracted. For scanned documents run the vision pass on the "
            f"staged pages: {extraction.vision_dir or 'n/a'}"
        )

    # Phase 2: Chunk
    chunks = split_into_chunks(raw_text, settings)
    logger.info(f"Chunked: {len(chunks)} chunks")

    # Phase 3: Map (summarize each chunk)
    prompt_template = PROMPT_MAP_EN if lingua == "en" else PROMPT_MAP_IT
    results: list[MapResult] = []
    for chunk in chunks:
        # Convert Chunk object to dict for map_chunk compatibility
        chunk_dict = {
            "id": chunk.id,
            "text": chunk.text,
            "token_count": chunk.token_count,
        }
        result = map_chunk(
            chunk_dict,
            prompt_template,
            settings,
            chunk_index=chunk.id,
            lang=lingua,
        )
        if result:
            results.append(result)

    if not results:
        raise RuntimeError("No chunks processed successfully")

    logger.info(f"Mapped: {len(results)}/{len(chunks)} chunks")

    # Phase 4: Reduce (concatenate, deduplicate, verify citations)
    essay = reduce_results(results)

    # Phase 5: Boldify — apply **bold** to known entities
    all_entities = EntitySet()
    for r in results:
        all_entities.persone.extend(r.entities.persone)
        all_entities.date.extend(r.entities.date)
        all_entities.opere.extend(r.entities.opere)
    all_entities.persone = list(set(all_entities.persone))
    all_entities.date = list(set(all_entities.date))
    all_entities.opere = list(set(all_entities.opere))

    essay = boldify_intelligente(essay, all_entities)

    # Coverage: average of individual chunk coverage values
    coverage = sum(r.coverage for r in results) / len(results) if results else 0

    # Phase 6: Proofreading
    from scripts.proofreader import auto_critique
    proof_result = auto_critique(PipelineResult(
        essay=essay,
        entities=all_entities,
        total_chunks=len(chunks),
        processed_chunks=len(results),
        coverage=coverage,
    ), settings)
    logger.info(f"Proofreading score: {proof_result.score}/100")

    if proof_result.issues:
        logger.warning(f"Proofreading issues: {proof_result.issues[:3]}")

    if proof_result.suggestions:
        logger.info(f"Proofreading suggestions: {proof_result.suggestions[:3]}")

    if proof_result.score < 60:
        logger.warning(f"Low quality score ({proof_result.score}). Consider reviewing output.")

    return PipelineResult(
        essay=essay,
        entities=all_entities,
        total_chunks=len(chunks),
        processed_chunks=len(results),
        coverage=coverage,
        proofread=proof_result,
        vision_pages=extraction.vision_pages,
        vision_manifest=extraction.vision_manifest,
    )
