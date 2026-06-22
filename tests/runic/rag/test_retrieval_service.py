"""Unit tests for :class:`runic.rag.services.retrieval.RetrievalService`.

All tests are network-free. Retrievers are recording stubs that return canned
:class:`RetrievalContext` objects; the reranker is the passthrough
:class:`~tests.runic.rag.fakes.FakeReranker` (or the real RRF reranker for the
fusion test); the synthesizer is driven by pydantic-ai's ``TestModel``.

They assert that:

* mode selection is dict dispatch — ``local`` runs only the local retriever,
  ``hybrid`` runs vector + fulltext + highlevel, ``auto`` classifies between them;
* hybrid fans out and the contexts are fused (RRF) before synthesis;
* an :class:`Answer` with one citation per fused chunk is always returned;
* an unknown mode raises ``ValueError``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

import runic.rag.adapters.synthesis as synthesis_module
from runic.rag.adapters.reranking import RRFReranker
from runic.rag.adapters.synthesis import PydanticAISynthesizer
from runic.rag.domain import (
    Answer,
    ChunkHit,
    EntityHit,
    RelationHit,
    RetrievalContext,
    ScoredKey,
)
from runic.rag.services.retrieval import RetrievalService
from tests.runic.rag.fakes import FakeEmbedder, FakeReranker

if TYPE_CHECKING:
    from runic.rag.config import RagSettings
    from runic.rag.ports import Reranker, Synthesizer, Writer


class _StubRetriever:
    """A recording :class:`Retriever` returning a canned context."""

    def __init__(self, context: RetrievalContext) -> None:
        self._context = context
        self.calls: list[tuple[str, int]] = []

    def retrieve(self, query: str, *, top_k: int) -> RetrievalContext:
        self.calls.append((query, top_k))
        # Round-trip the live query onto the returned context.
        return self._context.model_copy(update={"query": query})


class _StubSynthesizer:
    """A :class:`Synthesizer` that echoes the fused context into an Answer."""

    def __init__(self) -> None:
        self.seen: list[RetrievalContext] = []

    def synthesize(self, query: str, context: RetrievalContext) -> Answer:
        self.seen.append(context)
        return Answer(text=f"answer:{query}", citations=[], context=context)


class _StubStore:
    """GraphStore stand-in; the service holds it but never calls it.

    Implements the full :class:`~runic.rag.ports.GraphStore` surface so it
    satisfies the protocol structurally; every method raises to make any
    accidental use loud.
    """

    def bootstrap_schema(self) -> None:  # pragma: no cover - never called
        raise AssertionError("store must not be touched by RetrievalService")

    def writer(self) -> AbstractContextManager[Writer]:  # pragma: no cover
        raise AssertionError("store must not be touched by RetrievalService")

    def vector_search(
        self,
        *,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None = None,
    ) -> list[ScoredKey]:  # pragma: no cover - never called
        raise AssertionError("store must not be touched by RetrievalService")

    def fulltext_search(
        self, *, label: str, prop: str, query: str, k: int
    ) -> list[ScoredKey]:  # pragma: no cover - never called
        raise AssertionError("store must not be touched by RetrievalService")

    def get_entities(self, keys: list[str]) -> list[EntityHit]:  # pragma: no cover
        raise AssertionError("store must not be touched by RetrievalService")

    def expand(
        self, keys: list[str], *, max_hops: int
    ) -> tuple[list[EntityHit], list[RelationHit]]:  # pragma: no cover
        raise AssertionError("store must not be touched by RetrievalService")

    def chunks_for_entities(
        self, keys: list[str], *, limit: int
    ) -> list[ChunkHit]:  # pragma: no cover - never called
        raise AssertionError("store must not be touched by RetrievalService")


def _entity(key: str) -> EntityHit:
    return EntityHit(
        canonical_key=key, name=key, type="Concept", description="d", score=0.9
    )


def _chunk(cid: str) -> ChunkHit:
    return ChunkHit(id=cid, text=f"text-{cid}", source="src", score=0.8)


def _context(name: str) -> RetrievalContext:
    """A canned context tagged so we can tell which retriever produced it."""
    return RetrievalContext(
        query="seed",
        entities=[_entity(f"{name}:e")],
        chunks=[_chunk(f"{name}-c")],
    )


def _retrievers() -> dict[str, _StubRetriever]:
    """One stub per canonical retriever name, each with a distinct context."""
    return {
        "local": _StubRetriever(_context("local")),
        "vector": _StubRetriever(_context("vector")),
        "fulltext": _StubRetriever(_context("fulltext")),
        "highlevel": _StubRetriever(_context("highlevel")),
    }


def _service(
    retrievers: dict[str, _StubRetriever],
    settings: RagSettings,
    *,
    reranker: Reranker | None = None,
    synthesizer: Synthesizer | None = None,
) -> RetrievalService:
    return RetrievalService(
        store=_StubStore(),
        retrievers=retrievers,
        reranker=reranker if reranker is not None else FakeReranker(),
        synthesizer=synthesizer if synthesizer is not None else _StubSynthesizer(),
        embedder=FakeEmbedder(dim=settings.embedding_dim),
        settings=settings,
    )


def _ran(retrievers: dict[str, _StubRetriever]) -> set[str]:
    """The set of retriever names that were actually invoked."""
    return {name for name, stub in retrievers.items() if stub.calls}


def test_local_mode_runs_only_local_retriever(rag_settings: RagSettings) -> None:
    """``mode='local'`` dispatches to the local retriever and no other."""
    retrievers = _retrievers()
    service = _service(retrievers, rag_settings)

    answer = service.query("Who founded ACME?", mode="local")

    assert _ran(retrievers) == {"local"}
    assert isinstance(answer, Answer)


def test_hybrid_mode_runs_vector_fulltext_highlevel(
    rag_settings: RagSettings,
) -> None:
    """``mode='hybrid'`` fans out across the three breadth strategies."""
    retrievers = _retrievers()
    service = _service(retrievers, rag_settings)

    service.query("anything", mode="hybrid")

    assert _ran(retrievers) == {"vector", "fulltext", "highlevel"}


def test_hybrid_fuses_contexts_with_reranker(rag_settings: RagSettings) -> None:
    """Hybrid passes all retriever contexts through the (RRF) reranker."""
    retrievers = _retrievers()
    synth = _StubSynthesizer()
    service = _service(
        retrievers, rag_settings, reranker=RRFReranker(), synthesizer=synth
    )

    service.query("broad themes across everything", mode="hybrid")

    # The fused context the synthesizer saw merges chunks from all three
    # retrievers (vector, fulltext, highlevel) — proof fusion happened.
    fused = synth.seen[-1]
    chunk_ids = {chunk.id for chunk in fused.chunks}
    assert chunk_ids == {"vector-c", "fulltext-c", "highlevel-c"}
    entity_keys = {hit.canonical_key for hit in fused.entities}
    assert entity_keys == {"vector:e", "fulltext:e", "highlevel:e"}


def test_auto_mode_picks_local_for_short_pointed_query(
    rag_settings: RagSettings,
) -> None:
    """A short, entity-pointed question routes to the local retriever."""
    retrievers = _retrievers()
    service = _service(retrievers, rag_settings)

    service.query("Who founded ACME?", mode="auto")

    assert _ran(retrievers) == {"local"}


def test_auto_mode_picks_hybrid_for_broad_query(rag_settings: RagSettings) -> None:
    """A broad/thematic question routes to the hybrid fan-out."""
    retrievers = _retrievers()
    service = _service(retrievers, rag_settings)

    service.query("Compare the overall themes across all the documents", mode="auto")

    assert _ran(retrievers) == {"vector", "fulltext", "highlevel"}


def test_default_mode_is_auto(rag_settings: RagSettings) -> None:
    """Omitting ``mode`` uses ``auto`` (short query → local)."""
    retrievers = _retrievers()
    service = _service(retrievers, rag_settings)

    service.query("Who is Jane?")

    assert _ran(retrievers) == {"local"}


def test_unknown_mode_raises(rag_settings: RagSettings) -> None:
    """An unregistered mode is rejected before any retriever runs."""
    retrievers = _retrievers()
    service = _service(retrievers, rag_settings)

    with pytest.raises(ValueError, match="Unknown retrieval mode"):
        service.query("q", mode="bogus")

    assert _ran(retrievers) == set()


def test_missing_retriever_is_skipped(rag_settings: RagSettings) -> None:
    """Hybrid with a partial wiring runs only the retrievers present."""
    retrievers = {"vector": _StubRetriever(_context("vector"))}
    service = _service(retrievers, rag_settings)

    answer = service.query("anything", mode="hybrid")

    assert _ran(retrievers) == {"vector"}
    assert isinstance(answer, Answer)


def test_no_contexts_yields_empty_context_answer(rag_settings: RagSettings) -> None:
    """With nothing wired the service still returns an Answer over empty context."""
    synth = _StubSynthesizer()
    service = _service({}, rag_settings, synthesizer=synth)

    answer = service.query("anything", mode="hybrid")

    assert isinstance(answer, Answer)
    assert synth.seen[-1].entities == []
    assert synth.seen[-1].chunks == []


def test_end_to_end_with_test_model_synthesizer(
    monkeypatch: pytest.MonkeyPatch, rag_settings: RagSettings
) -> None:
    """Integration: real RRF reranker + pydantic-ai TestModel synthesizer.

    Drives the full local→fuse→synthesize path and asserts a cited Answer.
    """

    def fake_build_agent(
        settings: RagSettings, *, output_type: object = None, system_prompt: str
    ) -> Agent[None, str]:
        return Agent(
            TestModel(custom_output_text="Grounded answer [chunk:local-c]"),
            system_prompt=system_prompt,
        )

    monkeypatch.setattr(synthesis_module, "build_agent", fake_build_agent)

    retrievers = _retrievers()
    service = _service(
        retrievers,
        rag_settings,
        reranker=RRFReranker(),
        synthesizer=PydanticAISynthesizer(rag_settings),
    )

    answer = service.query("Who founded ACME?", mode="local")

    assert isinstance(answer, Answer)
    assert answer.text == "Grounded answer [chunk:local-c]"
    assert [c.chunk_id for c in answer.citations] == ["local-c"]
    assert answer.context is not None
