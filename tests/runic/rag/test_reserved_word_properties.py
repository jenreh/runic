"""``GraphStore``'s label and property arguments survive being reserved words.

:class:`~runic.rag.store.GraphStore` takes ``label`` and ``prop`` as arguments
and interpolates them into Cypher — they are not model attributes the OGM quotes
on the caller's behalf.  The rag adapters pass fixed names, but the store is a
public surface, so a caller may hand it whatever property their graph uses.

Apache AGE reads an unquoted ``n.count`` as the aggregate function and rejects
the statement, which without quoting made the store unusable for such a graph.
The live tests here drive the portable brute-force paths — the ones Memgraph,
ArcadeDB and AGE take, and the only ones that build a property reference out of
the argument — while the procedure builders, which pass the same names as Cypher
*string literals*, are checked directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from runic.rag.config import RagSettings
from runic.rag.store import (
    GraphStore,
    _falkordb_fulltext_proc,
    _falkordb_vector_proc,
    _neo4j_fulltext_proc,
    _neo4j_vector_proc,
)
from tests._backends import enabled_backends, make_driver, random_graph_name

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# Procedure builders — the label/property reach Cypher as string literals
# ---------------------------------------------------------------------------


class TestProcedureArguments:
    """A label or property is a *quoted literal* to these procs, not an identifier.

    They are still interpolated, so they still need escaping — a name carrying a
    quote would otherwise close the literal and continue as Cypher.
    """

    def test_falkordb_vector_proc_quotes_its_arguments(self) -> None:
        assert _falkordb_vector_proc("Entity", "count", 10) == (
            "CALL db.idx.vector.queryNodes('Entity', 'count', 10, vecf32($q)) "
            "YIELD node, score"
        )

    def test_neo4j_vector_proc_quotes_its_index_name(self) -> None:
        assert _neo4j_vector_proc("Entity", "count", 10) == (
            "CALL db.index.vector.queryNodes('Entity_count', $k, $q) YIELD node, score"
        )

    def test_fulltext_procs_quote_the_label(self) -> None:
        assert "'Entity'" in _falkordb_fulltext_proc("Entity")
        assert "'Entity'" in _neo4j_fulltext_proc("Entity")

    @pytest.mark.parametrize(
        "builder",
        [_falkordb_vector_proc, _neo4j_vector_proc],
        ids=["falkordb", "neo4j"],
    )
    def test_a_quote_cannot_escape_the_literal(self, builder: Any) -> None:
        """The escape hatch a bare f-string left open."""
        emitted = builder("Ent'ity", "prop", 1)
        assert "\\'" in emitted

    def test_a_control_character_is_refused(self) -> None:
        with pytest.raises(ValueError, match="control character"):
            _falkordb_vector_proc("Ent\nity", "prop", 1)


# ---------------------------------------------------------------------------
# Live: the brute-force paths build `alias.prop` from the argument
# ---------------------------------------------------------------------------

pytestmark_live = pytest.mark.integration


@pytest.fixture(params=enabled_backends())
def rw_driver(request: pytest.FixtureRequest) -> Iterator[Any]:
    """A live driver per configured backend, with its own graph."""
    backend: str = request.param
    driver, cleanup = make_driver(backend, random_graph_name(f"ragrw_{backend}"))
    driver.__runic_backend__ = backend
    yield driver
    cleanup()


def _store(driver: Any, *, brute_force: bool = True) -> GraphStore:
    """A store over *driver*.

    ``brute_force`` pins the settings backend to one with no native vector or
    fulltext procedure, so the portable path runs without a bootstrapped index.
    That path is the real one for Memgraph, ArcadeDB and AGE — including the
    backend this fix exists for.
    """
    backend = "memgraph" if brute_force else driver.__runic_backend__
    settings = RagSettings.model_validate(
        {"backend": backend, "embedding_dim": 3, "openai_api_key": "sk-test"}
    )
    return GraphStore(driver, settings)


@pytest.fixture
def seeded(rw_driver: Any) -> Any:
    """Nodes carrying reserved-word properties."""
    for i, key in enumerate(("k1", "k2"), start=1):
        rw_driver.execute(
            "CREATE (n:Entity {canonical_key: $key, name: $name, "
            "description: $desc, `count`: $vec, `end`: $txt, `order`: $vec}) "
            "RETURN n",
            {
                "key": key,
                "name": f"entity {i}",
                "desc": f"description {i}",
                "vec": [float(i), 0.0, 0.0],
                "txt": f"invoice {i}",
            },
        )
        # A non-Entity label so the fulltext fallback takes its `n.<prop>`
        # branch; for Entity it matches name+description and never reads *prop*.
        rw_driver.execute(
            "CREATE (n:RwDoc {id: $key, `end`: $txt}) RETURN n",
            {"key": key, "txt": f"invoice {i}"},
        )
    return rw_driver


@pytest.fixture
def store(seeded: Any) -> GraphStore:
    return _store(seeded)


@pytest.mark.integration
@pytest.mark.parametrize("prop", ["count", "order"])
def test_vector_search_over_a_reserved_property(store: GraphStore, prop: str) -> None:
    """The brute-force KNN reads the embedding through the property argument."""
    hits = store.vector_search(
        label="Entity", prop=prop, query_vec=[1.0, 0.0, 0.0], k=2
    )
    assert {h.key for h in hits} == {"k1", "k2"}


@pytest.mark.integration
def test_fulltext_search_over_a_reserved_property(store: GraphStore) -> None:
    """The portable token-overlap path builds `n.<prop>` from the argument."""
    hits = store.fulltext_search(label="RwDoc", prop="end", query="invoice", k=5)
    assert {h.key for h in hits} == {"k1", "k2"}


@pytest.mark.integration
def test_vector_search_with_a_type_filter(store: GraphStore) -> None:
    """The filtered branch emits its own WHERE over the same node."""
    hits = store.vector_search(
        label="Entity",
        prop="count",
        query_vec=[1.0, 0.0, 0.0],
        k=2,
        type_filter="Missing",
    )
    assert hits == []


@pytest.mark.integration
def test_a_label_that_is_a_reserved_word(rw_driver: Any) -> None:
    """The label goes into a MATCH pattern, and is quoted the same way."""
    rw_driver.execute(
        "CREATE (n:`Match` {id: $k, `count`: $v}) RETURN n",
        {"k": "m1", "v": [1.0, 0.0, 0.0]},
    )
    hits = _store(rw_driver).vector_search(
        label="Match", prop="count", query_vec=[1.0, 0.0, 0.0], k=1
    )
    assert [h.key for h in hits] == ["m1"]
