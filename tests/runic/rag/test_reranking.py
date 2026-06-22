"""Unit tests for the reranking adapters (RRF + cross-encoder). No network."""

from __future__ import annotations

import builtins
from typing import Any

import pytest

from runic.rag.adapters.reranking import CrossEncoderReranker, RRFReranker
from runic.rag.domain import ChunkHit, EntityHit, RelationHit, RetrievalContext
from runic.rag.exceptions import RagError


def _entity(key: str, score: float = 0.0) -> EntityHit:
    return EntityHit(
        canonical_key=key,
        name=key.upper(),
        type="Concept",
        description=f"about {key}",
        score=score,
    )


def _chunk(chunk_id: str, score: float = 0.0) -> ChunkHit:
    return ChunkHit(id=chunk_id, text=f"text {chunk_id}", source="doc", score=score)


def _ctx(
    *,
    entities: list[EntityHit] | None = None,
    chunks: list[ChunkHit] | None = None,
    relations: list[RelationHit] | None = None,
    query: str = "q",
) -> RetrievalContext:
    return RetrievalContext(
        query=query,
        entities=entities or [],
        chunks=chunks or [],
        relations=relations or [],
    )


# ── RRFReranker: math ─────────────────────────────────────────────────────────


def test_rrf_constructor_rejects_non_positive_k0() -> None:
    with pytest.raises(ValueError, match="k0 must be positive"):
        RRFReranker(k0=0)


def test_rrf_empty_contexts_returns_empty_context() -> None:
    result = RRFReranker().rerank("hello", [], top_k=5)
    assert result.query == "hello"
    assert result.entities == []
    assert result.chunks == []
    assert result.relations == []


def test_rrf_single_context_preserves_rank_order() -> None:
    ctx = _ctx(entities=[_entity("a"), _entity("b"), _entity("c")])
    result = RRFReranker(k0=60).rerank("q", [ctx], top_k=10)
    assert [hit.canonical_key for hit in result.entities] == ["a", "b", "c"]


def test_rrf_fused_score_is_sum_of_reciprocal_ranks() -> None:
    # Canonical RRF uses 1-based ranks → contribution 1/(60 + rank + 1):
    # "a": rank0 in ctx1 (1/61) + rank1 in ctx2 (1/62)
    # "b": rank1 in ctx1 (1/62) + rank0 in ctx2 (1/61)  → tie with "a"
    ctx1 = _ctx(entities=[_entity("a"), _entity("b")])
    ctx2 = _ctx(entities=[_entity("b"), _entity("a")])
    result = RRFReranker(k0=60).rerank("q", [ctx1, ctx2], top_k=10)

    expected = 1.0 / 61 + 1.0 / 62
    by_key = {hit.canonical_key: hit for hit in result.entities}
    assert by_key["a"].score == pytest.approx(expected)
    assert by_key["b"].score == pytest.approx(expected)
    # Tie on score → ascending key order.
    assert [hit.canonical_key for hit in result.entities] == ["a", "b"]


def test_rrf_known_ranks_produce_known_fused_order() -> None:
    # ctx1: x(0), y(1), z(2) ; ctx2: y(0), z(1) → y appears high in both.
    ctx1 = _ctx(entities=[_entity("x"), _entity("y"), _entity("z")])
    ctx2 = _ctx(entities=[_entity("y"), _entity("z")])
    result = RRFReranker(k0=60).rerank("q", [ctx1, ctx2], top_k=10)

    score_x = 1.0 / 61  # only ctx1 rank0
    score_y = 1.0 / 62 + 1.0 / 61  # ctx1 rank1 + ctx2 rank0
    score_z = 1.0 / 63 + 1.0 / 62  # ctx1 rank2 + ctx2 rank1
    assert score_y > score_z > score_x
    assert [hit.canonical_key for hit in result.entities] == ["y", "z", "x"]


def test_rrf_k0_affects_scores() -> None:
    ctx = _ctx(entities=[_entity("a")])
    small = RRFReranker(k0=1).rerank("q", [ctx], top_k=10)
    large = RRFReranker(k0=100).rerank("q", [ctx], top_k=10)
    # rank0 (1-based rank 1) → 1/(k0 + 1).
    assert small.entities[0].score == pytest.approx(1.0 / 2)
    assert large.entities[0].score == pytest.approx(1.0 / 101)


# ── RRFReranker: dedup, truncation, chunks, relations ──────────────────────────


def test_rrf_dedupes_entities_by_canonical_key() -> None:
    ctx1 = _ctx(entities=[_entity("a")])
    ctx2 = _ctx(entities=[_entity("a")])
    result = RRFReranker().rerank("q", [ctx1, ctx2], top_k=10)
    assert len(result.entities) == 1
    assert result.entities[0].canonical_key == "a"


def test_rrf_dedupes_chunks_by_id() -> None:
    ctx1 = _ctx(chunks=[_chunk("c1"), _chunk("c2")])
    ctx2 = _ctx(chunks=[_chunk("c1")])
    result = RRFReranker(k0=60).rerank("q", [ctx1, ctx2], top_k=10)
    keys = [hit.id for hit in result.chunks]
    assert keys == ["c1", "c2"]
    by_id = {hit.id: hit for hit in result.chunks}
    assert by_id["c1"].score == pytest.approx(1.0 / 61 + 1.0 / 61)
    assert by_id["c2"].score == pytest.approx(1.0 / 62)


def test_rrf_truncates_entities_and_chunks_to_top_k() -> None:
    entities = [_entity(f"e{i}") for i in range(5)]
    chunks = [_chunk(f"c{i}") for i in range(5)]
    result = RRFReranker().rerank(
        "q", [_ctx(entities=entities, chunks=chunks)], top_k=2
    )
    assert len(result.entities) == 2
    assert len(result.chunks) == 2
    assert [hit.canonical_key for hit in result.entities] == ["e0", "e1"]
    assert [hit.id for hit in result.chunks] == ["c0", "c1"]


def test_rrf_merges_and_dedupes_relations() -> None:
    rel_a = RelationHit(source_key="a", target_key="b", rel_type="R", description="d")
    rel_a_dup = RelationHit(
        source_key="a", target_key="b", rel_type="R", description="d"
    )
    rel_b = RelationHit(source_key="b", target_key="c", rel_type="R", description="")
    ctx1 = _ctx(relations=[rel_a, rel_b])
    ctx2 = _ctx(relations=[rel_a_dup])
    result = RRFReranker().rerank("q", [ctx1, ctx2], top_k=10)
    assert len(result.relations) == 2
    assert result.relations[0] == rel_a
    assert result.relations[1] == rel_b


def test_rrf_overwrites_incoming_scores_with_fused_scores() -> None:
    # Incoming similarity scores must be replaced by the RRF fused score.
    ctx = _ctx(entities=[_entity("a", score=0.99)])
    result = RRFReranker(k0=60).rerank("q", [ctx], top_k=10)
    assert result.entities[0].score == pytest.approx(1.0 / 61)


# ── CrossEncoderReranker ───────────────────────────────────────────────────────


class _FakeCrossEncoder:
    """Stand-in cross-encoder: score = length of the candidate text."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [float(len(candidate)) for _query, candidate in pairs]


def test_cross_encoder_raises_clear_error_when_dependency_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def _blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers":
            raise ImportError("no sentence_transformers")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    reranker = CrossEncoderReranker()
    with pytest.raises(RagError, match="sentence-transformers"):
        reranker.rerank("q", [_ctx(entities=[_entity("a")])], top_k=5)


def test_cross_encoder_empty_contexts_short_circuits() -> None:
    # No model load needed when there are no contexts.
    result = CrossEncoderReranker().rerank("q", [], top_k=5)
    assert result == RetrievalContext(query="q")


def test_cross_encoder_reranks_by_model_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reranker = CrossEncoderReranker()
    monkeypatch.setattr(reranker, "_load_model", lambda: _FakeCrossEncoder("fake"))
    # description lengths: "about short"=11, "about longerkey"=15 → longer wins.
    ctx = _ctx(
        entities=[_entity("short"), _entity("longerkey")],
        chunks=[_chunk("c1"), _chunk("c22")],
    )
    result = reranker.rerank("q", [ctx], top_k=10)
    assert [hit.canonical_key for hit in result.entities] == ["longerkey", "short"]
    # chunk texts: "text c1"=7, "text c22"=8 → c22 first.
    assert [hit.id for hit in result.chunks] == ["c22", "c1"]


def test_cross_encoder_dedupes_and_truncates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reranker = CrossEncoderReranker()
    monkeypatch.setattr(reranker, "_load_model", lambda: _FakeCrossEncoder("fake"))
    ctx1 = _ctx(entities=[_entity("a"), _entity("b")])
    ctx2 = _ctx(entities=[_entity("a"), _entity("c")])
    result = reranker.rerank("q", [ctx1, ctx2], top_k=2)
    # 3 unique entities (a, b, c) → truncated to 2.
    assert len(result.entities) == 2
    keys = {hit.canonical_key for hit in result.entities}
    assert keys <= {"a", "b", "c"}


def test_cross_encoder_model_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[str] = []

    def _factory(name: str) -> _FakeCrossEncoder:
        loaded.append(name)
        return _FakeCrossEncoder(name)

    monkeypatch.setattr(
        "runic.rag.adapters.reranking.CrossEncoder",
        _factory,
        raising=False,
    )

    # Patch the lazy import to use our factory via the module namespace.
    import runic.rag.adapters.reranking as mod

    real_import = builtins.__import__

    def _import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "sentence_transformers":
            ns = type(mod)("sentence_transformers")
            ns.CrossEncoder = _factory  # ty: ignore[unresolved-attribute]
            return ns
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)

    reranker = CrossEncoderReranker(model_name="custom-model")
    first = reranker._load_model()
    second = reranker._load_model()
    assert first is second
    assert loaded == ["custom-model"]
