"""
Shared data models for the riassunto-libro pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Chunk:
    """A text chunk with metadata."""
    id: int
    text: str
    token_count: int
    pdf_pages: Optional[tuple[int, int]] = None


@dataclass
class EntitySet:
    """Extracted entities from a text chunk."""
    persone: list[str] = field(default_factory=list)
    date: list[str] = field(default_factory=list)
    opere: list[str] = field(default_factory=list)


@dataclass
class MapResult:
    """Result of mapping (summarizing) a single chunk."""
    chunk_id: int
    summary: str
    entities: EntitySet
    token_count: int
    coverage: int = 100
    integration: str = ""


@dataclass
class ProofreadResult:
    """Result of the proofreading quality check."""
    score: int  # 0-100
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class PipelineResult:
    """Complete pipeline output."""
    essay: str
    entities: EntitySet
    total_chunks: int
    processed_chunks: int
    coverage: float
    output_path: Optional[str] = None
    proofread: Optional[ProofreadResult] = None
    vision_pages: list[int] = field(default_factory=list)
    vision_manifest: Optional[str] = None
