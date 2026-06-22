"""GraphRAG — the public Tell-Don't-Ask facade for runic.rag (ADR).

:class:`GraphRAG` is the single entry point users touch. It hides all wiring
(Information Hiding): given a driver (or a prebuilt :class:`~runic.rag.store.GraphStore`)
plus the ports it composes an :class:`~runic.rag.services.IngestionService` and a
:class:`~runic.rag.services.RetrievalService` and exposes four verbs —
:meth:`bootstrap_schema`, :meth:`ingest_text`, :meth:`ingest_document`, and
:meth:`query`. Callers tell the facade what to do; they never reach inside it.

The explicit constructor is the extension seam (DIP): every collaborator is an
injected port, so the whole pipeline is swappable and unit-testable with fakes.
:meth:`with_defaults` is the batteries-included path that builds the production
adapters from :class:`~runic.rag.config.RagSettings`.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from runic.rag.concurrency import BudgetGuard
from runic.rag.config import RagSettings, load_settings
from runic.rag.ontology import Ontology
from runic.rag.services import IngestionService, RetrievalService
from runic.rag.store import GraphStore

if TYPE_CHECKING:
    from pathlib import Path

    from runic.rag.domain import Answer
    from runic.rag.ports import (
        Chunker,
        DocumentChunker,
        DocumentParser,
        Embedder,
        EntityResolver,
        Extractor,
        Reranker,
        Retriever,
        Synthesizer,
    )

log = logging.getLogger(__name__)

__all__ = ["GraphRAG"]

# Canonical retriever names the RetrievalService plans around.
_VECTOR = "vector"
_FULLTEXT = "fulltext"
_LOCAL = "local"
_HIGHLEVEL = "highlevel"


class GraphRAG:
    """The public Graph-RAG facade composing ingestion and retrieval.

    Construct via :meth:`with_defaults` for the production adapters, or call the
    constructor directly with explicit ports to swap any stage (the extension
    seam). The facade owns no backend knowledge — it merely wires the injected
    collaborators into the two services and forwards the four public verbs.

    Parameters
    ----------
    driver_or_store:
        Either an OGM driver (wrapped in a :class:`~runic.rag.store.GraphStore`)
        or an already-built ``GraphStore`` (used as-is, e.g. with test fakes).
    ontology:
        The entity-type vocabulary + OGM models for bootstrap and extraction.
    chunker, extractor, embedder, resolver:
        Ingestion-side ports.
    retrievers:
        Mapping of retriever name → :class:`~runic.rag.ports.Retriever`.
    reranker, synthesizer:
        Retrieval-side ports.
    settings:
        Runtime configuration shared by both services.
    document_parser, document_chunker:
        Optional file-oriented ingestion ports forwarded to
        :class:`~runic.rag.services.IngestionService`. Both default to ``None``
        (the unchanged built-in :meth:`ingest_document` path); inject e.g. the
        ``runic-rag-docling`` adapters here to parse/chunk documents
        structure-aware. The core imports no document backend.
    """

    def __init__(
        self,
        driver_or_store: Any,
        *,
        ontology: Ontology,
        chunker: Chunker,
        extractor: Extractor,
        embedder: Embedder,
        resolver: EntityResolver,
        retrievers: dict[str, Retriever],
        reranker: Reranker,
        synthesizer: Synthesizer,
        settings: RagSettings,
        budget: BudgetGuard | None = None,
        document_parser: DocumentParser | None = None,
        document_chunker: DocumentChunker | None = None,
    ) -> None:
        self._settings = settings
        self._ontology = ontology
        self._store = self._coerce_store(driver_or_store, ontology, settings)
        self._ingestion = IngestionService(
            self._store,
            chunker,
            extractor,
            embedder,
            resolver,
            settings,
            budget_guard=budget,
            ontology=ontology,
            document_parser=document_parser,
            document_chunker=document_chunker,
        )
        self._retrieval = RetrievalService(
            store=self._store,
            retrievers=retrievers,
            reranker=reranker,
            synthesizer=synthesizer,
            embedder=embedder,
            settings=settings,
        )

    # ── Construction ──────────────────────────────────────────────────────────

    @staticmethod
    def _coerce_store(
        driver_or_store: Any, ontology: Ontology, settings: RagSettings
    ) -> GraphStore:
        """Return *driver_or_store* if it is a GraphStore, else wrap the driver."""
        if isinstance(driver_or_store, GraphStore):
            return driver_or_store
        return GraphStore(
            driver_or_store,
            settings,
            schema_models=ontology.schema_models(),
        )

    @classmethod
    def with_defaults(
        cls,
        driver: Any = None,
        *,
        settings: RagSettings | None = None,
        ontology: Ontology | None = None,
        document_parser: DocumentParser | None = None,
        document_chunker: DocumentChunker | None = None,
    ) -> GraphRAG:
        """Build a fully-wired :class:`GraphRAG` with the production adapters.

        Loads settings from the environment when *settings* is ``None`` and
        builds a driver from ``settings.backend`` when *driver* is ``None``
        (FalkorDB on localhost by default, otherwise Neo4j). The default adapter
        stack is the paragraph chunker, the pydantic-ai extractor, the OpenAI
        embedder, the two-stage resolver, the four retrievers (vector, fulltext,
        local, high-level), the RRF reranker, and the pydantic-ai synthesizer.

        *document_parser* / *document_chunker* are optional, already-built
        file-oriented ports forwarded to the constructor; both default to
        ``None`` (the unchanged built-in document path). This path imports no
        document backend — an add-on (e.g. ``runic-rag-docling``) builds the
        port and passes it in, so the default stack stays dependency-light.
        """
        settings = settings or load_settings()
        ontology = ontology or Ontology.default()
        driver = driver if driver is not None else cls._build_driver(settings)

        from runic.rag.adapters import (
            FulltextRetriever,
            HighLevelRetriever,
            LocalRetriever,
            ParagraphChunker,
            PydanticAIExtractor,
            PydanticAISynthesizer,
            RRFReranker,
            TwoStageResolver,
            VectorRetriever,
        )

        store = GraphStore(driver, settings, schema_models=ontology.schema_models())
        embedder = cls._build_embedder(settings)
        # One shared budget spans ingestion AND the query path (extraction,
        # high-level keyword extraction, synthesis) so max_llm_calls/max_tokens
        # cap the whole run rather than each component in isolation.
        budget = BudgetGuard(
            max_llm_calls=settings.max_llm_calls, max_tokens=settings.max_tokens
        )
        retrievers: dict[str, Retriever] = {
            _VECTOR: VectorRetriever(store, embedder, settings),
            _FULLTEXT: FulltextRetriever(store, settings),
            _LOCAL: LocalRetriever(store, embedder, settings),
            _HIGHLEVEL: HighLevelRetriever(store, settings, budget=budget),
        }
        return cls(
            store,
            ontology=ontology,
            chunker=ParagraphChunker(settings),
            extractor=PydanticAIExtractor(settings),
            embedder=embedder,
            resolver=TwoStageResolver(settings),
            retrievers=retrievers,
            reranker=RRFReranker(),
            synthesizer=PydanticAISynthesizer(settings, budget=budget),
            settings=settings,
            budget=budget,
            document_parser=document_parser,
            document_chunker=document_chunker,
        )

    @staticmethod
    def _build_driver(settings: RagSettings) -> Any:
        """Create an OGM driver for the configured backend (all five)."""
        from runic.ogm.driver.factory import create_driver

        backend = settings.backend
        if backend == "neo4j":
            return create_driver(
                "neo4j",
                host=_neo4j_host(settings.neo4j_uri),
                port=_neo4j_port(settings.neo4j_uri),
                database=settings.neo4j_database,
                username=settings.neo4j_username or "",
                password=settings.neo4j_password or "",
            )
        if backend == "memgraph":
            return create_driver(
                "memgraph",
                host=_neo4j_host(settings.memgraph_uri),
                port=_neo4j_port(settings.memgraph_uri),
                database=settings.memgraph_database,
                username=settings.memgraph_username or "",
                password=settings.memgraph_password or "",
            )
        if backend == "arcadedb":
            return create_driver(
                "arcadedb",
                host=settings.arcadedb_host,
                port=settings.arcadedb_port,
                database=settings.arcadedb_database,
                username=settings.arcadedb_username,
                password=settings.arcadedb_password or "",
            )
        if backend == "age":
            return create_driver(
                "age",
                host=settings.age_host,
                port=settings.age_port,
                database=settings.age_database,
                graph=settings.age_graph,
                username=settings.age_username,
                password=settings.age_password or "",
            )
        return create_driver(
            "falkordb",
            host=settings.falkordb_host,
            port=settings.falkordb_port,
            graph=settings.falkordb_graph,
        )

    @staticmethod
    def _build_embedder(settings: RagSettings) -> Any:
        """Create the embedder for the configured embedding provider.

        Mirrors :meth:`_build_driver`: ``embedding_provider="ollama"`` selects the
        local :class:`~runic.rag.adapters.OllamaEmbedder`, otherwise the
        :class:`~runic.rag.adapters.OpenAIEmbedder`. This lets the
        batteries-included path run fully offline against Ollama without dropping
        down to the explicit constructor.
        """
        from runic.rag.adapters import OllamaEmbedder, OpenAIEmbedder

        if settings.embedding_provider == "ollama":
            return OllamaEmbedder(settings)
        return OpenAIEmbedder(settings)

    # ── Public verbs (Tell-Don't-Ask) ──────────────────────────────────────────

    def bootstrap_schema(self) -> None:
        """Create the entity types and indexes for the ontology (idempotent)."""
        self._store.bootstrap_schema()

    def ingest_text(self, text: str, *, source: str) -> Any:
        """Ingest *text* tagged with *source*; return the ingestion report."""
        return self._ingestion.ingest(text, source=source)

    def ingest_document(self, path: str | Path) -> Any:
        """Load and ingest the document at *path*; return the ingestion report."""
        return self._ingestion.ingest_document(path)

    def query(self, q: str, *, mode: str = "auto") -> Answer:
        """Answer *q* using the configured retrievers; return a cited Answer."""
        return self._retrieval.query(q, mode=mode)


def _neo4j_host(uri: str | None) -> str:
    """Extract the host from a ``bolt://host:port`` URI (default localhost)."""
    if not uri:
        return "localhost"
    rest = uri.split("://", 1)[-1]
    return rest.split(":", 1)[0] or "localhost"


def _neo4j_port(uri: str | None) -> int:
    """Extract the port from a ``bolt://host:port`` URI (default 7687)."""
    if not uri or ":" not in uri.split("://", 1)[-1]:
        return 7687
    rest = uri.split("://", 1)[-1]
    tail = rest.split(":", 1)[1].split("/", 1)[0]
    try:
        return int(tail)
    except ValueError:
        return 7687
