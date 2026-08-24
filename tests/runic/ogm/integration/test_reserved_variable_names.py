"""Each dialect's reserved-variable set, re-derived from the live backend.

``reserved_variable_names`` is an empirical fact about a parser, not a spec, so
it is checked by asking the parser rather than by trusting the list.  Every name
in :data:`WORDS` is tried in the positions runic actually emits a variable; a
name the backend refuses must be in the dialect's set, and a name it accepts
must not be (or the builder would reject an alias that works).

A drift in either direction is a real finding: the first means runic emits
Cypher a backend cannot parse, the second means runic refuses a name it could
have used.  Upgrading Apache AGE is the likely cause of either.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.integration

#: Cypher and openCypher keywords, plus the scalar/aggregate function names a
#: user might plausibly reach for as an alias.  Not exhaustive — no such list
#: exists for AGE — but wide enough that a grammar change shows up here.
WORDS: tuple[str, ...] = (
    "add",
    "after",
    "all",
    "alter",
    "and",
    "any",
    "as",
    "asc",
    "ascending",
    "before",
    "between",
    "both",
    "by",
    "call",
    "case",
    "coalesce",
    "collect",
    "commit",
    "constraint",
    "contains",
    "count",
    "create",
    "csv",
    "current",
    "cypher",
    "default",
    "delete",
    "desc",
    "descending",
    "detach",
    "distinct",
    "do",
    "drop",
    "each",
    "else",
    "end",
    "ends",
    "except",
    "exists",
    "explain",
    "extract",
    "false",
    "fieldterminator",
    "filter",
    "for",
    "foreach",
    "from",
    "group",
    "having",
    "headers",
    "if",
    "in",
    "index",
    "insert",
    "into",
    "is",
    "join",
    "key",
    "keys",
    "labels",
    "leading",
    "left",
    "length",
    "like",
    "limit",
    "load",
    "match",
    "max",
    "merge",
    "min",
    "nodes",
    "none",
    "not",
    "null",
    "of",
    "on",
    "only",
    "open",
    "optional",
    "or",
    "order",
    "profile",
    "properties",
    "range",
    "reduce",
    "relationships",
    "remove",
    "replace",
    "return",
    "right",
    "rollback",
    "rows",
    "scan",
    "set",
    "single",
    "size",
    "skip",
    "split",
    "start",
    "starts",
    "substring",
    "sum",
    "then",
    "trailing",
    "trim",
    "true",
    "type",
    "types",
    "union",
    "unique",
    "unwind",
    "using",
    "values",
    "when",
    "where",
    "with",
    "xor",
    "yield",
)

_LABEL = "RvnProbe"


def _usable_as_variable(driver: Any, word: str) -> bool:
    """True if *word* survives every position runic emits a variable in."""
    for cypher in (
        f"MATCH (w0:{_LABEL}) WITH w0 AS {word} RETURN {word}",
        f"MATCH ({word}:{_LABEL}) RETURN {word}",
        f"MATCH ({word}:{_LABEL}) RETURN {word}.id AS a",
    ):
        try:
            driver.execute(cypher, {})
        except Exception:
            rollback = getattr(driver, "rollback", None)
            if rollback is not None:
                # One syntax error aborts the transaction on AGE; without this
                # every later probe reports "current transaction is aborted"
                # and the whole sweep looks like a total failure.
                rollback()
            return False
    return True


@pytest.fixture
def probe_graph(graph_driver: Any) -> Any:
    graph_driver.execute(f"CREATE (n:{_LABEL} {{id: 1}}) RETURN n", {})
    return graph_driver


def test_declared_set_matches_the_live_parser(probe_graph: Any) -> None:
    """The dialect's set is exactly the names this backend actually refuses."""
    dialect = probe_graph.dialect
    declared = {w.lower() for w in dialect.reserved_variable_names}

    refused = {w for w in WORDS if not _usable_as_variable(probe_graph, w)}
    sampled = set(WORDS)

    missing = sorted(refused - declared)
    over_reach = sorted((declared & sampled) - refused)

    assert not missing, (
        f"{type(dialect).__name__} refuses these as variables but does not "
        f"declare them, so runic would emit Cypher it cannot parse: {missing}"
    )
    assert not over_reach, (
        f"{type(dialect).__name__} accepts these as variables but runic "
        f"refuses them, so a usable alias is being rejected: {over_reach}"
    )
