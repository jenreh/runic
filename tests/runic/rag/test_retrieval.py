"""Unit tests for the runic.rag retriever adapters (no network, no DB).

A :class:`_StubStore` implements the :class:`~runic.rag.ports.GraphStore`
surface the retrievers actually use, recording its calls so each test can
assert that the retriever passed the right arguments (label, prop, top_k,
hop bound) and assembled the resulting context correctly.

:class:`HighLevelRetriever` is driven with pydantic-ai's ``TestModel`` via
``agent.override`` so the keyword-extraction agent is deterministic and offline.
"""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import TYPE_CHECKING, Any

import pytest
from pydantic_ai.models.test import TestModel

from runic.rag.adapters.retrieval import (
    FulltextRetriever,
    HighLevelRetriever,
    LocalRetriever,
    ThemeKeywords,
    VectorRetriever,
)
from runic.rag.domain import ChunkHit, EntityHit, RelationHit, ScoredKey
from tests.runic.rag.fakes import FakeEmbedder

if TYPE_CHECKING:
    from runic.rag.config import RagSettings


class _StubStore:
    """A recording, in-memory stand-in for :class:`GraphStore`.

    Only the methods the retrievers call are implemented. Every call appends to
    :attr:`calls` so tests can verify the arguments the retriever sent.
    """

    def __init__(
        self,
        *,
        vector_hits: list[ScoredKey] | None = None,
        fulltext_hits: dict[str, list[ScoredKey]] | None = None,
        entities: dict[str, EntityHit] | None = None,
        chunks: list[ChunkHit] | None = None,
        expand_result: tuple[list[EntityHit], list[RelationHit]] | None = None,
    ) -> None:
        self._vector_hits = vector_hits or []
        self._fulltext_hits = fulltext_hits or {}
        self._entities = entities or {}
        self._chunks = chunks or []
        self._expand_result = expand_result or ([], [])
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def vector_search(
        self,
        *,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None = None,
    ) -> list[ScoredKey]:
        self.calls.append(
            (
                "vector_search",
                {
                    "label": label,
                    "prop": prop,
                    "k": k,
                    "type_filter": type_filter,
                    "dim": len(query_vec),
                },
            )
        )
        return list(self._vector_hits)

    def fulltext_search(
        self, *, label: str, prop: str, query: str, k: int
    ) -> list[ScoredKey]:
        self.calls.append(
            ("fulltext_search", {"label": label, "prop": prop, "query": query, "k": k})
        )
        return list(self._fulltext_hits.get(query, []))

    def get_entities(self, keys: list[str]) -> list[EntityHit]:
        self.calls.append(("get_entities", {"keys": list(keys)}))
        return [self._entities[key] for key in keys if key in self._entities]

    def expand(
        self, keys: list[str], *, max_hops: int
    ) -> tuple[list[EntityHit], list[RelationHit]]:
        self.calls.append(("expand", {"keys": list(keys), "max_hops": max_hops}))
        return self._expand_result

    def chunks_for_entities(self, keys: list[str], *, limit: int) -> list[ChunkHit]:
        self.calls.append(("chunks_for_entities", {"keys": list(keys), "limit": limit}))
        return list(self._chunks[:limit])

    # Ingestion-side protocol surface unused by retrievers (kept for ----------
    # structural GraphStore conformance only).

    def bootstrap_schema(self) -> None:  # pragma: no cover - unused by retrievers
        self.calls.append(("bootstrap_schema", {}))

    def writer(self) -> AbstractContextManager[Any]:  # pragma: no cover - unused
        return nullcontext(self)

    # Test helpers ----------------------------------------------------------

    def calls_named(self, name: str) -> list[dict[str, Any]]:
        """Return the recorded argument dicts for every call to *name*."""
        return [args for call_name, args in self.calls if call_name == name]


def _entity(key: str, name: str, etype: str = "Person") -> EntityHit:
    return EntityHit(
        canonical_key=key,
        name=name,
        type=etype,
        description=f"{name} description.",
        score=1.0,
    )


def _chunk(cid: str) -> ChunkHit:
    return ChunkHit(id=cid, text=f"text of {cid}", source="doc1", score=1.0)


@pytest.fixture
def embedder(rag_settings: RagSettings) -> FakeEmbedder:
    return FakeEmbedder(dim=rag_settings.embedding_dim)


# ── VectorRetriever ───────────────────────────────────────────────────────────


def test_vector_retriever_assembles_context(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore(
        vector_hits=[
            ScoredKey(key="person:alice", score=0.97),
            ScoredKey(key="org:acme", score=0.55),
        ],
        entities={
            "person:alice": _entity("person:alice", "Alice"),
            "org:acme": _entity("org:acme", "Acme", "Organization"),
        },
        chunks=[_chunk("c0"), _chunk("c1")],
    )
    retriever = VectorRetriever(store, embedder, rag_settings)

    ctx = retriever.retrieve("who founded acme?", top_k=5)

    assert ctx.query == "who founded acme?"
    # Entities hydrated and re-scored from the vector hits, ordered desc.
    assert [e.canonical_key for e in ctx.entities] == ["person:alice", "org:acme"]
    assert ctx.entities[0].score == pytest.approx(0.97)
    assert ctx.entities[1].score == pytest.approx(0.55)
    # Chunks attached.
    assert {c.id for c in ctx.chunks} == {"c0", "c1"}
    # No relations for a plain vector retrieve.
    assert ctx.relations == []


def test_vector_retriever_searches_entity_embedding_with_top_k(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore()
    VectorRetriever(store, embedder, rag_settings).retrieve("q", top_k=7)

    (vs,) = store.calls_named("vector_search")
    assert vs["label"] == "Entity"
    assert vs["prop"] == "embedding"
    assert vs["k"] == 7
    assert vs["dim"] == rag_settings.embedding_dim


def test_vector_retriever_respects_top_k_for_chunks(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore(
        vector_hits=[ScoredKey(key="person:alice", score=0.9)],
        entities={"person:alice": _entity("person:alice", "Alice")},
        chunks=[_chunk(f"c{i}") for i in range(10)],
    )
    ctx = VectorRetriever(store, embedder, rag_settings).retrieve("q", top_k=3)

    assert len(ctx.chunks) == 3
    (cfe,) = store.calls_named("chunks_for_entities")
    assert cfe["limit"] == 3


def test_vector_retriever_empty_when_no_hits(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore()
    ctx = VectorRetriever(store, embedder, rag_settings).retrieve("q", top_k=5)

    assert ctx.entities == []
    assert ctx.chunks == []


# ── FulltextRetriever ─────────────────────────────────────────────────────────


def test_fulltext_retriever_assembles_context(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore(
        fulltext_hits={"Alice": [ScoredKey(key="person:alice", score=3.2)]},
        entities={"person:alice": _entity("person:alice", "Alice")},
        chunks=[_chunk("c0")],
    )
    ctx = FulltextRetriever(store, rag_settings).retrieve("Alice", top_k=5)

    assert [e.canonical_key for e in ctx.entities] == ["person:alice"]
    assert ctx.entities[0].score == pytest.approx(3.2)
    assert {c.id for c in ctx.chunks} == {"c0"}

    (fs,) = store.calls_named("fulltext_search")
    assert fs["label"] == "Entity"
    assert fs["prop"] == "name"
    assert fs["query"] == "Alice"
    assert fs["k"] == 5


def test_fulltext_retriever_empty_when_no_hits(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore()
    ctx = FulltextRetriever(store, rag_settings).retrieve("nope", top_k=5)

    assert ctx.entities == []
    assert ctx.chunks == []
    # No hydration attempted when there are no keys.
    assert store.calls_named("get_entities") == [{"keys": []}]


# ── LocalRetriever ────────────────────────────────────────────────────────────


def test_local_retriever_expands_neighbourhood(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    alice = _entity("person:alice", "Alice")
    acme = _entity("org:acme", "Acme", "Organization")
    berlin = _entity("loc:berlin", "Berlin", "Location")
    relations = [
        RelationHit(
            source_key="person:alice",
            target_key="org:acme",
            rel_type="FOUNDED",
            description="Alice founded Acme.",
        ),
        RelationHit(
            source_key="org:acme",
            target_key="loc:berlin",
            rel_type="LOCATED_IN",
            description="Acme is in Berlin.",
        ),
    ]
    store = _StubStore(
        vector_hits=[ScoredKey(key="person:alice", score=0.95)],
        expand_result=([alice, acme, berlin], relations),
        chunks=[_chunk("c0")],
    )
    rag_settings = rag_settings.model_copy(update={"max_hops": 2})
    ctx = LocalRetriever(store, embedder, rag_settings).retrieve("acme", top_k=10)

    keys = {e.canonical_key for e in ctx.entities}
    assert keys == {"person:alice", "org:acme", "loc:berlin"}
    assert len(ctx.relations) == 2
    # Seed entity carries its vector score; neighbours keep the default.
    by_key = {e.canonical_key: e for e in ctx.entities}
    assert by_key["person:alice"].score == pytest.approx(0.95)


def test_local_retriever_passes_max_hops(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore(
        vector_hits=[ScoredKey(key="person:alice", score=0.9)],
        expand_result=([_entity("person:alice", "Alice")], []),
    )
    rag_settings = rag_settings.model_copy(update={"max_hops": 3})
    LocalRetriever(store, embedder, rag_settings).retrieve("q", top_k=5)

    (exp,) = store.calls_named("expand")
    assert exp["max_hops"] == 3
    assert exp["keys"] == ["person:alice"]


def test_local_retriever_chunks_cover_all_entities(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    alice = _entity("person:alice", "Alice")
    acme = _entity("org:acme", "Acme", "Organization")
    store = _StubStore(
        vector_hits=[ScoredKey(key="person:alice", score=0.9)],
        expand_result=([alice, acme], []),
        chunks=[_chunk("c0")],
    )
    LocalRetriever(store, embedder, rag_settings).retrieve("q", top_k=5)

    (cfe,) = store.calls_named("chunks_for_entities")
    # Chunks fetched for the full expanded entity set, not just the seed.
    assert set(cfe["keys"]) == {"person:alice", "org:acme"}


def test_local_retriever_empty_when_no_seed(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore()
    ctx = LocalRetriever(store, embedder, rag_settings).retrieve("q", top_k=5)

    assert ctx.entities == []
    assert ctx.relations == []
    # Never expands without a seed.
    assert store.calls_named("expand") == []


# ── HighLevelRetriever ────────────────────────────────────────────────────────


def test_high_level_retriever_uses_llm_keywords(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    acme = _entity("org:acme", "Acme", "Organization")
    berlin = _entity("loc:berlin", "Berlin", "Location")
    store = _StubStore(
        fulltext_hits={
            "acme": [ScoredKey(key="org:acme", score=2.0)],
            "berlin": [ScoredKey(key="loc:berlin", score=1.0)],
        },
        expand_result=(
            [acme, berlin],
            [
                RelationHit(
                    source_key="org:acme",
                    target_key="loc:berlin",
                    rel_type="LOCATED_IN",
                    description="",
                )
            ],
        ),
        chunks=[_chunk("c0")],
    )
    retriever = HighLevelRetriever(store, rag_settings)

    model = TestModel(custom_output_args=ThemeKeywords(keywords=["acme", "berlin"]))
    with retriever.agent.override(model=model):
        ctx = retriever.retrieve("tell me about the company", top_k=5)

    # Both keywords were fulltext-searched.
    searched = {fs["query"] for fs in store.calls_named("fulltext_search")}
    assert searched == {"acme", "berlin"}
    # The matched entities seeded the expansion.
    (exp,) = store.calls_named("expand")
    assert set(exp["keys"]) == {"org:acme", "loc:berlin"}
    assert {e.canonical_key for e in ctx.entities} == {"org:acme", "loc:berlin"}
    assert len(ctx.relations) == 1


def test_high_level_retriever_falls_back_to_query(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore(
        fulltext_hits={"raw query": [ScoredKey(key="org:acme", score=1.0)]},
        expand_result=([_entity("org:acme", "Acme", "Organization")], []),
    )
    retriever = HighLevelRetriever(store, rag_settings)

    model = TestModel(custom_output_args=ThemeKeywords(keywords=[]))
    with retriever.agent.override(model=model):
        retriever.retrieve("raw query", top_k=5)

    # With no keywords, the raw query is used as the single search term.
    searched = {fs["query"] for fs in store.calls_named("fulltext_search")}
    assert searched == {"raw query"}


def test_high_level_retriever_empty_when_no_matches(
    rag_settings: RagSettings, embedder: FakeEmbedder
) -> None:
    store = _StubStore()
    retriever = HighLevelRetriever(store, rag_settings)

    model = TestModel(custom_output_args=ThemeKeywords(keywords=["ghost"]))
    with retriever.agent.override(model=model):
        ctx = retriever.retrieve("anything", top_k=5)

    assert ctx.entities == []
    assert ctx.relations == []
    assert store.calls_named("expand") == []
