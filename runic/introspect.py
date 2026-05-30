from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from runic.manifest import (
    FulltextIndex,
    MandatoryConstraint,
    RangeIndex,
    UniqueConstraint,
    VectorIndex,
)

log = logging.getLogger(__name__)

# Expected column positions for CALL db.indexes() result rows.
# Verified against falkordblite 0.10.0 (redislite):
#   [0] label (str)
#   [1] properties (list[str])
#   [2] types (dict: prop -> list[str], e.g. {'email': ['RANGE']})
#   [3] options (dict: prop -> dict)
#   [4] language (str)
#   [5] stopwords (list[str])
#   [6] entitytype (str: 'NODE' | 'RELATIONSHIP')
#   [7] status (str: 'OPERATIONAL' | ...)
_IDX_LABEL = 0
_IDX_PROPERTIES = 1
_IDX_TYPES = 2
_IDX_OPTIONS = 3
_IDX_LANGUAGE = 4
_IDX_STOPWORDS = 5
_IDX_ENTITYTYPE = 6
_IDX_STATUS = 7
_IDX_MIN_COLS = 8

# Expected column positions for CALL db.constraints() result rows:
#   [0] type (str: 'UNIQUE' | 'MANDATORY')
#   [1] label (str)
#   [2] properties (list[str])
#   [3] entitytype (str)
#   [4] status (str)
_CON_TYPE = 0
_CON_LABEL = 1
_CON_PROPERTIES = 2
_CON_ENTITYTYPE = 3
_CON_STATUS = 4
_CON_MIN_COLS = 5

_MIGRATION_LABEL = "_FalkorMigrateVersion"


@dataclass
class LiveSchema:
    range_indexes: list[RangeIndex]
    fulltext_indexes: list[FulltextIndex]
    vector_indexes: list[VectorIndex]
    constraints: list[UniqueConstraint | MandatoryConstraint]


def read_live_schema(graph: Any) -> LiveSchema:
    range_indexes: list[RangeIndex] = []
    fulltext_indexes: list[FulltextIndex] = []
    vector_indexes: list[VectorIndex] = []
    constraints: list[UniqueConstraint | MandatoryConstraint] = []

    idx_result = graph.ro_query("CALL db.indexes()")
    for row in idx_result.result_set:
        if len(row) < _IDX_MIN_COLS:
            raise AssertionError(
                f"db.indexes() row has {len(row)} columns, expected >= {_IDX_MIN_COLS}. "
                "FalkorDB version may have changed the schema."
            )
        label: str = row[_IDX_LABEL]
        if label == _MIGRATION_LABEL:
            continue

        props: list[str] = list(row[_IDX_PROPERTIES])
        types_dict: dict = row[_IDX_TYPES]
        options_dict: dict = row[_IDX_OPTIONS]
        language: str = row[_IDX_LANGUAGE]
        stopwords: list[str] = list(row[_IDX_STOPWORDS])
        entity_type: str = row[_IDX_ENTITYTYPE]
        rel = entity_type == "RELATIONSHIP"

        for prop in props:
            prop_types: list[str] = types_dict.get(prop, [])
            if not prop_types:
                continue
            idx_type = prop_types[0]
            if idx_type == "RANGE":
                range_indexes.append(RangeIndex(label=label, prop=prop, rel=rel))
            elif idx_type == "FULLTEXT":
                sw = tuple(stopwords) if stopwords else None
                lang = language if language and language != "english" else None
                fulltext_indexes.append(
                    FulltextIndex(
                        label=label, props=[prop], language=lang, stopwords=sw
                    )
                )
            elif idx_type == "VECTOR":
                prop_opts: dict = options_dict.get(prop, {})
                dimension: int = int(prop_opts.get("dimension", 0))
                similarity: str = str(prop_opts.get("similarityFunction", "cosine"))
                m: int = int(prop_opts.get("M", 16))
                ef_construction: int = int(prop_opts.get("efConstruction", 200))
                ef_runtime: int = int(prop_opts.get("efRuntime", 10))
                vector_indexes.append(
                    VectorIndex(
                        label=label,
                        prop=prop,
                        dimension=dimension,
                        similarity=similarity,
                        m=m,
                        ef_construction=ef_construction,
                        ef_runtime=ef_runtime,
                    )
                )
            else:
                log.warning(
                    "unknown index type %r for %s.%s — skipping", idx_type, label, prop
                )

    con_result = graph.ro_query("CALL db.constraints()")
    for row in con_result.result_set:
        if len(row) < _CON_MIN_COLS:
            raise AssertionError(
                f"db.constraints() row has {len(row)} columns, expected >= {_CON_MIN_COLS}. "
                "FalkorDB version may have changed the schema."
            )
        con_type: str = row[_CON_TYPE]
        con_label: str = row[_CON_LABEL]
        if con_label == _MIGRATION_LABEL:
            continue
        con_props: tuple[str, ...] = tuple(row[_CON_PROPERTIES])
        con_entity: str = row[_CON_ENTITYTYPE]
        con_status: str = row[_CON_STATUS]

        if con_status != "OPERATIONAL":
            log.debug(
                "skipping non-OPERATIONAL constraint on %s: %s", con_label, con_status
            )
            continue

        if con_type == "UNIQUE":
            constraints.append(
                UniqueConstraint(
                    entity=con_entity, label=con_label, props=list(con_props)
                )
            )
        elif con_type == "MANDATORY":
            constraints.append(
                MandatoryConstraint(
                    entity=con_entity, label=con_label, props=list(con_props)
                )
            )
        else:
            log.warning(
                "unknown constraint type %r on %s — skipping", con_type, con_label
            )

    log.debug(
        "live schema: %d range, %d fulltext, %d vector indexes, %d constraints",
        len(range_indexes),
        len(fulltext_indexes),
        len(vector_indexes),
        len(constraints),
    )
    return LiveSchema(
        range_indexes=range_indexes,
        fulltext_indexes=fulltext_indexes,
        vector_indexes=vector_indexes,
        constraints=constraints,
    )
