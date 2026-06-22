"""Protocol definitions (ports) for the runic.rag Graph-RAG SDK.

Every collaborator the services depend on is described here as a
:class:`typing.Protocol`, enabling constructor injection (DIP) and trivial
fakes in tests. No implementations live in this module.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from runic.rag.domain import (
    Answer,
    Chunk,
    ChunkHit,
    EntityHit,
    ExtractedEntity,
    Extraction,
    RelationHit,
    RetrievalContext,
    ScoredKey,
)

if TYPE_CHECKING:
    from typing import Any

__all__ = [
    "Chunker",
    "Embedder",
    "EntityResolver",
    "Extractor",
    "GraphStore",
    "Reranker",
    "Retriever",
    "Synthesizer",
    "VectorSearcher",
    "Writer",
]


@runtime_checkable
class Chunker(Protocol):
    """Splits raw text into ordered :class:`~runic.rag.domain.Chunk` objects."""

    def split(self, text: str, *, source: str) -> list[Chunk]:
        """Return ordered chunks for *text* tagged with *source*."""
        ...


@runtime_checkable
class Extractor(Protocol):
    """Extracts entities and relations from a single chunk."""

    def extract(self, chunk: Chunk, *, entity_types: list[str]) -> Extraction:
        """Return the :class:`~runic.rag.domain.Extraction` for *chunk*."""
        ...


@runtime_checkable
class Embedder(Protocol):
    """Turns text into dense vectors."""

    @property
    def dimension(self) -> int:
        """The dimensionality of vectors produced by this embedder."""
        ...

    def embed(self, text: str) -> list[float]:
        """Embed a single string."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many strings; result order matches *texts*."""
        ...


@runtime_checkable
class VectorSearcher(Protocol):
    """The narrow vector-search capability the resolver needs (ISP).

    A full :class:`GraphStore` satisfies this, but so does any object exposing
    just ``vector_search`` — keeping :meth:`EntityResolver.find_duplicate`
    decoupled from the rest of the store surface (and trivially fakeable).
    """

    def vector_search(
        self,
        *,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None = None,
    ) -> list[ScoredKey]:
        """KNN search returning scored canonical keys (normalised [0, 1])."""
        ...


@runtime_checkable
class EntityResolver(Protocol):
    """Decides the canonical identity for an extracted entity."""

    def canonical_key(self, entity: ExtractedEntity) -> str:
        """Return the deterministic canonical key for *entity*."""
        ...

    def find_duplicate(
        self, entity: ExtractedEntity, embedding: list[float], store: VectorSearcher
    ) -> str | None:
        """Return the canonical key of an existing duplicate, or None."""
        ...


@runtime_checkable
class Retriever(Protocol):
    """Builds a :class:`~runic.rag.domain.RetrievalContext` for a query."""

    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext:
        """Return the retrieval context for *query*."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Reorders / prunes retrieval contexts by relevance to a query."""

    def rerank(
        self, query: str, contexts: list[RetrievalContext], *, top_k: int
    ) -> RetrievalContext:
        """Return a single reranked, trimmed context."""
        ...


@runtime_checkable
class Synthesizer(Protocol):
    """Produces a cited :class:`~runic.rag.domain.Answer` from context."""

    def synthesize(self, query: str, context: RetrievalContext) -> Answer:
        """Return the synthesized answer for *query* given *context*."""
        ...


@runtime_checkable
class Writer(Protocol):
    """A single graph unit-of-work yielded by :meth:`GraphStore.writer`.

    All methods stage changes against one underlying OGM session; the changes
    are committed when the surrounding context manager exits cleanly.
    """

    def add_chunk(self, chunk_node: Any) -> None:
        """Add (or merge) an OGM Chunk node to the graph."""
        ...

    def upsert_entity(
        self,
        key: str,
        name: str,
        type: str,  # noqa: A002 - mirrors domain vocabulary
        description: str,
        embedding: list[float] | None,
    ) -> None:
        """Insert or update an entity identified by its canonical *key*."""
        ...

    def relate(
        self,
        src_key: str,
        rel_type: str,
        dst_key: str,
        description: str,
        confidence: float,
        source_chunk: str,
    ) -> None:
        """Create a typed relation edge between two entities."""
        ...

    def mention(self, chunk_id: str, entity_key: str) -> None:
        """Link a chunk to an entity it mentions."""
        ...


@runtime_checkable
class GraphStore(Protocol):
    """The backend-isolating graph port (concept §9.1).

    One adapter wraps a :class:`runic.ogm.Session` and hides backend dialect
    differences (FalkorDB vs Neo4j vector/fulltext procs, vector index dim).
    """

    def bootstrap_schema(self) -> None:
        """Create entity types and indexes (vector index uses the REAL dim)."""
        ...

    def writer(self) -> AbstractContextManager[Writer]:
        """Return a context manager yielding a :class:`Writer` (one UoW)."""
        ...

    def vector_search(
        self,
        *,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None = None,
    ) -> list[ScoredKey]:
        """KNN search; returns canonical keys with normalized similarity."""
        ...

    def fulltext_search(
        self, *, label: str, prop: str, query: str, k: int
    ) -> list[ScoredKey]:
        """Fulltext search; returns canonical keys with scores."""
        ...

    def get_entities(self, keys: list[str]) -> list[EntityHit]:
        """Hydrate entities for the given canonical keys."""
        ...

    def expand(
        self, keys: list[str], *, max_hops: int
    ) -> tuple[list[EntityHit], list[RelationHit]]:
        """Expand the neighbourhood up to *max_hops* around *keys*."""
        ...

    def chunks_for_entities(self, keys: list[str], *, limit: int) -> list[ChunkHit]:
        """Return chunks mentioning any of the given entity keys."""
        ...
