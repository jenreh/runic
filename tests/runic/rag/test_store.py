"""Integration tests for :class:`runic.rag.store.GraphStore` against FalkorDB.

These require a live FalkorDB on localhost:6379 (provided by the
``falkordb_driver`` fixture, which skips when the server is unreachable).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pytest

from runic.rag.ontology import Ontology
from runic.rag.store import GraphStore

if TYPE_CHECKING:
    from runic.rag.config import RagSettings

pytestmark = pytest.mark.integration


def _unit(values: list[float], dim: int) -> list[float]:
    """Pad/truncate *values* to *dim* and return a unit vector."""
    vec = (values + [0.0] * dim)[:dim]
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def store(falkordb_driver: object, rag_settings: RagSettings) -> GraphStore:
    """A bootstrapped GraphStore on a live FalkorDB graph."""
    gs = GraphStore(
        falkordb_driver,
        rag_settings,
        schema_models=Ontology.default().schema_models(),
    )
    gs.bootstrap_schema()
    return gs


@pytest.fixture
def populated(
    store: GraphStore, rag_settings: RagSettings
) -> tuple[GraphStore, dict[str, list[float]]]:
    """Populate the graph: 2 chunks, 4 entities (2 near-dupes), relations."""
    dim = rag_settings.embedding_dim
    near_a = _unit([1.0, 0.0, 0.0], dim)
    near_b = _unit([0.99, 0.01, 0.0], dim)  # almost identical to near_a
    distinct_c = _unit([0.0, 1.0, 0.0], dim)
    distinct_d = _unit([0.0, 0.0, 1.0], dim)
    embeds = {
        "alice": near_a,
        "alicia": near_b,
        "acme": distinct_c,
        "berlin": distinct_d,
    }

    class _Chunk:
        def __init__(self, cid: str, text: str, seq: int, emb: list[float]) -> None:
            self.id = cid
            self.text = text
            self.seq = seq
            self.source = "doc1"
            self.embedding = emb

    with store.writer() as w:
        w.add_chunk(_Chunk("c0", "Alice founded Acme in Berlin.", 0, near_a))
        w.add_chunk(_Chunk("c1", "Alicia leads the Acme team.", 1, near_b))
        w.upsert_entity("person:alice", "Alice", "Person", "Founder.", near_a)
        w.upsert_entity("person:alicia", "Alicia", "Person", "Leader.", near_b)
        w.upsert_entity("org:acme", "Acme", "Organization", "A company.", distinct_c)
        w.upsert_entity("loc:berlin", "Berlin", "Location", "A city.", distinct_d)
        w.relate(
            "person:alice", "FOUNDED", "org:acme", "Alice founded Acme.", 0.9, "c0"
        )
        w.relate(
            "org:acme", "LOCATED_IN", "loc:berlin", "Acme is in Berlin.", 0.8, "c0"
        )
        w.mention("c0", "person:alice")
        w.mention("c0", "org:acme")
        w.mention("c0", "loc:berlin")
        w.mention("c1", "person:alicia")
        w.mention("c1", "org:acme")

    return store, embeds


def test_bootstrap_schema_is_idempotent(store: GraphStore) -> None:
    """Re-running bootstrap_schema tolerates already-existing indexes."""
    store.bootstrap_schema()  # second call must not raise


def test_vector_search_normalized_and_ordered(
    populated: tuple[GraphStore, dict[str, list[float]]],
) -> None:
    store, embeds = populated
    hits = store.vector_search(
        label="Entity", prop="embedding", query_vec=embeds["alice"], k=4
    )
    assert hits, "expected vector hits"
    # All scores normalized into [0, 1].
    assert all(0.0 <= h.score <= 1.0 for h in hits)
    # Best match is the identical vector with score ~1.0.
    assert hits[0].key == "person:alice"
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)
    # Near-duplicate ranks above the distinct entities.
    keys_in_order = [h.key for h in hits]
    assert keys_in_order.index("person:alicia") < keys_in_order.index("org:acme")
    # Scores are sorted descending.
    assert hits == sorted(hits, key=lambda h: h.score, reverse=True)


def test_vector_search_type_filter(
    populated: tuple[GraphStore, dict[str, list[float]]],
) -> None:
    store, embeds = populated
    hits = store.vector_search(
        label="Entity",
        prop="embedding",
        query_vec=embeds["alice"],
        k=10,
        type_filter="Person",
    )
    assert hits
    returned = {h.key for h in hits}
    assert returned <= {"person:alice", "person:alicia"}
    assert "org:acme" not in returned


def test_fulltext_search_finds_by_name(
    populated: tuple[GraphStore, dict[str, list[float]]],
) -> None:
    store, _ = populated
    hits = store.fulltext_search(label="Entity", prop="name", query="Alice", k=10)
    keys = {h.key for h in hits}
    assert "person:alice" in keys


def test_get_entities_provenance(
    populated: tuple[GraphStore, dict[str, list[float]]],
) -> None:
    store, _ = populated
    hits = store.get_entities(["person:alice", "org:acme"])
    by_key = {h.canonical_key: h for h in hits}
    assert by_key["person:alice"].name == "Alice"
    assert by_key["person:alice"].type == "Person"
    assert by_key["org:acme"].name == "Acme"


def test_expand_returns_entities_and_relations(
    populated: tuple[GraphStore, dict[str, list[float]]],
) -> None:
    store, _ = populated
    entities, relations = store.expand(["person:alice"], max_hops=2)
    entity_keys = {e.canonical_key for e in entities}
    # 2 hops from Alice -> Acme -> Berlin.
    assert {"person:alice", "org:acme", "loc:berlin"} <= entity_keys
    rel_pairs = {(r.source_key, r.target_key, r.rel_type) for r in relations}
    assert ("person:alice", "org:acme", "FOUNDED") in rel_pairs
    assert ("org:acme", "loc:berlin", "LOCATED_IN") in rel_pairs


def test_chunks_for_entities_ordered(
    populated: tuple[GraphStore, dict[str, list[float]]],
) -> None:
    store, _ = populated
    chunks = store.chunks_for_entities(["org:acme"], limit=10)
    ids = [c.id for c in chunks]
    assert set(ids) == {"c0", "c1"}
    # Ordered by seq ascending (lowest/first seq first).
    assert ids == ["c0", "c1"]
    assert all(c.source == "doc1" for c in chunks)
