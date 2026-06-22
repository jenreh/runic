"""Unit tests for the two-stage entity resolver (no network).

Key normalization is asserted deterministically; duplicate detection uses the
deterministic :class:`~tests.runic.rag.fakes.FakeEmbedder` and a stub store that
returns controlled :class:`~runic.rag.domain.ScoredKey` lists (above/below/
within the grey band), so behaviour is fully reproducible.
"""

from __future__ import annotations

from runic.rag.adapters.resolution import (
    TwoStageResolver,
    normalize_text,
)
from runic.rag.config import RagSettings
from runic.rag.domain import ExtractedEntity, ScoredKey
from tests.runic.rag.fakes import FakeEmbedder

# ── Stub store ────────────────────────────────────────────────────────────────


class _StubStore:
    """Minimal GraphStore double recording the call and replaying canned hits."""

    def __init__(self, hits: list[ScoredKey]) -> None:
        self._hits = hits
        self.calls: list[dict[str, object]] = []

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
            {
                "label": label,
                "prop": prop,
                "query_vec": query_vec,
                "k": k,
                "type_filter": type_filter,
            }
        )
        return list(self._hits)


class _RecordingTiebreaker:
    """Tiebreaker returning a fixed decision and recording its invocation."""

    def __init__(self, decision: str | None) -> None:
        self._decision = decision
        self.calls: list[tuple[str, str]] = []

    def same_entity(self, entity: ExtractedEntity, candidate_key: str) -> str | None:
        self.calls.append((entity.name, candidate_key))
        return self._decision


def _settings(**overrides: object) -> RagSettings:
    """Settings with deterministic resolution thresholds for unit tests."""
    base: dict[str, object] = {
        "embedding_dim": 16,
        "openai_api_key": "sk-test",
        "resolve_threshold": 0.92,
        "tiebreak_low": 0.82,
        "tiebreak_high": 0.92,
        "llm_tiebreak": False,
    }
    base.update(overrides)
    # model_validate accepts a plain dict (no per-field kwarg type-checking on
    # an object-valued mapping), keeping ty happy for this dynamic test helper.
    return RagSettings.model_validate(base)


# ── Stage 1: canonical key normalization ──────────────────────────────────────


def test_normalize_text_casefolds_and_collapses_whitespace() -> None:
    assert normalize_text("  Hello   World  ") == "hello world"
    assert normalize_text("HELLO") == "hello"


def test_normalize_text_nfkc_unicode() -> None:
    # Composed vs decomposed "é" normalize to the same casefolded token.
    composed = "Café"  # é as a single code point
    decomposed = "Café"  # e + combining acute accent
    assert normalize_text(composed) == normalize_text(decomposed) == "café"
    # NFKC also folds compatibility forms (e.g. fullwidth digits/letters).
    assert normalize_text("ＡＢＣ") == "abc"  # ＡＢＣ -> abc


def test_canonical_key_is_type_and_normalized_name() -> None:
    resolver = TwoStageResolver(_settings())
    key = resolver.canonical_key(ExtractedEntity(name="  Alice  Smith ", type="Person"))
    assert key == "person:alice smith"


def test_canonical_key_stable_across_case_and_whitespace() -> None:
    resolver = TwoStageResolver(_settings())
    a = resolver.canonical_key(ExtractedEntity(name="ACME Corp", type="Organization"))
    b = resolver.canonical_key(ExtractedEntity(name="acme   corp", type="organization"))
    assert a == b == "organization:acme corp"


def test_canonical_key_unicode_equivalence() -> None:
    resolver = TwoStageResolver(_settings())
    composed = resolver.canonical_key(
        ExtractedEntity(name="Café Central", type="Location")
    )
    decomposed = resolver.canonical_key(
        ExtractedEntity(name="Café Central", type="Location")
    )
    assert composed == decomposed == "location:café central"


# ── Stage 2: duplicate detection ───────────────────────────────────────────────


def test_find_duplicate_above_threshold_merges() -> None:
    resolver = TwoStageResolver(_settings(resolve_threshold=0.92))
    store = _StubStore([ScoredKey(key="person:alicia", score=0.97)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    result = resolver.find_duplicate(entity, embedder.embed("Alice"), store)

    assert result == "person:alicia"


def test_find_duplicate_below_threshold_returns_none() -> None:
    resolver = TwoStageResolver(_settings(resolve_threshold=0.92))
    store = _StubStore([ScoredKey(key="org:acme", score=0.50)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    result = resolver.find_duplicate(entity, embedder.embed("Alice"), store)

    assert result is None


def test_find_duplicate_at_threshold_is_inclusive() -> None:
    # score == resolve_threshold must merge (>= boundary, not in grey band).
    resolver = TwoStageResolver(_settings(resolve_threshold=0.92))
    store = _StubStore([ScoredKey(key="person:robert", score=0.92)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Bob", type="Person")

    result = resolver.find_duplicate(entity, embedder.embed("Bob"), store)
    assert result == "person:robert"


def test_find_duplicate_no_hits_returns_none() -> None:
    resolver = TwoStageResolver(_settings())
    store = _StubStore([])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Nobody", type="Person")

    assert resolver.find_duplicate(entity, embedder.embed("Nobody"), store) is None


def test_find_duplicate_ignores_self_match() -> None:
    # The only hit is the entity's own canonical key -> not a duplicate.
    resolver = TwoStageResolver(_settings())
    store = _StubStore([ScoredKey(key="person:alice", score=1.0)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    assert resolver.find_duplicate(entity, embedder.embed("Alice"), store) is None


def test_find_duplicate_excludes_self_even_at_threshold() -> None:
    # A self-match is dropped before the threshold check, so even a >= score
    # for the entity's own key must not count as a duplicate.
    resolver = TwoStageResolver(_settings(resolve_threshold=0.92))
    store = _StubStore([ScoredKey(key="person:bob", score=0.99)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Bob", type="Person")  # own key == person:bob

    assert resolver.find_duplicate(entity, embedder.embed("Bob"), store) is None


def test_find_duplicate_skips_self_then_takes_next_candidate() -> None:
    resolver = TwoStageResolver(_settings(resolve_threshold=0.92))
    store = _StubStore(
        [
            ScoredKey(key="person:alice", score=1.0),  # self, ignored
            ScoredKey(key="person:alicia", score=0.95),  # real duplicate
        ]
    )
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    assert (
        resolver.find_duplicate(entity, embedder.embed("Alice"), store)
        == "person:alicia"
    )


def test_find_duplicate_passes_type_filter_and_embedding() -> None:
    resolver = TwoStageResolver(_settings())
    store = _StubStore([])
    embedder = FakeEmbedder(16)
    vec = embedder.embed("Alice")
    entity = ExtractedEntity(name="Alice", type="Person")

    resolver.find_duplicate(entity, vec, store)

    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["label"] == "Entity"
    assert call["prop"] == "embedding"
    assert call["type_filter"] == "Person"
    assert call["query_vec"] == vec


# ── Grey band / LLM tiebreak ────────────────────────────────────────────────────


def test_grey_band_without_tiebreak_does_not_merge() -> None:
    # Score in [0.82, 0.92) and llm_tiebreak off -> conservative no-merge.
    resolver = TwoStageResolver(_settings(llm_tiebreak=False))
    store = _StubStore([ScoredKey(key="person:alicia", score=0.85)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    assert resolver.find_duplicate(entity, embedder.embed("Alice"), store) is None


def test_grey_band_with_tiebreak_merges_on_positive_decision() -> None:
    tiebreaker = _RecordingTiebreaker(decision="person:alicia")
    resolver = TwoStageResolver(_settings(llm_tiebreak=True), tiebreaker=tiebreaker)
    store = _StubStore([ScoredKey(key="person:alicia", score=0.88)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    result = resolver.find_duplicate(entity, embedder.embed("Alice"), store)

    assert result == "person:alicia"
    assert tiebreaker.calls == [("Alice", "person:alicia")]


def test_grey_band_with_tiebreak_keeps_distinct_on_negative_decision() -> None:
    tiebreaker = _RecordingTiebreaker(decision=None)
    resolver = TwoStageResolver(_settings(llm_tiebreak=True), tiebreaker=tiebreaker)
    store = _StubStore([ScoredKey(key="person:alicia", score=0.88)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    result = resolver.find_duplicate(entity, embedder.embed("Alice"), store)

    assert result is None
    assert tiebreaker.calls == [("Alice", "person:alicia")]


def test_grey_band_with_tiebreak_enabled_but_no_tiebreaker_does_not_merge() -> None:
    resolver = TwoStageResolver(_settings(llm_tiebreak=True))
    store = _StubStore([ScoredKey(key="person:alicia", score=0.88)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    assert resolver.find_duplicate(entity, embedder.embed("Alice"), store) is None


def test_tiebreaker_not_consulted_above_threshold() -> None:
    # A clear duplicate must short-circuit before any LLM call.
    tiebreaker = _RecordingTiebreaker(decision=None)
    resolver = TwoStageResolver(_settings(llm_tiebreak=True), tiebreaker=tiebreaker)
    store = _StubStore([ScoredKey(key="person:alicia", score=0.99)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    assert (
        resolver.find_duplicate(entity, embedder.embed("Alice"), store)
        == "person:alicia"
    )
    assert tiebreaker.calls == []


def test_tiebreaker_not_consulted_below_grey_band() -> None:
    tiebreaker = _RecordingTiebreaker(decision="person:alicia")
    resolver = TwoStageResolver(
        _settings(llm_tiebreak=True, tiebreak_low=0.82), tiebreaker=tiebreaker
    )
    store = _StubStore([ScoredKey(key="person:alicia", score=0.50)])
    embedder = FakeEmbedder(16)
    entity = ExtractedEntity(name="Alice", type="Person")

    assert resolver.find_duplicate(entity, embedder.embed("Alice"), store) is None
    assert tiebreaker.calls == []


def test_resolver_satisfies_entity_resolver_protocol() -> None:
    from runic.rag.ports import EntityResolver

    resolver = TwoStageResolver(_settings())
    assert isinstance(resolver, EntityResolver)
