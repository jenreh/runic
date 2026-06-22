"""Full Graph-RAG roundtrip across EVERY runic-supported backend.

Parametrised over ``RUNIC_TEST_BACKENDS`` (FalkorDB, Neo4j, Memgraph, ArcadeDB,
Apache AGE). For each reachable backend it bootstraps the schema, ingests a
small corpus (with fake LLM/embeddings — no network), and runs local and hybrid
queries, asserting the writes, retrieval, and provenance all work.

This is the proof that ``runic.rag`` is backend-agnostic: FalkorDB/Neo4j use the
native vector/fulltext procs while Memgraph/ArcadeDB/AGE use the portable
brute-force paths, all behind the same :class:`GraphStore` surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from runic.rag.config import RagSettings
from runic.rag.domain import (
    Answer,
    Citation,
    ExtractedEntity,
    ExtractedRelation,
    Extraction,
    RetrievalContext,
)
from runic.rag.facade import GraphRAG
from runic.rag.ontology import Ontology
from runic.rag.store import GraphStore
from tests._backends import enabled_backends, make_driver, random_graph_name

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.integration

_CORPUS = (
    "Alice founded Acme in Berlin. Alice is the chief executive of Acme.\n\n"
    "Acme is headquartered in Berlin and builds graph databases. "
    "Berlin is the capital of Germany."
)


def _extraction_for(text: str) -> Extraction:
    """Deterministic, network-free extraction keyed on chunk content."""
    entities: list[ExtractedEntity] = []
    relations: list[ExtractedRelation] = []
    if "Alice" in text:
        entities.append(
            ExtractedEntity(name="Alice", type="Person", description="Founder of Acme.")
        )
    if "Acme" in text:
        entities.append(
            ExtractedEntity(
                name="Acme", type="Organization", description="A graph DB company."
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
                source="Alice", target="Acme", rel_type="FOUNDED", confidence=0.9
            )
        )
    if "Acme" in text and "Berlin" in text:
        relations.append(
            ExtractedRelation(
                source="Acme", target="Berlin", rel_type="LOCATED_IN", confidence=0.8
            )
        )
    return Extraction(entities=entities, relations=relations)


class _EchoSynthesizer:
    """Network-free synthesizer: echoes entity names and cites every chunk."""

    def synthesize(self, query: str, context: RetrievalContext) -> Answer:
        names = ", ".join(e.name for e in context.entities)
        citations = [
            Citation(chunk_id=c.id, source=c.source, text=c.text)
            for c in context.chunks
        ]
        return Answer(
            text=f"Q={query} entities={names}", citations=citations, context=context
        )


def _adapter_for(backend: str, driver: Any, graph_name: str) -> Any:
    """Wrap *driver* in the matching migrate adapter (FalkorDB derives its own)."""
    if backend == "falkordb":
        return None  # GraphStore derives it from driver.falkordb_connection()
    if backend == "neo4j":
        from runic.migrate.adapters.neo4j import Neo4jAdapter

        return Neo4jAdapter(driver, graph_name)
    if backend == "memgraph":
        from runic.migrate.adapters.memgraph import MemgraphAdapter

        return MemgraphAdapter(driver, graph_name)
    if backend == "arcadedb":
        from runic.migrate.adapters.arcadedb import ArcadeDBAdapter

        return ArcadeDBAdapter(driver, graph_name)
    if backend == "age":
        from runic.migrate.adapters.age import AGEAdapter

        return AGEAdapter(driver, graph_name)
    return None


def _build_rag(store: GraphStore, settings: RagSettings) -> GraphRAG:
    """Wire a GraphRAG over *store* with fakes (no LLM/embedding network)."""
    from runic.rag.adapters.chunking import ParagraphChunker
    from runic.rag.adapters.reranking import RRFReranker
    from runic.rag.adapters.resolution import TwoStageResolver
    from runic.rag.adapters.retrieval import (
        FulltextRetriever,
        LocalRetriever,
        VectorRetriever,
    )
    from tests.runic.rag.fakes import FakeEmbedder, FakeExtractor

    embedder = FakeEmbedder(settings.embedding_dim)
    return GraphRAG(
        store,
        ontology=Ontology.default(),
        chunker=ParagraphChunker(settings),
        extractor=FakeExtractor(lambda chunk: _extraction_for(chunk.text)),
        embedder=embedder,
        resolver=TwoStageResolver(settings),
        retrievers={
            "vector": VectorRetriever(store, embedder, settings),
            "fulltext": FulltextRetriever(store, settings),
            "local": LocalRetriever(store, embedder, settings),
            # FulltextRetriever stands in for the LLM high-level retriever so the
            # hybrid path stays network-free.
            "highlevel": FulltextRetriever(store, settings),
        },
        reranker=RRFReranker(),
        synthesizer=_EchoSynthesizer(),
        settings=settings,
    )


@pytest.fixture(params=enabled_backends())
def backend_rag(request: pytest.FixtureRequest) -> Iterator[tuple[str, GraphRAG]]:
    """A bootstrapped GraphRAG over a live, per-backend store (auto-skips if down)."""
    backend: str = request.param
    graph_name = random_graph_name(prefix=f"ragbk_{backend}")
    driver, cleanup = make_driver(backend, graph_name)
    settings = RagSettings.model_validate(
        {"backend": backend, "embedding_dim": 16, "openai_api_key": "sk-test"}
    )
    store = GraphStore(
        driver,
        settings,
        schema_models=Ontology.default().schema_models(),
        adapter=_adapter_for(backend, driver, graph_name),
    )
    try:
        yield backend, _build_rag(store, settings)
    finally:
        cleanup()


def test_rag_roundtrip_across_backends(backend_rag: tuple[str, GraphRAG]) -> None:
    backend, rag = backend_rag

    rag.bootstrap_schema()  # must not raise on any backend (AGE tolerates no-DDL)

    report = rag.ingest_text(_CORPUS, source="facts")
    assert report.chunks >= 1, backend
    assert report.entities >= 3, f"{backend}: expected Alice/Acme/Berlin"
    assert report.relations >= 1, backend
    assert report.mentions >= 1, backend

    # Local mode: vector seed → neighbourhood expansion → grounded, cited answer.
    local = rag.query("Who founded Acme?", mode="local")
    assert isinstance(local, Answer)
    assert local.citations, f"{backend}: local query produced no citations"
    assert all(c.source == "facts" for c in local.citations), backend

    # Hybrid mode: vector + fulltext (+ traversal) fused via RRF.
    hybrid = rag.query("How is Acme related to Berlin?", mode="hybrid")
    assert hybrid.citations, f"{backend}: hybrid query produced no citations"
    assert hybrid.context is not None
    assert hybrid.context.entities, f"{backend}: hybrid retrieved no entities"

    # Idempotency: re-ingesting the same text MERGEs onto the same nodes.
    report2 = rag.ingest_text(_CORPUS, source="facts")
    assert report2.entities == report.entities, f"{backend}: ingest not idempotent"
