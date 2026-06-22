"""Frozen value objects for the runic.rag Graph-RAG SDK.

These are immutable pydantic v2 models passed between ports/services. They are
deliberately decoupled from the OGM node models in :mod:`runic.rag.models`
(e.g. the domain :class:`Chunk` is distinct from the OGM ``Chunk`` node).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Answer",
    "Chunk",
    "ChunkHit",
    "Citation",
    "EntityHit",
    "ExtractedEntity",
    "ExtractedRelation",
    "Extraction",
    "RelationHit",
    "RetrievalContext",
    "ScoredKey",
]


class _Frozen(BaseModel):
    """Base for all frozen RAG value objects."""

    model_config = ConfigDict(frozen=True)


# ── Ingestion-side value objects ───────────────────────────────────────────


class Chunk(_Frozen):
    """A contiguous slice of source text produced by a chunker."""

    id: str
    text: str
    seq: int
    source: str


class ExtractedEntity(_Frozen):
    """An entity surfaced by the extractor from a chunk."""

    name: str
    type: str
    description: str = ""


class ExtractedRelation(_Frozen):
    """A directed relation between two extracted entities (by name)."""

    source: str
    target: str
    rel_type: str
    description: str = ""
    confidence: float = 1.0


class Extraction(_Frozen):
    """The full set of entities and relations extracted from one chunk."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


# ── Retrieval-side value objects ───────────────────────────────────────────


class ScoredKey(_Frozen):
    """A canonical key paired with a normalized similarity score in [0, 1]."""

    key: str
    score: float


class EntityHit(_Frozen):
    """An entity returned by retrieval, with its relevance score."""

    canonical_key: str
    name: str
    type: str
    description: str
    score: float


class ChunkHit(_Frozen):
    """A source chunk returned by retrieval, with its relevance score."""

    id: str
    text: str
    source: str
    score: float


class RelationHit(_Frozen):
    """A relation edge discovered while expanding the entity neighbourhood."""

    source_key: str
    target_key: str
    rel_type: str
    description: str


class RetrievalContext(_Frozen):
    """The assembled evidence for a query: entities, chunks, and relations."""

    query: str
    entities: list[EntityHit] = Field(default_factory=list)
    chunks: list[ChunkHit] = Field(default_factory=list)
    relations: list[RelationHit] = Field(default_factory=list)


# ── Answer-side value objects ──────────────────────────────────────────────


class Citation(_Frozen):
    """A reference to a source chunk supporting an answer."""

    chunk_id: str
    source: str
    text: str


class Answer(_Frozen):
    """A synthesized answer with its supporting citations and context."""

    text: str
    citations: list[Citation] = Field(default_factory=list)
    context: RetrievalContext | None = None
