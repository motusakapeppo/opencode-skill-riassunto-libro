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
from scripts.extractor import extract_document
from scripts.chunker import split_into_chunks
from scripts.llm_engine import (
    map_chunk,
    reduce_results,
    synthesize_essay,
    repair_prose,
    boldify_intelligente,
)

# ---------------------------------------------------------------------------
#  Prompt templates (from mega_skill.py lines 354-440)
# ---------------------------------------------------------------------------

PROMPT_MAP_IT = """Riscrivi il testo in italiano SEMPLICE, CONCISO, completo.

Questo e' un blocco di un libro piu' lungo: verra' fuso con altri blocchi alla fine. Non concludere il discorso e non aggiungere sezioni finali.

Parla come un amico intelligente che spiega a uno stanco dopo lavoro. Frasi corte, parole di tutti i giorni.

TERMINI TECNICI: se usi parole specialistiche (recitativo, monodia, libretto...), aggiungi subito una brevissima spiegazione tra parentesi: "recitativo (canto parlato)".

GRASSETTO INTELLIGENTE: usa **grassetto** per nomi propri, date chiave e concetti portanti. Massimo 2-3 grassetti per paragrafo.

CONTRATTO DI STILE (verificabile):
1. SOLO PROSA. Nessun elenco, nessuna riga che inizi con -, *, •, "1." o "1)".
2. Paragrafi di 3-6 frasi, ognuno legato al precedente da un connettivo ("Per questo", "Di conseguenza", "Allo stesso tempo", "Piu' avanti").
3. VIETATO trascrivere metadati bibliografici: ISSN, DOI, ISBN, numeri di pagina, "vol. II", "pp. 44-51", nomi di collane o riviste. I contenuti si raccontano, non si citano.
4. VIETATE le sezioni finali: niente "Da Ricordare", "Cronologia", "Glossario", "Opere Citati", "Scheda Riassuntiva", "Domande di Verifica". Vengono generate una sola volta, alla fine del libro.
5. VIETATI i titoli-etichetta: "### Concetti chiave", "### Esempi", "### Introduzione", "### Conclusione".
6. Non nominare il supporto: niente "questo blocco", "il testo fornito", "l'autore del brano".
7. COMPLETEZZA: ogni nome, data, concetto, evento deve restare.
8. Lunghezza: circa {target} caratteri. Meglio denso che lungo.

Alla fine del riassunto, obbligatoriamente, il blocco entita':
===ENTITA===
PERSONE: separate da |
DATE: separate da |
OPERE/EVENTI/CONCETTI: separate da |
===FINE ENTITA===

TESTO:
{testo}"""

PROMPT_MAP_EN = """Rewrite in simple, CONCISE, complete Italian.

This is one block of a longer book: it will be merged with other blocks at the end. Do not conclude the argument and do not add closing sections.

Write like a smart friend explaining to a tired friend after work. Short sentences, everyday words.

TECHNICAL TERMS: when you use specialist words (recitative, monody, libretto...), add a quick explanation in parentheses: "recitative (sung speech)".

BOLD: use **word** for proper names, key dates and core concepts. At most 2-3 per paragraph.

STYLE CONTRACT (verifiable):
1. PROSE ONLY. No lists, no line starting with -, *, •, "1." or "1)".
2. Paragraphs of 3-6 sentences, each linked to the previous one by a connective ("For this reason", "As a result", "At the same time", "Later").
3. NEVER transcribe bibliographic metadata: ISSN, DOI, ISBN, page numbers, "vol. II", "pp. 44-51", journal or series names. Content is told, not cited.
4. NO closing sections: no "Da Ricordare", "Cronologia", "Glossario", "Opere Citati", "Scheda Riassuntiva", "Domande di Verifica". They are generated once, at the end of the book.
5. NO label headings: "### Key concepts", "### Examples", "### Introduction", "### Conclusion".
6. Do not name the medium: no "this block", "the provided text", "the author of the passage".
7. COMPLETENESS: every name, date, concept, event must stay.
8. Length: about {target} characters. Dense beats long.

At the end, mandatorily, the entity block:
===ENTITIES===
PEOPLE: separated by |
DATES: separated by |
WORKS/EVENTS/CONCEPTS: separated by |
===END ENTITIES===

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
        raise RuntimeError(
            "No chunks processed successfully. If every call returned an empty "
            "message, raise max_output_tokens (reasoning models spend ~6k tokens "
            "before writing the answer)."
        )

    logger.info(f"Mapped: {len(results)}/{len(chunks)} chunks")

    if len(results) < len(chunks) * 0.5:
        raise RuntimeError(
            f"{len(chunks) - len(results)}/{len(chunks)} chunk tornati vuoti o falliti. "
            "Non proseguo: il saggio perderebbe meta' del libro. "
            "Alza max_output_tokens (default 16000) o controlla la quota Ollama."
        )

    # Phase 4: Merge — strip per-chunk didactic sections, dedupe, mark boundaries
    draft = reduce_results(results, settings)
    logger.info(f"Merged draft: {len(draft):,} chars")

    # Phase 5: Synthesis — prose essay + didactic sections, generated once
    essay = synthesize_essay(draft, settings)
    logger.info(f"Synthesized: {len(essay):,} chars (mode={settings.reduce_mode})")

    # Phase 6: Boldify — apply **bold** to known entities
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

    # Phase 7: Proofreading (LLM criteria + deterministic style metrics)
    from scripts.proofreader import auto_critique
    proof_result = auto_critique(PipelineResult(
        essay=essay,
        entities=all_entities,
        total_chunks=len(chunks),
        processed_chunks=len(results),
        coverage=coverage,
    ), settings)

    # One bounded repair pass if the document came out as a list dump
    if proof_result.must_rewrite and settings.style == "prose":
        logger.warning("Style violation: rewriting the document as prose (one attempt)")
        repaired = repair_prose(essay, settings)
        if repaired:
            repaired = boldify_intelligente(repaired, all_entities)
            check = auto_critique(PipelineResult(
                essay=repaired,
                entities=all_entities,
                total_chunks=len(chunks),
                processed_chunks=len(results),
                coverage=coverage,
            ), settings)
            essay, proof_result = repaired, check

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
