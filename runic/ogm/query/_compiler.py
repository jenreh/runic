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

from runic.ogm.core.descriptors import FieldDescriptor, FieldInfo
from runic.ogm.query._decoder import _ResultDecoder
from runic.ogm.query.expressions import (
    AggExpr,
    CompoundExpr,
    Expr,
    FilterExpr,
    NegatedExpr,
)

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
    _agg_exprs: list[AggExpr]
    _group_by_alias: str | None
    _project_fields: list[FieldDescriptor | str]
    _param_counter: int
    _params: dict[str, Any]

    # ------------------------------------------------------------------
    # Dialect access
    # ------------------------------------------------------------------

    @property
    def _dialect(self) -> Any:
        if self._session is None:
            return None
        return self._session.mapper.dialect

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
        alias = expr.alias or self._alias_for_cls(expr.cls)

        # Null checks have no parameter
        if expr.op == "IS NULL":
            return f"{alias}.{expr.prop} IS NULL"
        if expr.op == "IS NOT NULL":
            return f"{alias}.{expr.prop} IS NOT NULL"

        # Look up converter for this field
        fi = self._find_field_info(expr.cls, expr.prop)
        converter = fi.field.converter if fi is not None else None

        # Convert value to graph representation
        param_value = expr.value
        if converter is not None and param_value is not None:
            param_value = converter.to_graph(param_value)

        param_name = self._next_param(param_value)

        # Wrap param ref with cypher_fn if needed (dialect-aware)
        _d = self._dialect
        cypher_fn = (
            _d.cypher_fn_for_field(fi) if (fi is not None and _d is not None) else None
        )
        param_ref = f"{cypher_fn}(${param_name})" if cypher_fn else f"${param_name}"

        if expr.op in ("IN", "NOT IN"):
            prefix = "NOT " if (expr.negate or expr.op == "NOT IN") else ""
            return f"{prefix}{alias}.{expr.prop} IN ${param_name}"

        if expr.negate:
            return f"NOT ({alias}.{expr.prop} {expr.op} {param_ref})"
        return f"{alias}.{expr.prop} {expr.op} {param_ref}"

    def _compile_return(self) -> str:
        """Compile the RETURN clause."""
        distinct_kw = "DISTINCT " if self._distinct else ""

        # Aggregation mode
        if self._agg_exprs:
            cls_to_alias: dict[type, str] = {
                cls: aliases[0] for cls, aliases in self._cls_aliases.items() if aliases
            }
            agg_parts = [e.to_cypher(cls_to_alias) for e in self._agg_exprs]
            if self._group_by_alias:
                return (
                    f"RETURN {distinct_kw}{self._group_by_alias}, "
                    f"{', '.join(agg_parts)}"
                )
            return f"RETURN {distinct_kw}{', '.join(agg_parts)}"

        # Scalar projection
        if self._project_fields:
            proj_parts: list[str] = []
            for f in self._project_fields:
                if isinstance(f, FieldDescriptor):
                    alias = (
                        self._alias_for_cls(f.owner) if f.owner else self._root_alias
                    )
                    proj_parts.append(f"{alias}.{f.field_name}")
                else:
                    proj_parts.append(str(f))
            return f"RETURN {distinct_kw}{', '.join(proj_parts)}"

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
            if expr.alias is not None:
                return expr.alias == self._root_alias
            # No explicit alias: resolve via class lookup
            resolved = self._alias_for_cls(expr.cls)
            return resolved == self._root_alias
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

    def _find_field_info(self, cls: type, prop: str) -> FieldInfo | None:
        """Look up a FieldInfo by class and property name."""
        node_meta = self._meta.get_node_meta(cls)
        if node_meta:
            return next((fi for fi in node_meta.fields if fi.name == prop), None)
        edge_meta = self._meta.get_edge_meta(cls)
        if edge_meta:
            return next((fi for fi in edge_meta.fields if fi.name == prop), None)
        return None
