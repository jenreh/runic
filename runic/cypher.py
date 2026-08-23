"""Cypher escaping helpers shared by the migrate and OGM subsystems.

Cypher (and the FalkorDB/Neo4j/Memgraph dialects) cannot bind *identifiers*
(labels, relationship types, property keys) or DDL-internal string literals as
query parameters.  These helpers make such interpolation safe:

* :func:`escape_identifier` backtick-quotes an identifier, doubling embedded
  backticks.  Use it for pattern positions such as ``(n:{label})`` or
  ``[r:{rel_type}]``.
* :func:`escape_string` produces a single-quoted Cypher string literal with
  backslashes and single quotes escaped.  Use it for procedure string arguments
  and DDL option maps (for example ``CALL db.idx.fulltext.createNodeIndex``).

Both functions reject control characters, which can never appear in a legal
identifier or option value and are a strong signal of an injection attempt.

A second group validates *references* — the ``alias`` and ``alias.property``
strings the query builder accepts as an escape hatch in ``project()``,
``order_by()`` and ``project()``.  These are interpolated into RETURN and
ORDER BY, so they are validated rather than escaped: anything richer than a
property reference must be built from expression objects, not smuggled through
as text.
"""

from __future__ import annotations

import re

_CONTROL_CHARS = frozenset(chr(c) for c in range(0x20)) | {"\x7f"}

# Labels, relationship types, and similar schema identifiers that come from
# model *definitions* are interpolated directly into Cypher patterns
# (``(n:{label})``, ``[r:{rel_type}]``).  They are validated once at definition
# time against this pattern so every downstream interpolation is safe by
# construction — see :func:`validate_identifier`.
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """Return ``name`` if it is a safe Cypher schema identifier, else raise.

    Used at model-definition chokepoints (node labels, edge types, relationship
    types) so the value can be interpolated into Cypher patterns without risk of
    injection.  The accepted form is a simple identifier: a letter or underscore
    followed by letters, digits, or underscores.
    """
    if not isinstance(name, str) or not _IDENTIFIER_RE.fullmatch(name):
        msg = (
            f"invalid Cypher {kind} {name!r}; must match "
            f"{_IDENTIFIER_RE.pattern} (a letter/underscore followed by "
            "letters, digits, or underscores)"
        )
        raise ValueError(msg)
    return name


def _reject_control_chars(value: str, kind: str) -> None:
    if any(ch in _CONTROL_CHARS for ch in value):
        msg = f"illegal control character in Cypher {kind}: {value!r}"
        raise ValueError(msg)


def escape_identifier(name: str) -> str:
    """Return ``name`` as a backtick-quoted Cypher identifier.

    Embedded backticks are doubled so the value cannot break out of the quoting.
    Safe for use in pattern positions, e.g. ``f"(n:{escape_identifier(label)})"``.
    """
    _reject_control_chars(name, "identifier")
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def escape_string(value: str) -> str:
    """Return ``value`` as a single-quoted, escaped Cypher string literal.

    Backslashes and single quotes are escaped so the value cannot break out of
    the literal.  Safe for procedure arguments and DDL option maps, e.g.
    ``f"language: {escape_string(language)}"``.
    """
    _reject_control_chars(value, "string literal")
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


# A reference the query builder may interpolate into RETURN / ORDER BY: a bare
# Cypher variable (``n``, ``total``) or one property access on it (``n.id``).
# Deliberately no function calls, operators, or whitespace — richer expressions
# must be built from expression objects so their operands are bound, not typed.
_REFERENCE_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?")

_ORDER_DIRECTIONS = frozenset({"ASC", "DESC"})


def validate_reference(
    expr: str, kind: str = "reference", *, allow_star: bool = False
) -> str:
    """Return ``expr`` if it is a bare alias or ``alias.property``, else raise.

    The query builder interpolates these directly, so a value that is not a
    reference — a function call, a second clause, a comment — would execute as
    Cypher.  ``allow_star`` additionally permits ``"*"`` for ``count(*)``.
    """
    if allow_star and expr == "*":
        return expr
    if not isinstance(expr, str) or not _REFERENCE_RE.fullmatch(expr):
        star = ' or "*"' if allow_star else ""
        msg = (
            f"invalid Cypher {kind} {expr!r}; must be a bare alias or "
            f"'alias.property' reference{star} (use field descriptors or "
            "expression objects for anything richer)"
        )
        raise ValueError(msg)
    return expr


def validate_order_term(expr: str, kind: str = "order term") -> str:
    """Return ``expr`` if it is a reference with an optional ASC/DESC suffix.

    Accepts ``"n.created_at"``, ``"total DESC"``, ``"score asc"``.  Rejects
    anything that would let a caller append a clause to the ORDER BY.
    """
    if not isinstance(expr, str):
        raise ValueError(f"invalid Cypher {kind} {expr!r}; expected a string")
    parts = expr.split()
    if not parts or len(parts) > 2:
        msg = (
            f"invalid Cypher {kind} {expr!r}; expected 'reference' or "
            "'reference ASC|DESC'"
        )
        raise ValueError(msg)
    validate_reference(parts[0], kind)
    if len(parts) == 2 and parts[1].upper() not in _ORDER_DIRECTIONS:
        msg = (
            f"invalid sort direction {parts[1]!r} in Cypher {kind} {expr!r}; "
            "expected ASC or DESC"
        )
        raise ValueError(msg)
    return expr
