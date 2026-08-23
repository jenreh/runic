"""Catalogue parity against a real backend.

The unit suite proves runic *emits* the right Cypher; this one proves the
backend *accepts* it.  Every expressible statement has its parameters bound and
is executed against each configured backend — which is the only way a statement
ever gets checked rather than merely read, and is the test the reference
catalogue's docstring describes.

Run against all backends with::

    RUNIC_TEST_BACKENDS=falkordb,neo4j,memgraph,arcadedb,age task test:integration
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from runic.ogm.session.session import Session
from tests.runic.ogm.catalog_cases import (
    CATALOG_CASES,
    CatalogCase,
    statements,
)
from tests.runic.ogm.catalog_models import (
    Address,
    Group,
    Message,
    Template,
    Topic,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.integration


#: Index DDL per backend, for the indexes the search statements search.
#: Written as raw Cypher because index syntax is exactly the part that is not
#: portable — which is why runic keeps it behind an adapter rather than a
#: builder.
_SEARCH_INDEX_DDL: dict[str, tuple[str, ...]] = {
    "neo4j": (
        "CREATE VECTOR INDEX Message_embedding IF NOT EXISTS "
        "FOR (m:Message) ON (m.embedding) "
        "OPTIONS {indexConfig: {`vector.dimensions`: 4, "
        "`vector.similarity_function`: 'cosine'}}",
        "CREATE FULLTEXT INDEX Message IF NOT EXISTS "
        "FOR (m:Message) ON EACH [m.subject, m.body_clean]",
    ),
    "memgraph": (
        "CREATE VECTOR INDEX Message_embedding ON :Message(embedding) "
        "WITH CONFIG {'dimension': 4, 'capacity': 100, 'metric': 'cos'}",
        "CREATE TEXT INDEX Message ON :Message",
    ),
    "falkordb": (
        "CALL db.idx.fulltext.createNodeIndex('Message', 'subject', 'body_clean')",
    ),
}


def _ensure_search_indexes(driver: Any, backend: str) -> None:
    """Create the indexes the search statements need, where the backend has them.

    A search procedure with no index behind it fails at the driver — on FalkorDB
    with a message naming the yielded variable rather than the missing index.
    Backends with no Cypher-reachable index carry a recorded reason on the cases
    that need one.
    """
    if backend == "falkordb":
        from runic.ogm.schema.runtime_index import IndexOperations

        try:
            IndexOperations.from_driver(driver).create_vector_index(
                Message,
                Message.embedding,  # ty: ignore[invalid-argument-type]
                dimension=4,
            )
        except Exception:  # noqa: BLE001 - already present
            log.debug("vector index already present for the parity fixture")

    for statement in _SEARCH_INDEX_DDL.get(backend, ()):
        try:
            driver.execute(statement, {})
        except Exception:  # noqa: BLE001 - already present, or unsupported
            log.debug("parity fixture could not run index DDL: %s", statement)


@pytest.fixture
def seeded(graph_driver: Any) -> Any:
    """A graph holding one of everything the catalogue reads.

    Deliberately tiny: parity is about whether a statement runs and returns the
    shape it claims, not about result volume.  One message without a canonical
    id is included because several statements are defined by how they skip it.
    """
    with Session(graph_driver) as session:
        session.add(Message(id="m1", subject="Invoice 42", body_clean="please pay"))
        session.add(Message(id="m2", subject="Re: Invoice 42", body_clean="paid"))
        session.add(Message(id="", subject="no canonical id"))
        session.add(Address(id="a1"))
        session.add(Address(id="a2"))
        session.add(Group(id="g1", size=2, message_count=2))
        session.add(Topic(id="t1", label="billing", method="token"))
        session.add(Template(id="tpl1", direction="sent", occurrences=2))
        session.commit()
    _ensure_search_indexes(graph_driver, _backend_of(graph_driver))
    return graph_driver


def _ids(case: object) -> str:
    return case.name if isinstance(case, CatalogCase) else ""


def _backend_of(driver: Any) -> str:
    """Name the backend behind *driver*, for per-backend expectations."""
    dialect = type(driver.dialect).__name__.removesuffix("Dialect").lower()
    return {
        "falkordb": "falkordb",
        "neo4j": "neo4j",
        "memgraph": "memgraph",
        "arcadedb": "arcadedb",
        "age": "age",
    }.get(dialect, dialect)


@pytest.mark.parametrize("case", statements(), ids=_ids)
def test_statement_runs_against_backend(case: CatalogCase, seeded: Any) -> None:
    """Bind every parameter and execute — the statement must be accepted."""
    backend = _backend_of(seeded)
    if backend in case.unsupported:
        pytest.skip(f"{backend}: {case.unsupported[backend]}")
    stmt = case.build() if case.build else None
    assert stmt is not None

    with Session(seeded) as session:
        rows = session.all_rows(stmt, case.bind())

    assert isinstance(rows, list)


@pytest.mark.parametrize("case", statements(), ids=_ids)
def test_unbound_parameter_is_refused(case: CatalogCase, seeded: Any) -> None:
    """A statement must not run with a declared parameter left unbound.

    An unsupplied ``$parameter`` is a null in Cypher: it matches nothing and
    returns an empty result that looks exactly like an empty archive.  Failing
    loudly is the only way that distinction survives.
    """
    backend = _backend_of(seeded)
    if backend in case.unsupported:
        pytest.skip(f"{backend}: {case.unsupported[backend]}")
    if not case.params:
        pytest.skip("statement binds no caller input")
    stmt = case.build() if case.build else None
    assert stmt is not None

    with Session(seeded) as session, pytest.raises(ValueError, match="missing values"):
        session.all_rows(stmt, {})


@pytest.mark.parametrize("case", statements(), ids=_ids)
def test_bindings_cover_declared_parameters(case: CatalogCase) -> None:
    """Every declared parameter has a representative value.

    Guards the live suite against a statement that gains a parameter and then
    silently stops being executed with it bound.
    """
    assert set(case.bind()) == set(case.params)


_UPSERTS = [
    c for c in CATALOG_CASES if c.name.startswith("MERGE_") and c.is_expressible
]


@pytest.mark.parametrize("case", _UPSERTS, ids=_ids)
def test_upsert_is_idempotent(case: CatalogCase, seeded: Any) -> None:
    """Running an upsert twice must change nothing.

    This is the property MERGE exists for, and the one a derived layer's
    rebuild contract rests on. A CREATE would pass the "does it run" check
    above and still double every node on the second pass, because a derived
    label carries no unique constraint to stop it.
    """
    backend = _backend_of(seeded)
    if backend in case.unsupported:
        pytest.skip(f"{backend}: {case.unsupported[backend]}")
    stmt = case.build() if case.build else None
    assert stmt is not None

    def run_once() -> None:
        with Session(seeded) as session:
            session.all_rows(stmt, case.bind())
            # A Bolt backend does not make a write visible to a later session
            # until its transaction commits.
            session.commit()

    run_once()
    before = _written_shape(seeded, case)
    run_once()
    after = _written_shape(seeded, case)

    assert before == after, f"{case.name} is not idempotent: {before} -> {after}"


#: What each upsert writes, as the label or relationship type to count.
_WRITES: dict[str, tuple[str, str]] = {
    "MERGE_GROUPS": ("node", "Group"),
    "MERGE_TOPICS": ("node", "Topic"),
    "MERGE_TEMPLATES": ("node", "Template"),
    "MERGE_ADDRESSED_GROUP": ("edge", "ADDRESSED_GROUP"),
    "MERGE_ABOUT": ("edge", "ABOUT"),
    "MERGE_INSTANCE_OF": ("edge", "INSTANCE_OF"),
    "MERGE_CO_ADDRESSED": ("edge", "CO_ADDRESSED"),
}


def _written_shape(driver: Any, case: CatalogCase) -> int:
    """Count only what *case* writes.

    Counting the whole graph would measure every other test sharing the
    database, which on the Bolt backends is all of them.
    """
    kind, name = _WRITES[case.name]
    cypher = (
        f"MATCH (n:{name}) RETURN count(n) AS c"
        if kind == "node"
        else f"MATCH ()-[r:{name}]-() RETURN count(r) AS c"
    )
    with Session(driver) as session:
        return int(session.execute(cypher, {}).rows[0][0])


def test_vector_index_lifecycle(graph_driver: Any) -> None:
    """Create, observe, drop — the cycle a changed embedder forces.

    The dimension follows whichever model is configured, so re-indexing at a new
    length is a runtime operation rather than a migration.
    """
    from runic.ogm.schema.runtime_index import IndexOperations

    try:
        ops = IndexOperations.from_driver(graph_driver)
    except NotImplementedError as exc:
        pytest.skip(str(exc))

    def has_index() -> bool:
        return any(
            spec.label == "Message" and spec.property == "embedding"
            for spec in ops.describe()
        )

    ops.create_vector_index(Message, Message.embedding, dimension=4)  # ty: ignore[invalid-argument-type]
    assert has_index(), "index should be visible after creation"

    ops.resize_vector_index(Message, Message.embedding, dimension=8)  # ty: ignore[invalid-argument-type]
    assert has_index(), "index should survive a resize"

    ops.drop_vector_index(Message, Message.embedding)  # ty: ignore[invalid-argument-type]
    assert not has_index(), "index should be gone after drop"


def test_every_case_has_bindable_parameters() -> None:
    """Including the ones not yet expressible — bindings must not lag behind."""
    unbindable: dict[str, str] = {}
    for case in CATALOG_CASES:
        try:
            case.bind()
        except KeyError as exc:  # missing sample value
            unbindable[case.name] = str(exc)
    assert not unbindable, f"cases with unbindable parameters: {unbindable}"
