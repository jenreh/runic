"""Cypher compilation for the runic query builder.

:class:`_CypherCompiler` extends :class:`~runic.ogm.query._decoder._ResultDecoder`
and owns the single responsibility of turning the builder's accumulated state
(WHERE/RETURN/aggregation/projection specs) into Cypher fragments, plus the
alias/parameter/field-lookup helpers those fragments rely on.  It is internal;
:class:`~runic.ogm.query.builder.QueryBuilder` inherits it and orchestrates the
full ``build()``.
"""

from __future__ import annotations

from typing import Any, TypeVar

from runic.cypher import validate_reference
from runic.ogm.core.descriptors import FieldDescriptor, FieldInfo
from runic.ogm.query._decoder import _ResultDecoder
from runic.ogm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    NegatedExpr,
)
from runic.ogm.query.values import ValueExpr

T = TypeVar("T")


class _CypherCompiler(_ResultDecoder[T]):  # noqa: UP046
    """Compile builder state into Cypher predicate / RETURN fragments.

    State attributes are populated by :meth:`QueryBuilder.__init__`; they are
    declared here so the compile methods type-check against the shared state.
    """

    _cls_aliases: dict[type, list[str]]
    _root_alias: str
    _where_exprs: list[Expr]
    _distinct: bool
    _project_fields: list[FieldDescriptor | ValueExpr | AggExpr | str]
    _alias_map: dict[str, type]
    _returning: list[Any]
    _param_counter: int
    _params: dict[str, Any]
    _declared_params: set[str]
    _limit_val: Any
    _skip_val: Any

    # ------------------------------------------------------------------
    # Dialect access
    # ------------------------------------------------------------------

    @property
    def _dialect(self) -> Any:
        if self._session is None:
            return None
        return self._session.mapper.dialect

    def _require_dialect(self) -> Any:
        """The session's dialect, or the default when the statement is unbound.

        A statement built by ``select()`` has no session until it is executed,
        but it still has to compile — ``parameter_names()`` and ``build()`` are
        both useful on an unbound statement, and a procedure-rooted one needs a
        dialect to know which procedure to name. The default matches
        :class:`~runic.ogm.mapper.mapper.Mapper`'s, so an unbound statement
        compiles the same way a FalkorDB-bound one does.
        """
        dialect = self._dialect
        if dialect is not None:
            return dialect
        from runic.ogm.driver.falkordb import FalkorDBDialect

        return FalkorDBDialect()

    # ------------------------------------------------------------------
    # Internal: Cypher expression compilation
    # ------------------------------------------------------------------

    def _compile_expr(self, expr: Expr) -> str:
        """Recursively compile an Expr tree to a Cypher predicate string."""
        if isinstance(expr, FilterExpr):
            return self._compile_filter(expr)
        if isinstance(expr, CompoundExpr):
            parts = [f"({self._compile_expr(op)})" for op in expr.operands]
            return f" {expr.op} ".join(parts)
        if isinstance(expr, NegatedExpr):
            return f"NOT ({self._compile_expr(expr.operand)})"
        raise TypeError(f"Unsupported expression type: {type(expr)!r}")

    def _compile_filter(self, expr: FilterExpr) -> str:
        """Compile a single FilterExpr to a Cypher condition string."""
        from runic.ogm.query.values import ValueExpr

        # Left-hand side: usually ``alias.prop``, but a ValueExpr when the
        # predicate compares something richer (another property, a function).
        if isinstance(expr.left, ValueExpr):
            lhs = expr.left.to_cypher(self)
        else:
            alias = expr.alias or self._alias_for_cls(expr.cls)
            lhs = f"{alias}.{expr.prop}"

        # Null checks have no parameter
        if expr.op == "IS NULL":
            return f"{lhs} IS NULL"
        if expr.op == "IS NOT NULL":
            return f"{lhs} IS NOT NULL"

        param_ref = self._compile_operand(expr)

        if expr.op in ("IN", "NOT IN"):
            prefix = "NOT " if (expr.negate or expr.op == "NOT IN") else ""
            # ``reverse`` asks the opposite question: is this value an element
            # of the stored list, rather than is this property one of these
            # values.  A list-valued property needs the former.
            if expr.reverse:
                return f"{prefix}{param_ref} IN {lhs}"
            return f"{prefix}{lhs} IN {param_ref}"

        if expr.negate:
            return f"NOT ({lhs} {expr.op} {param_ref})"
        return f"{lhs} {expr.op} {param_ref}"

    def _compile_operand(self, expr: FilterExpr) -> str:
        """Render a predicate's right-hand side, binding it unless it is an expression.

        A plain Python value is converted by the field's ``TypeConverter`` and
        bound as a parameter, with the dialect's ``cypher_fn`` wrapper applied
        where one is declared (``vecf32``, ``point``, ``intern``).  A
        :class:`~runic.ogm.query.values.ValueExpr` renders itself instead, which
        is how a property-to-property comparison avoids a parameter altogether.
        """
        from runic.ogm.query.values import ValueExpr

        if isinstance(expr.value, ValueExpr):
            return expr.value.to_cypher(self)
        if isinstance(expr.value, FieldDescriptor):
            # A field compared against a field: render the property reference
            # rather than binding the descriptor object as a parameter.
            from runic.ogm.query.values import _prop_ref

            return _prop_ref(expr.value).to_cypher(self)

        fi = self._find_field_info(expr.cls, expr.prop)
        converter = fi.field.converter if fi is not None else None

        param_value = expr.value
        if converter is not None and param_value is not None:
            param_value = converter.to_graph(param_value)

        param_name = self._next_param(param_value)

        _d = self._dialect
        cypher_fn = (
            _d.cypher_fn_for_field(fi) if (fi is not None and _d is not None) else None
        )
        return f"{cypher_fn}(${param_name})" if cypher_fn else f"${param_name}"

    def _compile_return(self) -> str:
        """Compile the RETURN clause.

        Cypher has no GROUP BY: every non-aggregated RETURN item is a grouping
        key, so a projection mixing plain values and aggregates *is* the
        grouped query — ``project(u, count("*").as_("n"))`` → ``RETURN u,
        count(*) AS n``.
        """
        distinct_kw = "DISTINCT " if self._distinct else ""

        # Explicit expressions, set by returning() — usually a write reporting
        # what it did.
        if self._returning:
            rendered = [self._compile_return_item(v) for v in self._returning]
            return f"RETURN {distinct_kw}{', '.join(rendered)}"

        # Projection — values, aggregates, or both
        if self._project_fields:
            return f"RETURN {distinct_kw}{', '.join(self._compile_projection())}"

        # Explicit return aliases
        if self._return_aliases:
            all_parts = list(self._return_aliases)
            if (
                self._edge_alias_for_result
                and self._edge_alias_for_result not in all_parts
            ):
                # Insert edge between the two node aliases
                all_parts.insert(1, self._edge_alias_for_result)
            return f"RETURN {distinct_kw}{', '.join(all_parts)}"

        # Default: return last alias
        return f"RETURN {distinct_kw}{self._last_alias}"

    def _compile_projection(self) -> list[str]:
        """Render every projected item, auto-naming bare fields.

        A bare field is emitted as ``alias.prop AS prop`` so result rows are
        keyed by the field's own name rather than ``"n.prop"``.  Two items
        auto-naming to the same column is ambiguous and raises — ``.as_()``
        one of them.
        """
        parts: list[str] = []
        seen: dict[str, Any] = {}
        for item in self._project_fields:
            rendered, name = self._compile_projection_item(item)
            if name is not None:
                if name in seen:
                    msg = (
                        f"projection names the column {name!r} twice; "
                        f"rename one with .as_()"
                    )
                    raise ValueError(msg)
                seen[name] = item
            parts.append(rendered)
        return parts

    def _compile_projection_item(self, item: Any) -> tuple[str, str | None]:
        """Render one projected item; return ``(cypher, result_column_name)``.

        The name is ``None`` when nothing is claimed: a raw string passes
        through verbatim, and a computed expression without ``.as_()`` gets
        whatever name the store reports.
        """
        from runic.ogm.query.values import (
            Alias,
            AliasedExpr,
            PropertyRef,
            _prop_ref,
        )

        if isinstance(item, AggExpr):
            return self._compile_agg(item, self._cls_alias_map()), item.result_alias
        if isinstance(item, AliasedExpr):
            return item.to_cypher(self), item.alias
        if isinstance(item, Alias):
            return item.to_cypher(self), item.to_cypher(self)
        if isinstance(item, FieldDescriptor):
            item = _prop_ref(item)
        if isinstance(item, PropertyRef) and item.prop:
            return f"{item.to_cypher(self)} AS {item.prop}", item.prop
        if isinstance(item, ValueExpr):
            return item.to_cypher(self), None
        return validate_reference(str(item), "projection"), None

    def _compile_return_item(self, value: Any) -> str:
        """Render one explicit RETURN expression, aggregate or value."""
        from runic.ogm.query.expressions import AggExpr as _Agg

        if isinstance(value, _Agg):
            return self._compile_agg(value, self._cls_alias_map())
        return self._compile_value(value)

    def _cls_alias_map(self) -> dict[type, str]:
        """First registered Cypher variable per OGM class, for aggregates."""
        return {
            cls: aliases[0] for cls, aliases in self._cls_aliases.items() if aliases
        }

    def _compile_agg(self, agg: AggExpr, cls_to_alias: dict[type, str]) -> str:
        """Render one aggregation, whose operand may be a value expression.

        ``count(when(...))`` is the case that matters: several differently
        filtered counts over a single scan, which is otherwise several queries
        whose populations can drift apart.
        """
        from runic.ogm.query.values import ValueExpr

        if isinstance(agg.field, ValueExpr):
            distinct_kw = "DISTINCT " if agg.distinct else ""
            rendered = f"{agg.func}({distinct_kw}{agg.field.to_cypher(self)})"
            return f"{rendered} AS {agg.result_alias}" if agg.result_alias else rendered
        return agg.to_cypher(cls_to_alias)

    def _compile_paging(self) -> list[str]:
        """Render SKIP / LIMIT, which may be integers or bound parameters."""
        from runic.ogm.query.values import ValueExpr

        parts: list[str] = []
        for keyword, value in (("SKIP", self._skip_val), ("LIMIT", self._limit_val)):
            if value is None:
                continue
            rendered = value.to_cypher(self) if isinstance(value, ValueExpr) else value
            parts.append(f"{keyword} {rendered}")
        return parts

    def _compile_value(self, value: Any) -> str:
        """Render one RETURN / ORDER BY item, whatever form it takes.

        Accepts a :class:`~runic.ogm.query.values.ValueExpr`, a field descriptor,
        or a validated raw reference string.
        """
        from runic.ogm.query.values import ValueExpr, _prop_ref

        if isinstance(value, ValueExpr):
            return value.to_cypher(self)
        if isinstance(value, FieldDescriptor):
            return _prop_ref(value).to_cypher(self)
        return validate_reference(str(value), "projection")

    def _expr_aliases(self, expr: Expr) -> set[str]:
        """The Cypher variables *expr* reads, across both operands and nesting."""
        from runic.ogm.query.values import ValueExpr, _aliases_of

        if isinstance(expr, FilterExpr):
            found: set[str] = set()
            if isinstance(expr.left, ValueExpr):
                found |= expr.left.referenced_aliases(self)
            else:
                found.add(expr.alias or self._alias_for_cls(expr.cls))
            found |= _aliases_of((expr.value,), self)
            return found
        if isinstance(expr, CompoundExpr):
            found = set()
            for operand in expr.operands:
                found |= self._expr_aliases(operand)
            return found
        if isinstance(expr, NegatedExpr):
            return self._expr_aliases(expr.operand)
        return {self._root_alias}

    def _split_where_exprs(self) -> tuple[list[Expr], list[Expr]]:
        """Split WHERE expressions into root-targeting and post-traversal groups.

        Root expressions reference only the root alias (or its class) and are
        safe to emit between the root MATCH and any OPTIONAL MATCH clauses.
        Post-traversal expressions reference traversal targets or edges and must
        come after all MATCH/OPTIONAL MATCH clauses.
        """
        root: list[Expr] = []
        post: list[Expr] = []
        for expr in self._where_exprs:
            if self._expr_targets_root_only(expr):
                root.append(expr)
            else:
                post.append(expr)
        return root, post

    def _expr_targets_root_only(self, expr: Expr) -> bool:
        """Return True if *expr* references only the root Cypher alias."""
        if isinstance(expr, FilterExpr):
            # Both operands matter. ``a.id < b.id`` looks root-targeting from
            # the left, but emitting it before the MATCH that introduces ``b``
            # is invalid Cypher — so a predicate is a root condition only when
            # every variable it reads is the root one.  A parameter or literal
            # reads nothing and constrains nothing.
            return self._expr_aliases(expr) <= {self._root_alias}
        if isinstance(expr, CompoundExpr):
            return all(self._expr_targets_root_only(op) for op in expr.operands)
        if isinstance(expr, NegatedExpr):
            return self._expr_targets_root_only(expr.operand)
        return False

    # ------------------------------------------------------------------
    # Internal: alias / parameter / field helpers
    # ------------------------------------------------------------------

    def _alias_for_cls(self, cls: type) -> str:
        """Return the first registered Cypher alias for *cls*, or root alias."""
        aliases = self._cls_aliases.get(cls)
        if aliases:
            return aliases[0]
        # Fallback: if cls is the root, return root alias
        if cls is self._root_cls:
            return self._root_alias
        return self._last_alias

    def _next_param(self, value: Any) -> str:
        """Allocate a new positional parameter, store value, return name."""
        name = f"p{self._param_counter}"
        self._param_counter += 1
        self._params[name] = value
        return name

    def declare_param(self, name: str) -> str:
        """Record a caller-bound parameter encountered during compilation.

        Unlike :meth:`_next_param`, no value is stored: the statement declares
        that it expects ``$name`` and the caller supplies it at execution.  This
        is what makes a statement reusable as a module-level constant.
        """
        self._declared_params.add(name)
        return name

    def _field_info_for_alias(self, alias: str, prop: str) -> FieldInfo | None:
        """Look up a field by the Cypher variable it is written through."""
        cls = self._alias_map.get(alias)
        return self._find_field_info(cls, prop) if cls is not None else None

    def _cypher_fn_for(self, alias: str, prop: str) -> str | None:
        """The dialect's wrapping function for a property, if it declares one.

        ``vecf32``, ``point`` and ``intern`` have to wrap a value on its way in
        or the backend stores something it cannot index.
        """
        fi = self._field_info_for_alias(alias, prop)
        dialect = self._dialect
        if fi is None or dialect is None:
            return None
        return dialect.cypher_fn_for_field(fi)  # type: ignore[no-any-return]

    def _convert_for(self, alias: str, prop: str, value: Any) -> Any:
        """Apply a field's TypeConverter to a value being written."""
        fi = self._field_info_for_alias(alias, prop)
        converter = fi.field.converter if fi is not None else None
        if converter is None or value is None:
            return value
        return converter.to_graph(value)

    def _find_field_info(self, cls: type, prop: str) -> FieldInfo | None:
        """Look up a FieldInfo by class and property name."""
        node_meta = self._meta.get_node_meta(cls)
        if node_meta:
            return next((fi for fi in node_meta.fields if fi.name == prop), None)
        edge_meta = self._meta.get_edge_meta(cls)
        if edge_meta:
            return next((fi for fi in edge_meta.fields if fi.name == prop), None)
        return None
