"""
Pipeline orchestrator — extract → chunk → map (prose) → merge → synthesis → proofread.

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
    boldify_intelligente,
    build_map_prompt,
    detect_content_type,
    map_chunk,
    reduce_results,
    repair_prose,
    synthesize_essay,
)

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

    # Phase 3: Map (each chunk in prose, focus per content type)
    content_type = detect_content_type(raw_text[:4000])
    prompt_template = build_map_prompt(content_type, lingua)
    logger.info(f"Content type: {content_type}")
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
