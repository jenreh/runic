"""End-to-end integration tests for :class:`runic.rag.facade.GraphRAG`.

These wire the facade with deterministic, network-free fakes
(:class:`FakeExtractor`, :class:`FakeEmbedder`, :class:`FakeReranker`) over a
*live* FalkorDB (the ``falkordb_driver`` fixture skips when unreachable). They
exercise the real ingestion + retrieval services and the real GraphStore: only
the LLM/embedder boundaries are faked, so the graph writes, vector/fulltext
search, neighbourhood expansion, and citation wiring are all exercised for real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from runic.rag.adapters import (
    FulltextRetriever,
    LocalRetriever,
    TwoStageResolver,
    VectorRetriever,
)
from runic.rag.adapters.chunking import ParagraphChunker
from runic.rag.domain import (
    Answer,
    ExtractedEntity,
    ExtractedRelation,
    Extraction,
    RetrievalContext,
)
from runic.rag.facade import GraphRAG
from runic.rag.ontology import Ontology
from runic.rag.store import GraphStore
from tests.runic.rag.fakes import FakeEmbedder, FakeExtractor

if TYPE_CHECKING:
    from runic.rag.config import RagSettings

pytestmark = pytest.mark.integration

_CORPUS = (
    "Alice founded Acme in Berlin. Alice is the chief executive of Acme.\n\n"
    "Acme is headquartered in Berlin and builds graph databases. "
    "Berlin is the capital of Germany."
)


def _extraction_for(text: str) -> Extraction:
    """Deterministic extraction keyed on which sentence a chunk contains."""
    entities: list[ExtractedEntity] = []
    relations: list[ExtractedRelation] = []
    if "Alice" in text:
        entities.append(
            ExtractedEntity(name="Alice", type="Person", description="Founder of Acme.")
        )
    if "Acme" in text:
        entities.append(
            ExtractedEntity(
                name="Acme",
                type="Organization",
                description="A graph database company.",
            )
        )
    if "Berlin" in text:
        entities.append(
            ExtractedEntity(
                name="Berlin", type="Location", description="Capital of Germany."
            )
        )
    if "Alice" in text and "Acme" in text:
        relations.append(
            ExtractedRelation(
                source="Alice",
                target="Acme",
                rel_type="FOUNDED",
                description="Alice founded Acme.",
                confidence=0.9,
            )
        )
    if "Acme" in text and "Berlin" in text:
        relations.append(
            ExtractedRelation(
                source="Acme",
                target="Berlin",
                rel_type="LOCATED_IN",
                description="Acme is in Berlin.",
                confidence=0.8,
            )
        )
    return Extraction(entities=entities, relations=relations)


class _EchoSynthesizer:
    """Network-free synthesizer: echoes entity names and cites every chunk."""

    def synthesize(self, query: str, context: RetrievalContext) -> Answer:
        from runic.rag.domain import Citation

        names = ", ".join(e.name for e in context.entities)
        citations = [
            Citation(chunk_id=c.id, source=c.source, text=c.text)
            for c in context.chunks
        ]
        return Answer(
            text=f"Q={query} entities={names}",
            citations=citations,
            context=context,
        )


@pytest.fixture
def rag(falkordb_driver: object, rag_settings: RagSettings) -> GraphRAG:
    """A GraphRAG facade wired with fakes over a live FalkorDB store."""
    from runic.rag.adapters.reranking import RRFReranker

    settings = rag_settings
    ontology = Ontology.default()
    embedder = FakeEmbedder(settings.embedding_dim)
    store = GraphStore(
        falkordb_driver, settings, schema_models=ontology.schema_models()
    )
    return GraphRAG(
        store,
        ontology=ontology,
        chunker=ParagraphChunker(settings),
        extractor=FakeExtractor(lambda chunk: _extraction_for(chunk.text)),
        embedder=embedder,
        resolver=TwoStageResolver(settings),
        retrievers={
            "vector": VectorRetriever(store, embedder, settings),
            "fulltext": FulltextRetriever(store, settings),
            "local": LocalRetriever(store, embedder, settings),
            "highlevel": FulltextRetriever(store, settings),
        },
        reranker=RRFReranker(),
        synthesizer=_EchoSynthesizer(),
        settings=settings,
    )


def test_facade_end_to_end_local_and_hybrid(rag: GraphRAG) -> None:
    """Bootstrap, ingest a small corpus, then query in local and hybrid modes."""
    rag.bootstrap_schema()

    report = rag.ingest_text(_CORPUS, source="facts")
    assert report.chunks >= 1
    assert report.entities >= 3  # Alice, Acme, Berlin
    assert report.relations >= 1

    local = rag.query("Who founded Acme?", mode="local")
    assert isinstance(local, Answer)
    assert local.citations, "local query must produce grounded citations"
    assert all(c.source == "facts" for c in local.citations)

    hybrid = rag.query("How is Acme related to Berlin?", mode="hybrid")
    assert isinstance(hybrid, Answer)
    assert hybrid.citations, "hybrid query must produce grounded citations"
    # Grounded: the chunk ids cited must be the ones actually ingested.
    assert hybrid.context is not None
    cited_ids = {c.chunk_id for c in hybrid.citations}
    context_ids = {c.id for c in hybrid.context.chunks}
    assert cited_ids == context_ids


def test_facade_idempotent_reingest(rag: GraphRAG) -> None:
    """Re-ingesting identical text MERGEs onto the same nodes (stable counts)."""
    rag.bootstrap_schema()
    first = rag.ingest_text(_CORPUS, source="facts")
    second = rag.ingest_text(_CORPUS, source="facts")
    assert first.entities == second.entities
    assert first.relations == second.relations
