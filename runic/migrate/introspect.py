from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, cast

from runic.migrate.manifest import (
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


# ---------------------------------------------------------------------------
# Baseline schema snapshot — used by `runic baseline` (Phase 2.5)
# ---------------------------------------------------------------------------


@dataclass
class IndexSpec:
    """Single index entry from a live-graph introspection.

    *properties* is a list of one for RANGE/VECTOR indexes and one or more for
    FULLTEXT indexes (all properties of a multi-property fulltext index on the
    same label are grouped into a single IndexSpec).

    *options* carries the raw FalkorDB options dict (keys: dimension,
    similarityFunction, M, efConstruction, efRuntime) for VECTOR indexes.
    """

    label: str
    properties: list[str]
    index_type: Literal["RANGE", "FULLTEXT", "VECTOR"]
    entity_type: Literal["NODE", "RELATIONSHIP"]
    options: dict[str, Any] | None = None


@dataclass
class ConstraintSpec:
    kind: Literal["UNIQUE", "MANDATORY"]
    label: str
    properties: list[str]
    entity_type: Literal["NODE", "RELATIONSHIP"]


@dataclass
class SchemaSnapshot:
    indexes: list[IndexSpec]
    constraints: list[ConstraintSpec]


@dataclass
class OpCall:
    """A single schema operation call, consumed by the baseline script renderer.

    When *comment* is set the entire call is emitted as a commented-out line
    with the comment as a trailing note (used for VECTOR index stubs).
    """

    method: str
    args: tuple
    kwargs: dict
    comment: str | None = None


# ---------------------------------------------------------------------------
# Live-schema introspection for baseline
# ---------------------------------------------------------------------------


def introspect_graph(graph: Any) -> SchemaSnapshot:
    """Introspect a live FalkorDB graph and return a SchemaSnapshot.

    *graph* must expose ``ro_query(cypher) -> result`` (the raw FalkorDB graph
    object, *not* the runic adapter).

    Column positions are version-dependent — see module-level ``_IDX_*`` and
    ``_CON_*`` constants.  Rows that cannot be parsed are skipped with a
    warning rather than raising.  The ``_FalkorMigrateVersion`` label is
    always excluded.
    """
    indexes: list[IndexSpec] = []
    constraints: list[ConstraintSpec] = []

    try:
        idx_result = graph.ro_query("CALL db.indexes()")
    except Exception as exc:
        if "empty key" in str(exc).lower():
            log.debug("graph does not exist yet (empty key) — returning empty snapshot")
            return SchemaSnapshot(indexes=[], constraints=[])
        raise
    for row in idx_result.result_set:
        try:
            if len(row) < _IDX_MIN_COLS:
                log.warning(
                    "db.indexes() row has %d columns, expected >= %d — skipping",
                    len(row),
                    _IDX_MIN_COLS,
                )
                continue
            label: str = row[_IDX_LABEL]
            if label == _MIGRATION_LABEL:
                continue

            props: list[str] = list(row[_IDX_PROPERTIES])
            types_dict: dict = row[_IDX_TYPES]
            options_dict: dict = row[_IDX_OPTIONS]
            entity_type = cast(Literal["NODE", "RELATIONSHIP"], row[_IDX_ENTITYTYPE])

            range_props: list[str] = []
            fulltext_props: list[str] = []

            for prop in props:
                prop_types: list[str] = types_dict.get(prop, [])
                if not prop_types:
                    continue
                idx_type = prop_types[0]
                if idx_type == "RANGE":
                    range_props.append(prop)
                elif idx_type == "FULLTEXT":
                    fulltext_props.append(prop)
                elif idx_type == "VECTOR":
                    prop_opts: dict = dict(options_dict.get(prop, {}))
                    indexes.append(
                        IndexSpec(
                            label=label,
                            properties=[prop],
                            index_type="VECTOR",
                            entity_type=entity_type,
                            options=prop_opts,
                        )
                    )
                else:
                    log.warning(
                        "unknown index type %r for %s.%s — skipping",
                        idx_type,
                        label,
                        prop,
                    )

            indexes.extend(
                IndexSpec(
                    label=label,
                    properties=[prop],
                    index_type="RANGE",
                    entity_type=entity_type,
                )
                for prop in range_props
            )

            if fulltext_props:
                indexes.append(
                    IndexSpec(
                        label=label,
                        properties=fulltext_props,
                        index_type="FULLTEXT",
                        entity_type=entity_type,
                    )
                )
        except Exception:
            log.warning("failed to parse db.indexes() row — skipping", exc_info=True)

    con_result = graph.ro_query("CALL db.constraints()")
    for row in con_result.result_set:
        try:
            if len(row) < _CON_MIN_COLS:
                log.warning(
                    "db.constraints() row has %d columns, expected >= %d — skipping",
                    len(row),
                    _CON_MIN_COLS,
                )
                continue
            con_type = cast(Literal["UNIQUE", "MANDATORY"], row[_CON_TYPE])
            con_label: str = row[_CON_LABEL]
            if con_label == _MIGRATION_LABEL:
                continue
            con_props: list[str] = list(row[_CON_PROPERTIES])
            con_entity = cast(Literal["NODE", "RELATIONSHIP"], row[_CON_ENTITYTYPE])
            con_status: str = row[_CON_STATUS]

            if con_status != "OPERATIONAL":
                log.debug(
                    "skipping non-OPERATIONAL constraint on %s: %s",
                    con_label,
                    con_status,
                )
                continue

            if con_type not in ("UNIQUE", "MANDATORY"):
                log.warning(
                    "unknown constraint type %r on %s — skipping", con_type, con_label
                )
                continue

            constraints.append(
                ConstraintSpec(
                    kind=con_type,
                    label=con_label,
                    properties=con_props,
                    entity_type=con_entity,
                )
            )
        except Exception:
            log.warning(
                "failed to parse db.constraints() row — skipping", exc_info=True
            )

    log.debug(
        "schema snapshot: %d indexes, %d constraints",
        len(indexes),
        len(constraints),
    )
    return SchemaSnapshot(indexes=indexes, constraints=constraints)


def full_upgrade_ops(snapshot: SchemaSnapshot) -> list[OpCall]:
    """Return op calls to recreate the snapshot schema: indexes first, then constraints."""
    ops: list[OpCall] = []

    for spec in snapshot.indexes:
        if spec.index_type == "RANGE":
            for prop in spec.properties:
                kwargs: dict[str, Any] = (
                    {"rel": True} if spec.entity_type == "RELATIONSHIP" else {}
                )
                ops.append(
                    OpCall(
                        method="create_range_index",
                        args=(spec.label, prop),
                        kwargs=kwargs,
                    )
                )
        elif spec.index_type == "FULLTEXT":
            ops.append(
                OpCall(
                    method="create_fulltext_index",
                    args=(spec.label, *spec.properties),
                    kwargs={},
                )
            )
        elif spec.index_type == "VECTOR":
            prop = spec.properties[0]
            opts = spec.options or {}
            ops.append(
                OpCall(
                    method="create_vector_index",
                    args=(spec.label, prop),
                    kwargs={
                        "dimension": opts.get("dimension", 0),
                        "similarity": opts.get("similarityFunction", "cosine"),
                    },
                    comment="verify options manually",
                )
            )

    ops.extend(
        OpCall(
            method="create_constraint",
            args=(spec.kind, spec.entity_type, spec.label, spec.properties),
            kwargs={},
        )
        for spec in snapshot.constraints
    )

    return ops


def full_downgrade_ops(snapshot: SchemaSnapshot) -> list[OpCall]:
    """Return op calls to tear down the snapshot schema: constraints dropped before indexes.

    Constraints must be dropped before their backing range indexes to avoid
    "cannot drop index that supports a constraint" errors.
    """
    ops: list[OpCall] = []

    ops.extend(
        OpCall(
            method="drop_constraint",
            args=(spec.kind, spec.entity_type, spec.label, spec.properties),
            kwargs={},
        )
        for spec in reversed(snapshot.constraints)
    )

    for spec in reversed(snapshot.indexes):
        if spec.index_type == "RANGE":
            for prop in reversed(spec.properties):
                kwargs: dict[str, Any] = (
                    {"rel": True} if spec.entity_type == "RELATIONSHIP" else {}
                )
                ops.append(
                    OpCall(
                        method="drop_range_index",
                        args=(spec.label, prop),
                        kwargs=kwargs,
                    )
                )
        elif spec.index_type == "FULLTEXT":
            ops.append(
                OpCall(
                    method="drop_fulltext_index",
                    args=(spec.label, *spec.properties),
                    kwargs={},
                )
            )
        elif spec.index_type == "VECTOR":
            prop = spec.properties[0]
            ops.append(
                OpCall(
                    method="drop_vector_index",
                    args=(spec.label, prop),
                    kwargs={},
                    comment="verify before enabling",
                )
            )

    return ops


def render_manifest_code(snapshot: SchemaSnapshot) -> str:
    """Render a SchemaSnapshot as a ready-to-paste ``target_manifest`` Python block.

    The output is valid Python that can be pasted directly into ``env.py`` and
    passed to ``context.configure(..., target_manifest=target_manifest)`` to
    enable ``runic revision --autogenerate``.
    """
    needed: list[str] = []
    if any(i.index_type == "RANGE" for i in snapshot.indexes):
        needed.append("RangeIndex")
    if any(i.index_type == "FULLTEXT" for i in snapshot.indexes):
        needed.append("FulltextIndex")
    if any(i.index_type == "VECTOR" for i in snapshot.indexes):
        needed.append("VectorIndex")
    if any(c.kind == "UNIQUE" for c in snapshot.constraints):
        needed.append("UniqueConstraint")
    if any(c.kind == "MANDATORY" for c in snapshot.constraints):
        needed.append("MandatoryConstraint")
    needed.append("SchemaManifest")

    lines: list[str] = [
        f"from runic.migrate.manifest import {', '.join(needed)}",
        "",
        "target_manifest = SchemaManifest(",
    ]

    range_specs = [i for i in snapshot.indexes if i.index_type == "RANGE"]
    if range_specs:
        range_lines = [
            f"        RangeIndex(label={spec.label!r}, prop={prop!r}"
            + (", rel=True" if spec.entity_type == "RELATIONSHIP" else "")
            + "),"
            for spec in range_specs
            for prop in spec.properties
        ]
        lines += ["    range_indexes=[", *range_lines, "    ],"]
    else:
        lines.append("    range_indexes=[],")

    ft_specs = [i for i in snapshot.indexes if i.index_type == "FULLTEXT"]
    if ft_specs:
        ft_lines = [
            f"        FulltextIndex(label={spec.label!r}, props={list(spec.properties)!r}),"
            for spec in ft_specs
        ]
        lines += ["    fulltext_indexes=[", *ft_lines, "    ],"]
    else:
        lines.append("    fulltext_indexes=[],")

    vec_specs = [i for i in snapshot.indexes if i.index_type == "VECTOR"]
    if vec_specs:
        vec_lines = [
            "        VectorIndex("
            f"label={spec.label!r}, prop={spec.properties[0]!r}, "
            f"dimension={(spec.options or {}).get('dimension', 0)}, "
            f"similarity={(spec.options or {}).get('similarityFunction', 'cosine')!r}),"
            for spec in vec_specs
        ]
        lines += ["    vector_indexes=[", *vec_lines, "    ],"]
    else:
        lines.append("    vector_indexes=[],")

    if snapshot.constraints:
        con_lines = [
            f"        {'UniqueConstraint' if spec.kind == 'UNIQUE' else 'MandatoryConstraint'}"
            f"(entity={spec.entity_type!r}, label={spec.label!r}, props={spec.properties!r}),"
            for spec in snapshot.constraints
        ]
        lines += ["    constraints=[", *con_lines, "    ],"]
    else:
        lines.append("    constraints=[],")

    lines.append(")")
    return "\n".join(lines)


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

        fulltext_props: list[str] = []
        for prop in props:
            prop_types: list[str] = types_dict.get(prop, [])
            if not prop_types:
                continue
            idx_type = prop_types[0]
            if idx_type == "RANGE":
                range_indexes.append(RangeIndex(label=label, prop=prop, rel=rel))
            elif idx_type == "FULLTEXT":
                # Accumulate all fulltext props of this label into a single
                # multi-property index so it matches the grouped manifest spec
                # (one FulltextIndex per label, not one per property).
                fulltext_props.append(prop)
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

        if fulltext_props:
            sw = tuple(stopwords) if stopwords else None
            lang = language if language and language != "english" else None
            fulltext_indexes.append(
                FulltextIndex(
                    label=label, props=fulltext_props, language=lang, stopwords=sw
                )
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
