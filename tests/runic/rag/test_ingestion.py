"""Tests for :class:`runic.rag.services.ingestion.IngestionService`.

The unit tests exercise the parallel extract+embed and caching path with a fake
store (no network, no DB). The integration tests run the full pipeline against a
live FalkorDB (skipped when unreachable) using :class:`FakeExtractor` and
:class:`FakeEmbedder` so NO network call is ever made.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import pytest

from runic.rag.adapters.resolution import TwoStageResolver
from runic.rag.domain import (
    Chunk,
    ExtractedEntity,
    ExtractedRelation,
    Extraction,
    ScoredKey,
)
from runic.rag.ontology import Ontology
from runic.rag.services.ingestion import IngestionReport, IngestionService
from tests.runic.rag.fakes import FakeEmbedder, FakeExtractor

if TYPE_CHECKING:
    from runic.rag.config import RagSettings
    from runic.rag.ports import Chunker, Embedder, Extractor, GraphStore

# ── Shared corpus ──────────────────────────────────────────────────────────────

_TEXT = (
    "Alice founded Acme in Berlin.\n\n"
    "Acme is headquartered in Berlin and Alice leads it."
)
_SOURCE = "doc1"

# Known entities and the relations connecting them in the corpus.
_ENTITIES = [
    ExtractedEntity(name="Alice", type="Person", description="Founder of Acme."),
    ExtractedEntity(name="Acme", type="Organization", description="A company."),
    ExtractedEntity(name="Berlin", type="Location", description="A city."),
]
_RELATIONS = [
    ExtractedRelation(
        source="Alice", target="Acme", rel_type="FOUNDED", confidence=0.9
    ),
    ExtractedRelation(
        source="Acme", target="Berlin", rel_type="LOCATED_IN", confidence=0.8
    ),
]


def _content_extractor() -> Callable[[Chunk], Extraction]:
    """Return a deterministic, chunking-agnostic extraction function.

    For any chunk it surfaces exactly the known entities whose surface name
    appears in the chunk text, plus the relations whose *both* endpoints appear.
    This keeps assertions stable regardless of how the chunker splits the text.
    """

    def extract(chunk: Chunk) -> Extraction:
        present = {e.name for e in _ENTITIES if e.name in chunk.text}
        entities = [e for e in _ENTITIES if e.name in present]
        relations = [
            r for r in _RELATIONS if r.source in present and r.target in present
        ]
        return Extraction(entities=entities, relations=relations)

    return extract


# ── Fakes used only by the pure-unit tests ──────────────────────────────────────


class _CountingExtractor:
    """Wraps a callable extractor, counting how often :meth:`extract` is called."""

    def __init__(self, fn: Callable[[Chunk], Extraction]) -> None:
        self._inner = FakeExtractor(fn)
        self.calls = 0
        self._lock = threading.Lock()

    def extract(self, chunk: Chunk, *, entity_types: list[str]) -> Extraction:
        with self._lock:
            self.calls += 1
        return self._inner.extract(chunk, entity_types=entity_types)


class _CountingEmbedder:
    """Wraps :class:`FakeEmbedder`, counting embed() vs embed_batch() calls.

    Lets a test assert that ingestion batches embeddings (few embed_batch calls,
    zero per-item embed calls) instead of embedding one entity at a time.
    """

    def __init__(self, dim: int) -> None:
        self._inner = FakeEmbedder(dim)
        self.embed_calls = 0
        self.batch_calls = 0
        self._lock = threading.Lock()

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    def embed(self, text: str) -> list[float]:
        with self._lock:
            self.embed_calls += 1
        return self._inner.embed(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self.batch_calls += 1
        return self._inner.embed_batch(texts)


class _RecordingWriter:
    """In-memory writer recording every staged operation."""

    def __init__(self) -> None:
        self.chunks: dict[str, object] = {}
        self.entities: dict[str, tuple[str, str, str]] = {}
        self.embeddings: dict[str, list[float] | None] = {}
        self.relations: list[tuple[str, str, str]] = []
        self.mentions: set[tuple[str, str]] = set()

    def add_chunk(self, chunk_node: object) -> None:
        self.chunks[cast("Any", chunk_node).id] = chunk_node

    def upsert_entity(
        self,
        key: str,
        name: str,
        type: str,  # noqa: A002 - mirrors port signature
        description: str,
        embedding: list[float] | None,
    ) -> None:
        self.entities[key] = (name, type, description)
        self.embeddings[key] = embedding

    def relate(
        self,
        src_key: str,
        rel_type: str,
        dst_key: str,
        description: str,
        confidence: float,
        source_chunk: str,
    ) -> None:
        self.relations.append((src_key, rel_type, dst_key))

    def mention(self, chunk_id: str, entity_key: str) -> None:
        self.mentions.add((chunk_id, entity_key))


class _FakeStore:
    """Minimal GraphStore double: vector_search returns nothing (no dedup)."""

    def __init__(self) -> None:
        self.writer_recorder = _RecordingWriter()

    def bootstrap_schema(self) -> None:  # pragma: no cover - unused here
        return None

    def writer(self) -> _FakeStore:
        return self

    def __enter__(self) -> _RecordingWriter:
        return self.writer_recorder

    def __exit__(self, *exc: object) -> None:
        return None

    def vector_search(
        self,
        *,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None = None,
    ) -> list[ScoredKey]:
        return []


def _make_chunker(chunks: list[Chunk]) -> object:
    """Return a fake chunker yielding *chunks* verbatim."""

    class _Chunker:
        def split(self, text: str, *, source: str) -> list[Chunk]:
            return chunks

    return _Chunker()


def _chunks_for(text: str, source: str, settings: RagSettings) -> list[Chunk]:
    from runic.rag.adapters.chunking import ParagraphChunker

    return ParagraphChunker(settings).split(text, source=source)


# ── Pure-unit tests (no DB, no network) ─────────────────────────────────────────


def test_ingest_caches_and_parallelizes(
    rag_settings: RagSettings, tmp_path: object
) -> None:
    """Extraction runs once per distinct chunk; re-ingest hits the cache."""
    settings = rag_settings.model_copy(
        update={"cache_dir": str(tmp_path), "chunk_size": 16, "chunk_overlap": 4}
    )
    chunks = _chunks_for(_TEXT, _SOURCE, settings)
    assert len(chunks) >= 2, "corpus should split into multiple chunks"
    extractor = _CountingExtractor(_content_extractor())
    store = _FakeStore()
    service = IngestionService(
        store=cast("GraphStore", store),
        chunker=cast("Chunker", _make_chunker(chunks)),
        extractor=cast("Extractor", extractor),
        embedder=FakeEmbedder(settings.embedding_dim),
        resolver=TwoStageResolver(settings),
        settings=settings,
    )

    first = service.ingest(_TEXT, source=_SOURCE)
    assert isinstance(first, IngestionReport)
    assert first.chunks == len(chunks)
    # 3 distinct entities (Alice, Acme, Berlin) collapsed across all chunks.
    assert first.entities == 3
    # At least one relation whose endpoints co-occur in a chunk was written.
    assert first.relations >= 1
    # Distinct (chunk, entity) provenance edges.
    assert first.mentions > 0
    # Every entity was upserted exactly once into the fake store (idempotent keys).
    assert len(store.writer_recorder.entities) == 3
    calls_after_first = extractor.calls
    assert calls_after_first == len(chunks)

    # Re-ingest identical text: extraction served entirely from the cache.
    second = service.ingest(_TEXT, source=_SOURCE)
    assert second == first
    assert extractor.calls == calls_after_first


def _ceil_div(numerator: int, denominator: int) -> int:
    """Smallest integer >= numerator / denominator (denominator > 0)."""
    return -(-numerator // denominator)


def test_ingest_batches_entity_embeddings(
    rag_settings: RagSettings, tmp_path: object
) -> None:
    """Entity + chunk texts embed via bounded embed_batch calls, never per item.

    A corpus with K distinct entities must issue ``ceil(K / embed_batch_size)``
    batched requests (plus the chunk batch), NOT one ``embed()`` call per entity.
    """
    entity_count = 40
    batch_size = 16
    settings = rag_settings.model_copy(
        update={"cache_dir": str(tmp_path), "embed_batch_size": batch_size}
    )
    # Two chunks share the same text → it must collapse to a SINGLE embedding
    # (dedup), so only the one distinct chunk text is batched.
    chunks = [
        Chunk(id="c0", text="doc", seq=0, source="s"),
        Chunk(id="c1", text="doc", seq=1, source="s"),
    ]
    entities = [
        ExtractedEntity(name=f"E{i}", type="Person", description=f"desc {i}")
        for i in range(entity_count)
    ]
    canned = {"doc": Extraction(entities=entities)}
    embedder = _CountingEmbedder(settings.embedding_dim)
    store = _FakeStore()
    service = IngestionService(
        store=cast("GraphStore", store),
        chunker=cast("Chunker", _make_chunker(chunks)),
        extractor=cast("Extractor", FakeExtractor(canned)),
        embedder=cast("Embedder", embedder),
        resolver=TwoStageResolver(settings),
        settings=settings,
    )

    report = service.ingest("doc", source="s")

    # All K entities were processed (the call count is bounded, not because work
    # was dropped).
    assert report.chunks == len(chunks)
    assert report.entities == entity_count
    # Nothing is embedded one-at-a-time: the per-item embed() path is never hit.
    assert embedder.embed_calls == 0
    # Bounded by ceil over the batch size: one batch for the single distinct
    # chunk text + ceil(40 / 16) = 3 batches for the entity texts = 4 total —
    # far below K=40.
    expected_batches = _ceil_div(1, batch_size) + _ceil_div(entity_count, batch_size)
    assert embedder.batch_calls == expected_batches
    assert embedder.batch_calls < entity_count
    # Batched vectors are distributed back to the right entity by text identity.
    expected_vec = FakeEmbedder(settings.embedding_dim).embed("E0: desc 0")
    assert store.writer_recorder.embeddings["person:e0"] == expected_vec

    # Re-ingesting identical text serves every embedding from the cache, so the
    # batch is skipped entirely: no new embed_batch request is issued.
    batches_after_first = embedder.batch_calls
    service.ingest("doc", source="s")
    assert embedder.batch_calls == batches_after_first
    assert embedder.embed_calls == 0


def test_ingest_empty_text_returns_zero(rag_settings: RagSettings) -> None:
    """No chunks -> an all-zero report and no store interaction."""
    store = _FakeStore()
    service = IngestionService(
        store=cast("GraphStore", store),
        chunker=cast("Chunker", _make_chunker([])),
        extractor=cast("Extractor", FakeExtractor({})),
        embedder=FakeEmbedder(rag_settings.embedding_dim),
        resolver=TwoStageResolver(rag_settings),
        settings=rag_settings,
    )
    report = service.ingest("", source="empty")
    assert report == IngestionReport()
    assert store.writer_recorder.chunks == {}


def test_ingest_skips_relations_with_unknown_endpoints(
    rag_settings: RagSettings,
) -> None:
    """A relation whose endpoint was not extracted is dropped, not written."""
    chunk = Chunk(id="c0", text="t", seq=0, source="s")
    canned = {
        "t": Extraction(
            entities=[
                ExtractedEntity(name="Alice", type="Person", description="Founder.")
            ],
            relations=[
                ExtractedRelation(source="Alice", target="Ghost", rel_type="KNOWS")
            ],
        )
    }
    store = _FakeStore()
    service = IngestionService(
        store=cast("GraphStore", store),
        chunker=cast("Chunker", _make_chunker([chunk])),
        extractor=cast("Extractor", FakeExtractor(canned)),
        embedder=FakeEmbedder(rag_settings.embedding_dim),
        resolver=TwoStageResolver(rag_settings),
        settings=rag_settings,
    )
    report = service.ingest("ignored", source="s")
    assert report.entities == 1
    assert report.relations == 0
    assert store.writer_recorder.relations == []


# ── Integration tests against a live FalkorDB (fakes only — no network) ──────────


def _count(driver: object, cypher: str) -> int:
    """Run a single COUNT *cypher* against *driver* and return the scalar."""
    return cast("Any", driver).execute(cypher, {}).rows[0][0]


@pytest.fixture
def ingestion_service(
    falkordb_driver: object, rag_settings: RagSettings, tmp_path: object
) -> IngestionService:
    """A fully wired IngestionService over a bootstrapped live FalkorDB."""
    from runic.rag.store import GraphStore

    settings = rag_settings.model_copy(
        update={"cache_dir": str(tmp_path), "chunk_size": 16, "chunk_overlap": 4}
    )
    ontology = Ontology.default()
    store = GraphStore(
        falkordb_driver, settings, schema_models=ontology.schema_models()
    )
    store.bootstrap_schema()
    chunker = _make_chunker(_chunks_for(_TEXT, _SOURCE, settings))
    return IngestionService(
        store=store,
        chunker=cast("Chunker", chunker),
        extractor=cast("Extractor", FakeExtractor(_content_extractor())),
        embedder=FakeEmbedder(settings.embedding_dim),
        resolver=TwoStageResolver(settings),
        settings=settings,
        ontology=ontology,
    )


@pytest.mark.integration
def test_ingest_writes_expected_counts(
    ingestion_service: IngestionService, falkordb_driver: object
) -> None:
    """Ingesting the corpus persists the expected nodes/edges in FalkorDB."""
    report = ingestion_service.ingest(_TEXT, source=_SOURCE)
    assert report.chunks >= 2
    assert report.entities == 3
    assert report.relations >= 1

    chunk_count = _count(falkordb_driver, "MATCH (c:Chunk) RETURN count(c)")
    entity_count = _count(falkordb_driver, "MATCH (e:Entity) RETURN count(e)")
    rel_count = _count(falkordb_driver, "MATCH ()-[r:RELATES_TO]->() RETURN count(r)")
    mention_count = _count(falkordb_driver, "MATCH ()-[m:MENTIONS]->() RETURN count(m)")

    assert chunk_count == report.chunks
    assert entity_count == 3
    assert rel_count == report.relations
    assert mention_count == report.mentions


@pytest.mark.integration
def test_ingest_is_idempotent(
    ingestion_service: IngestionService, falkordb_driver: object
) -> None:
    """Re-ingesting identical text creates no duplicate nodes or edges."""
    first = ingestion_service.ingest(_TEXT, source=_SOURCE)

    def _counts() -> tuple[int, int, int, int]:
        return (
            _count(falkordb_driver, "MATCH (c:Chunk) RETURN count(c)"),
            _count(falkordb_driver, "MATCH (e:Entity) RETURN count(e)"),
            _count(falkordb_driver, "MATCH ()-[r:RELATES_TO]->() RETURN count(r)"),
            _count(falkordb_driver, "MATCH ()-[m:MENTIONS]->() RETURN count(m)"),
        )

    before = _counts()
    second = ingestion_service.ingest(_TEXT, source=_SOURCE)
    after = _counts()

    assert second == first
    assert before == after
