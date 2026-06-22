"""Pure-unit tests for :mod:`runic.rag.store` (no live backend).

These cover the dialect-independent logic added for robustness: the
missing-index classifier, the bolt-URI parser, the loud bootstrap error when no
migrate adapter can be built, and the re-raise-vs-degrade behaviour of
:meth:`GraphStore.vector_search` / :meth:`GraphStore.fulltext_search`. They use
a scripted fake driver, so no FalkorDB/Neo4j is required.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from runic.rag.exceptions import ConfigError
from runic.rag.store import GraphStore, _is_index_missing, _parse_bolt_uri

if TYPE_CHECKING:
    from runic.rag.config import RagSettings


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = list(rows)


class _ScriptedDriver:
    """Raises *proc_error* on the KNN/fulltext proc; returns *brute_rows* otherwise."""

    def __init__(
        self, *, proc_error: Exception, brute_rows: list[tuple[Any, ...]] | None = None
    ) -> None:
        self._proc_error = proc_error
        self._brute_rows = brute_rows or []
        self.cyphers: list[str] = []

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> _FakeResult:
        self.cyphers.append(cypher)
        if "queryNodes" in cypher:  # the native vector/fulltext procedure
            raise self._proc_error
        return _FakeResult(self._brute_rows)


# ── _is_index_missing ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "There is no such index 'Entity_embedding'",
        "ERR Unable to locate vector index",
        "Unknown index name",
    ],
)
def test_is_index_missing_true_for_index_errors(message: str) -> None:
    assert _is_index_missing(Exception(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "Vector dimension mismatch, expected 16 but got 3",
        "Connection refused",
        "read timeout",
        "syntax error near 'CALL'",
        "some unrelated runtime failure",
    ],
)
def test_is_index_missing_false_for_hard_errors(message: str) -> None:
    assert _is_index_missing(Exception(message)) is False


# ── _parse_bolt_uri ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("bolt://localhost:7687", ("localhost", 7687)),
        ("bolt://neo4j.example.com:7000", ("neo4j.example.com", 7000)),
        ("bolt://host", ("host", 7687)),
        ("neo4j://h:9999/db", ("h", 9999)),
        ("bolt://localhost:notaport", ("localhost", 7687)),
    ],
)
def test_parse_bolt_uri(uri: str, expected: tuple[str, int]) -> None:
    assert _parse_bolt_uri(uri) == expected


# ── bootstrap_schema fails loudly without an adapter ──────────────────────────


def test_bootstrap_raises_configerror_without_adapter(
    rag_settings: RagSettings,
) -> None:
    # backend is falkordb but the driver exposes no falkordb_connection(), so no
    # migrate adapter can be built — must raise, never silently skip.
    driver = _ScriptedDriver(proc_error=RuntimeError("unused"))
    store = GraphStore(driver, rag_settings)
    with pytest.raises(ConfigError, match="bootstrap schema"):
        store.bootstrap_schema()


# ── vector_search: re-raise hard errors, degrade only on missing index ────────


def test_vector_search_reraises_hard_error(rag_settings: RagSettings) -> None:
    driver = _ScriptedDriver(
        proc_error=RuntimeError("Vector dimension mismatch, expected 16 but got 3"),
    )
    store = GraphStore(driver, rag_settings)
    with pytest.raises(RuntimeError, match="dimension mismatch"):
        store.vector_search(label="Entity", prop="embedding", query_vec=[1.0], k=5)


def test_vector_search_degrades_to_brute_force_on_missing_index(
    rag_settings: RagSettings,
) -> None:
    driver = _ScriptedDriver(
        proc_error=RuntimeError("There is no such index 'Entity_embedding'"),
        brute_rows=[("person:alice", [1.0, 0.0]), ("person:bob", [0.0, 1.0])],
    )
    store = GraphStore(driver, rag_settings)
    hits = store.vector_search(
        label="Entity", prop="embedding", query_vec=[1.0, 0.0], k=5
    )
    keys = {hit.key for hit in hits}
    assert keys == {"person:alice", "person:bob"}
    # The closest vector ranks first.
    assert hits[0].key == "person:alice"


# ── fulltext_search: re-raise hard errors, empty only on missing index ────────


def test_fulltext_search_reraises_hard_error(rag_settings: RagSettings) -> None:
    driver = _ScriptedDriver(proc_error=RuntimeError("Connection refused"))
    store = GraphStore(driver, rag_settings)
    with pytest.raises(RuntimeError, match="Connection refused"):
        store.fulltext_search(label="Entity", prop="name", query="alice", k=5)


def test_fulltext_search_empty_on_missing_index(rag_settings: RagSettings) -> None:
    driver = _ScriptedDriver(proc_error=RuntimeError("no such index 'Entity'"))
    store = GraphStore(driver, rag_settings)
    assert store.fulltext_search(label="Entity", prop="name", query="x", k=5) == []
