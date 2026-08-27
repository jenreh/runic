"""The compilation interface clauses and value expressions render against.

A renderer that reaches past :class:`CompilationContext` into the compiler's
own state is the thing these tests exist to catch: every clause and value below
is rendered through a context that implements the protocol and *nothing else*,
so any other attribute access raises :exc:`AttributeError` instead of quietly
coupling a sibling module to a private name.
"""

from __future__ import annotations

from typing import Any, get_protocol_members

import pytest

from runic.ogm import fulltext_search, select, vector_search
from runic.ogm.core.metadata import metadata as _real_meta
from runic.ogm.query.clauses import (
    CallClause,
    MatchClause,
    MergeClause,
    SetClause,
    UnwindClause,
    WithClause,
)
from runic.ogm.query.expressions import Expr, count
from runic.ogm.query.mutation import unwind
from runic.ogm.query.protocol import CompilationContext
from runic.ogm.query.values import literal, param, when
from tests.runic.ogm.catalog_models import Group, Message

_real_meta.finalize()

_PUBLISHED_MEMBERS = {
    "alias_for_cls",
    "bind_param",
    "cls_alias_map",
    "compile_agg",
    "compile_and",
    "compile_expr",
    "convert_for",
    "cypher_fn_for",
    "declare_param",
    "dialect",
    "expr_aliases",
    "params",
    "root_alias",
}


class _MinimalContext:
    """A CompilationContext with no compiler behind it.

    Implements exactly the published members, so reaching for anything else —
    ``_next_param``, ``_cls_aliases``, a builder attribute — fails loudly.
    """

    def __init__(self) -> None:
        self.root_alias = "n"
        self.params: dict[str, Any] = {}
        self.declared: list[str] = []
        self.counter = 0

    @property
    def dialect(self) -> Any:
        return None

    def bind_param(self, value: Any) -> str:
        name = f"q{self.counter}"
        self.counter += 1
        self.params[name] = value
        return name

    def declare_param(self, name: str) -> str:
        self.declared.append(name)
        return name

    def alias_for_cls(self, cls: type) -> str:
        return cls.__name__.lower()

    def cls_alias_map(self) -> dict[type, str]:
        return {Message: "n"}

    def expr_aliases(self, expr: Expr) -> set[str]:
        return {"n"}

    def compile_expr(self, expr: Expr) -> str:
        return "<predicate>"

    def compile_and(self, exprs: list[Expr]) -> str:
        return " AND ".join("<predicate>" for _ in exprs)

    def compile_agg(self, agg: Any, cls_to_alias: dict[type, str]) -> str:
        return "<aggregate>"

    def cypher_fn_for(self, alias: str, prop: str) -> str | None:
        return "vecf32" if prop == "embedding" else None

    def convert_for(self, alias: str, prop: str, value: Any) -> Any:
        return value


@pytest.fixture
def ctx() -> _MinimalContext:
    return _MinimalContext()


class TestTheInterfaceItself:
    def test_names_exactly_the_published_members(self) -> None:
        assert get_protocol_members(CompilationContext) == _PUBLISHED_MEMBERS

    def test_the_minimal_context_satisfies_it(self, ctx: _MinimalContext) -> None:
        assert isinstance(ctx, CompilationContext)

    @pytest.mark.parametrize(
        "statement",
        [
            select(Message),
            select(Message).traverse(Message.sent_to),
            fulltext_search(Message, query=param("text")),
            vector_search(Message.embedding, vector=param("vec"), k=5),
            unwind(param("rows")),
        ],
        ids=["select", "traversal", "fulltext", "vector", "mutation"],
    )
    def test_every_builder_flavour_implements_it(self, statement: Any) -> None:
        assert isinstance(statement, CompilationContext)


class TestClausesRenderThroughTheInterface:
    def test_match_checks_the_dialect(self, ctx: _MinimalContext) -> None:
        clause = MatchClause("(a)-[:T]->(b)", requires=("procedure_call", "CALL"))
        assert clause.to_cypher(ctx) == "MATCH (a)-[:T]->(b)"

    def test_merge_checks_the_dialect(self, ctx: _MinimalContext) -> None:
        clause = MergeClause("(a)-[:T]->(b)", requires=("undirected_merge", "MERGE"))
        assert clause.to_cypher(ctx) == "MERGE (a)-[:T]->(b)"

    def test_with_compiles_its_having_clause(self, ctx: _MinimalContext) -> None:
        clause = WithClause(variables=("n",), where=(Message.id > "a",))  # ty: ignore[invalid-argument-type]
        assert clause.to_cypher(ctx) == "WITH n\nWHERE <predicate>"

    def test_with_renders_an_aggregate_variable(self, ctx: _MinimalContext) -> None:
        clause = WithClause(variables=("n", count(Message.id).as_("c")))
        assert clause.to_cypher(ctx) == "WITH n, <aggregate>"

    def test_unwind_binds_its_source(self, ctx: _MinimalContext) -> None:
        assert UnwindClause(source=[{"id": 1}]).to_cypher(ctx) == "UNWIND $q0 AS row"
        assert ctx.params == {"q0": [{"id": 1}]}

    def test_set_converts_and_wraps_the_value(self, ctx: _MinimalContext) -> None:
        clause = SetClause(assignments=(("n", "embedding", [0.5]), ("n", "id", "x")))
        assert clause.to_cypher(ctx) == (
            "SET n.`embedding` = vecf32($q0), n.`id` = $q1"
        )
        assert ctx.params == {"q0": [0.5], "q1": "x"}

    def test_call_checks_the_dialect_and_binds_its_args(
        self, ctx: _MinimalContext
    ) -> None:
        clause = CallClause(
            procedure="db.idx.fulltext.queryNodes",
            args=("Message", 3),
            yields=("node",),
            requires=("procedure_call", "CALL … YIELD"),
        )
        assert clause.to_cypher(ctx) == (
            "CALL db.idx.fulltext.queryNodes('Message', $q0) YIELD node"
        )


class TestValuesRenderThroughTheInterface:
    def test_literal_binds_a_parameter(self, ctx: _MinimalContext) -> None:
        assert literal(42).to_cypher(ctx) == "$q0"
        assert ctx.params == {"q0": 42}

    def test_param_declares_instead_of_binding(self, ctx: _MinimalContext) -> None:
        assert param("after").to_cypher(ctx) == "$after"
        assert ctx.declared == ["after"]
        assert ctx.params == {}

    def test_a_bare_field_resolves_its_alias(self, ctx: _MinimalContext) -> None:
        case = when(Message.id == "a", Message.id)  # ty: ignore[invalid-argument-type]
        assert case.to_cypher(ctx) == ("CASE WHEN <predicate> THEN message.`id` END")

    def test_case_reports_the_aliases_its_branches_read(
        self, ctx: _MinimalContext
    ) -> None:
        case = when(Message.id == "a", Group.id)  # ty: ignore[invalid-argument-type]
        assert case.referenced_aliases(ctx) == {"n", "group"}

    def test_the_root_alias_is_readable_from_a_statement(self) -> None:
        # The fallback a deferred PropertyRef takes when nothing owns it.
        assert select(Message).root_alias == "n"
        assert select(Message, "m").root_alias == "m"
