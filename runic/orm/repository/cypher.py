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
    if not result.rows:
        return []

    if returns is None:
        return []

    if returns in _SCALAR_TYPES:
        return [row[0] for row in result.rows]

    if returns is dict:
        columns = result.columns
        if columns:
            return [dict(zip(columns, row, strict=False)) for row in result.rows]
        return [dict(enumerate(row)) for row in result.rows]

    # Entity class — decode and register in identity map
    entities: list[Any] = []
    for row in result.rows:
        decoded = mapper.decode_node(row[0], returns)
        if register_fn is not None:
            decoded = register_fn(decoded)
        entities.append(decoded)
    return entities
