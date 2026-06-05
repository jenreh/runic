"""Shared Cypher result-mapping logic for Repository and AsyncRepository."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from runic.orm.mapper.mapper import Mapper

log = logging.getLogger(__name__)

_SCALAR_TYPES: frozenset[type] = frozenset({int, float, str, bool})


def map_cypher_result(
    result: Any,
    returns: type | None,
    mapper: Mapper,
    register_fn: Callable[[Any], Any] | None = None,
) -> list[Any]:
    """Map a raw ``QueryResult`` to a typed list according to *returns*.

    ``returns`` dispatch:
    - ``None`` → empty list (fire-and-forget writes)
    - ``int | float | str | bool`` → ``[row[0], ...]``
    - ``dict`` → ``[{col: val, ...}, ...]`` (uses ``result.header`` for keys)
    - Any ``Node`` subclass → decoded entities, each passed through *register_fn*
    """
    if not result.result_set:
        return []

    if returns is None:
        return []

    if returns in _SCALAR_TYPES:
        return [row[0] for row in result.result_set]

    if returns is dict:
        header = _extract_header(result)
        if header:
            return [dict(zip(header, row, strict=False)) for row in result.result_set]
        return [dict(enumerate(row)) for row in result.result_set]

    # Entity class — decode and register in identity map
    entities: list[Any] = []
    for row in result.result_set:
        decoded = mapper.decode_node(row[0], returns)
        if register_fn is not None:
            decoded = register_fn(decoded)
        entities.append(decoded)
    return entities


def _extract_header(result: Any) -> list[str]:
    """Return column name strings from ``result.header``, if present."""
    header = getattr(result, "header", None)
    if not header:
        return []
    names: list[str] = []
    for col in header:
        # FalkorDB header entries are [type_int, name_str]; plain strings also accepted
        if isinstance(col, (list, tuple)) and len(col) >= 2:
            names.append(str(col[1]))
        else:
            names.append(str(col))
    return names
