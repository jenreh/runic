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
