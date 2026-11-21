"""
Text chunking module — splits extracted text into manageable chunks for LLM processing.

Merges chunking logic from:
- mega_skill.py lines 274-349 (chunking_con_overlap)
- pipeline_unificata.py lines 167-236 (split_into_chunks)
- riassumi.py lines 81-130
"""

from pathlib import Path
from typing import Optional
import json
import re
from loguru import logger
from scripts.config import Settings
from scripts.models import Chunk

CHAPTER_PATTERNS = [
    r'^#\s+.+',
    r'^##\s+.+',
    r'^###\s+.+',
    r'^CAPITOLO\s+[IVXLCDM\d]+',
    r'^Capitolo\s+[IVXLCDM\d]+',
    r'^Chapter\s+\d+',
    r'^\d+\.\s+[A-Z]',
    r'^\[PAGINA\s+\d+\]',
]


def find_section_boundaries(text: str) -> list[int]:
    """Find line numbers of section/chapter boundaries.
    
    Returns sorted list of line indices (0-based) where new sections start.
    """
    lines = text.split('\n')
    boundaries = [0]
    for i, line in enumerate(lines):
        for pattern in CHAPTER_PATTERNS:
            if re.match(pattern, line.strip()):
                boundaries.append(i)
                break
    return sorted(set(boundaries))


def build_chunk_with_context(
    current_text: str,
    previous_chunk: Optional[Chunk],
    previous_summary: Optional[str],
    settings,
) -> str:
    """Build chunk text with contextual overlap.
    
    Structure:
    [CONTESTO PRECEDENTE]
    (2-3 sentence summary of previous chunk, if available)
    [FINE CONTESTO]
    
    [NUOVA SEZIONE]
    (current chunk text with N paragraphs overlap from previous chunk)
    """
    parts = []
    
    if previous_summary:
        parts.append("[CONTESTO PRECEDENTE]")
        parts.append(previous_summary)
        parts.append("[FINE CONTESTO]")
        parts.append("")
    
    parts.append(current_text)
    return "\n".join(parts)


def split_into_chunks(text: str, settings: Settings, previous_summaries: Optional[dict[int, str]] = None) -> list[Chunk]:
    """Divide text into chunks, preferring section boundaries.
    
    Algorithm:
    1. Find section boundaries (chapter headings, page markers)
    2. Group consecutive sections until token limit reached
    3. If a single section exceeds max_tokens, split by paragraphs
    4. If a paragraph exceeds max_tokens, split by sentences
    5. Add overlap from previous chunk
    """
    boundaries = find_section_boundaries(text)
    lines = text.split('\n')
    
    # Build sections from boundaries
    sections = []
    for i in range(len(boundaries)):
        start = boundaries[i]
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(lines)
        section_text = '\n'.join(lines[start:end]).strip()
        if section_text:
            sections.append(section_text)
    
    if not sections:
        return []
    
    # Group sections into chunks
    chunks = []
    current_sections = []
    current_tokens = 0
    chunk_id = 0
    
    for section in sections:
        section_tokens = len(section) // 5
        
        if current_tokens + section_tokens > settings.chunk_max_tokens and current_sections:
            # Finalize current chunk
            chunk_text = '\n\n'.join(current_sections)
            prev_summary = previous_summaries.get(chunk_id - 1) if previous_summaries else None
            prev_chunk = chunks[-1] if chunks else None
            chunk_text = build_chunk_with_context(chunk_text, prev_chunk, prev_summary, settings)
            chunks.append(Chunk(id=chunk_id, text=chunk_text, token_count=current_tokens))
            chunk_id += 1
            
            # Overlap: keep last N paragraphs
            overlap_paras = current_sections[-settings.chunk_overlap_paragraphs:] if settings.chunk_overlap_paragraphs > 0 else []
            current_sections = list(overlap_paras)
            current_tokens = sum(len(p) // 5 for p in current_sections)
        
        current_sections.append(section)
        current_tokens += section_tokens
    
    if current_sections:
        chunk_text = '\n\n'.join(current_sections)
        prev_summary = previous_summaries.get(chunk_id - 1) if previous_summaries else None
        prev_chunk = chunks[-1] if chunks else None
        chunk_text = build_chunk_with_context(chunk_text, prev_chunk, prev_summary, settings)
        chunks.append(Chunk(id=chunk_id, text=chunk_text, token_count=current_tokens))
    
    # Handle oversized chunks (single section exceeds max_tokens)
    final_chunks = []
    for chunk in chunks:
        if chunk.token_count <= settings.chunk_max_tokens:
            final_chunks.append(chunk)
        else:
            # Split oversized chunk by paragraphs
            paras = [p.strip() for p in re.split(r"\n\s*\n", chunk.text) if p.strip()]
            sub_current = []
            sub_tokens = 0
            for para in paras:
                pt = len(para) // 5
                if pt > settings.chunk_max_tokens:
                    # Split oversized paragraph by sentences
                    if sub_current:
                        sub_text = '\n\n'.join(sub_current)
                        prev_summary = previous_summaries.get(chunk_id - 1) if previous_summaries else None
                        prev_chunk = final_chunks[-1] if final_chunks else None
                        sub_text = build_chunk_with_context(sub_text, prev_chunk, prev_summary, settings)
                        final_chunks.append(Chunk(id=chunk_id, text=sub_text, token_count=sub_tokens))
                        chunk_id += 1
                        sub_current = []
                        sub_tokens = 0
                    for sent in re.split(r"(?<=[.!?])\s+", para):
                        st = len(sent) // 5
                        if sub_tokens + st > settings.chunk_max_tokens and sub_current:
                            sub_text = '\n\n'.join(sub_current)
                            prev_summary = previous_summaries.get(chunk_id - 1) if previous_summaries else None
                            prev_chunk = final_chunks[-1] if final_chunks else None
                            sub_text = build_chunk_with_context(sub_text, prev_chunk, prev_summary, settings)
                            final_chunks.append(Chunk(id=chunk_id, text=sub_text, token_count=sub_tokens))
                            chunk_id += 1
                            sub_current = []
                            sub_tokens = 0
                        sub_current.append(sent)
                        sub_tokens += st
                elif sub_tokens + pt > settings.chunk_max_tokens and sub_current:
                    sub_text = '\n\n'.join(sub_current)
                    prev_summary = previous_summaries.get(chunk_id - 1) if previous_summaries else None
                    prev_chunk = final_chunks[-1] if final_chunks else None
                    sub_text = build_chunk_with_context(sub_text, prev_chunk, prev_summary, settings)
                    final_chunks.append(Chunk(id=chunk_id, text=sub_text, token_count=sub_tokens))
                    chunk_id += 1
                    sub_current = [para]
                    sub_tokens = pt
                else:
                    sub_current.append(para)
                    sub_tokens += pt
            if sub_current:
                sub_text = '\n\n'.join(sub_current)
                prev_summary = previous_summaries.get(chunk_id - 1) if previous_summaries else None
                prev_chunk = final_chunks[-1] if final_chunks else None
                sub_text = build_chunk_with_context(sub_text, prev_chunk, prev_summary, settings)
                final_chunks.append(Chunk(id=chunk_id, text=sub_text, token_count=sub_tokens))
                chunk_id += 1
    
    # Merge small chunks
    merged = []
    for c in final_chunks:
        if c.token_count < settings.chunk_min_tokens and merged:
            merged[-1].text += "\n\n" + c.text
            merged[-1].token_count += c.token_count
        else:
            merged.append(c)
    
    for i, m in enumerate(merged):
        m.id = i
    
    logger.info(f"Chunked: {len(merged)} chunks (from {len(final_chunks)} raw, {len(sections)} sections)")
    return merged


def save_checkpoint(checkpoint_path: Path, chunks: list[Chunk], results: list[dict]) -> None:
    """Append-only checkpoint save.

    Reads existing checkpoint, merges new results, writes back.
    """
    existing = {}
    if checkpoint_path.exists():
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = {}

    existing["total"] = len(chunks)
    existing["results"] = results

    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def load_checkpoint(checkpoint_path: Path, total_chunks: int) -> tuple[list[dict], set[int]]:
    """Load checkpoint, return (results, done_ids).

    Returns empty lists if checkpoint missing or invalid.
    """
    if not checkpoint_path.exists():
        return [], set()

    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("total") != total_chunks:
            logger.warning(f"Checkpoint total mismatch: {data.get('total')} vs {total_chunks}")
            return [], set()

        results = data.get("results", [])
        done_ids = {r["chunk_id"] for r in results}
        return results, done_ids
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load checkpoint: {e}")
        return [], set()
