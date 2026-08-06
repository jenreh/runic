"""GraphStore — the single place backend Cypher dialect lives (concept §9.1).

This module wraps a :class:`runic.ogm.Session` (built from a driver) and isolates
every backend-specific detail: vector/fulltext procedure strings, the vector
write literal (``vecf32`` on FalkorDB, raw list elsewhere), vector-index
dimension handling, and cosine score normalisation.

It supports all five runic backends. FalkorDB and Neo4j use native vector +
fulltext procedures; Memgraph, ArcadeDB and Apache AGE use a portable
pure-Python brute-force path (standard-Cypher MATCH + cosine/token scoring) that
works everywhere. Backend selection is table-driven (a small dialect map) rather
than ``if/elif`` sprawl, and bootstrap tolerates backends whose engines reject or
do not support index DDL (the brute-force read paths cover them).

The public surface conforms exactly to the :class:`runic.rag.ports.GraphStore`
and :class:`runic.rag.ports.Writer` protocols.
"""

from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from runic.ogm import Session
from runic.ogm.schema import extract_declared_specs
from runic.rag.domain import ChunkHit, EntityHit, RelationHit, ScoredKey
from runic.rag.ontology import Ontology

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from runic.rag.config import RagSettings

log = logging.getLogger(__name__)

__all__ = ["GraphStore"]


# ── Dialect strategy ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Dialect:
    """Backend-specific procedure templates, score normalisation, and writes.

    ``vector_proc`` / ``fulltext_proc`` are *callables* returning a Cypher
    string given the validated, whitelisted literals; the query vector / text is
    always bound as a ``$param`` to keep user input out of the query string.
    Either may be ``None``, in which case the store uses a portable pure-Python
    brute-force path instead (works on every backend). ``normalize`` maps a raw
    proc score into a similarity in ``[0, 1]``. ``vector_write`` returns the
    Cypher expression for *storing* a vector parameter (FalkorDB needs
    ``vecf32(...)``; every other backend stores the raw list).
    """

    vector_proc: Any
    fulltext_proc: Any
    normalize: Any
    native_vector: bool
    vector_write: Any


def _clamp01(score: Any) -> float:
    """Clamp a raw score into ``[0, 1]``."""
    return max(0.0, min(1.0, float(score)))


def _falkordb_normalize(score: Any) -> float:
    """FalkorDB returns cosine DISTANCE → similarity = (2 - distance) / 2."""
    return max(0.0, min(1.0, (2.0 - float(score)) / 2.0))


def _falkordb_vector_proc(label: str, prop: str, k: int) -> str:
    return (
        f"CALL db.idx.vector.queryNodes('{label}', '{prop}', {k}, vecf32($q)) "
        "YIELD node, score"
    )


def _falkordb_fulltext_proc(label: str) -> str:
    return f"CALL db.idx.fulltext.queryNodes('{label}', $q) YIELD node, score"


def _neo4j_vector_proc(label: str, prop: str, k: int) -> str:  # noqa: ARG001
    # Neo4j convention: a named index "{label}_{prop}"; k is a $param.
    return (
        f"CALL db.index.vector.queryNodes('{label}_{prop}', $k, $q) YIELD node, score"
    )


def _neo4j_fulltext_proc(label: str) -> str:
    return f"CALL db.index.fulltext.queryNodes('{label}', $q) YIELD node, score"


# Brute-force backends (Memgraph/ArcadeDB/AGE): no native proc — the store uses
# standard-Cypher MATCH + Python cosine/token scoring, which works everywhere.
# Vectors are stored as raw lists (only FalkorDB wraps them in vecf32()).
_BRUTE_FORCE = _Dialect(
    vector_proc=None,
    fulltext_proc=None,
    normalize=_clamp01,
    native_vector=False,
    vector_write=lambda param: param,
)

_DIALECTS: dict[str, _Dialect] = {
    "falkordb": _Dialect(
        vector_proc=_falkordb_vector_proc,
        fulltext_proc=_falkordb_fulltext_proc,
        normalize=_falkordb_normalize,
        native_vector=True,
        vector_write=lambda param: f"vecf32({param})",
    ),
    # Neo4j: score is already cosine SIMILARITY in [0, 1]; raw-list vector write.
    "neo4j": _Dialect(
        vector_proc=_neo4j_vector_proc,
        fulltext_proc=_neo4j_fulltext_proc,
        normalize=_clamp01,
        native_vector=True,
        vector_write=lambda param: param,
    ),
    # Memgraph, ArcadeDB and Apache AGE use the portable brute-force path; their
    # native vector/fulltext procs differ per engine and are a future optimisation.
    "memgraph": _BRUTE_FORCE,
    "arcadedb": _BRUTE_FORCE,
    "age": _BRUTE_FORCE,
}


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Return cosine similarity of two equal-length vectors, mapped to [0, 1]."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    sim = dot / (norm_a * norm_b)
    return max(0.0, min(1.0, (sim + 1.0) / 2.0))


def _node_props(raw: Any) -> dict[str, Any]:
    """Best-effort extraction of a node's property dict from a raw proc result."""
    props = getattr(raw, "properties", None)
    if isinstance(props, dict):
        return props
    if isinstance(raw, dict):
        return raw
    return {}


# Markers that mean "this is a hard error, NOT a missing index" — never degrade.
_HARD_ERROR_MARKERS = (
    "dimension mismatch",
    "connection",
    "timeout",
    "refused",
    "unreachable",
    "syntax",
)


def _is_index_missing(exc: Exception) -> bool:
    """True when *exc* signals an absent vector/fulltext index (safe to degrade).

    Conservative: a known hard error (dimension mismatch, connection failure,
    syntax error) is never treated as a missing index; only index-related
    failures degrade to the brute-force / empty path. Everything else re-raises.
    """
    text = str(exc).lower()
    if any(marker in text for marker in _HARD_ERROR_MARKERS):
        return False
    return "index" in text


def _parse_bolt_uri(uri: str) -> tuple[str, int]:
    """Parse ``bolt://host:port`` into ``(host, port)`` (default localhost:7687)."""
    rest = uri.split("://", 1)[-1]
    host = rest.split(":", 1)[0].split("/", 1)[0] or "localhost"
    port = 7687
    if ":" in rest:
        tail = rest.split(":", 1)[1].split("/", 1)[0]
        try:
            port = int(tail)
        except ValueError:
            port = 7687
    return host, port


# ── Writer (unit of work) ─────────────────────────────────────────────────────


class _Writer:
    """One graph unit-of-work backed by a single OGM session (ADR-005).

    ``vector_expr`` is the backend-specific Cypher for storing a ``$vec``
    parameter — ``vecf32($vec)`` on FalkorDB, plain ``$vec`` everywhere else.
    """

    def __init__(self, session: Session, vector_expr: str) -> None:
        self._session = session
        self._vector_expr = vector_expr

    def add_chunk(self, chunk_node: Any) -> None:
        """MERGE a Chunk node by its id, updating mutable properties."""
        embedding = chunk_node.embedding
        vec = list(embedding) if embedding is not None else None
        self._session.execute(
            "MERGE (c:Chunk {id: $id}) "
            "SET c.text = $text, c.source = $source, c.seq = $seq, "
            f"c.embedding = CASE WHEN $vec IS NULL THEN c.embedding "
            f"ELSE {self._vector_expr} END",
            {
                "id": chunk_node.id,
                "text": chunk_node.text,
                "source": chunk_node.source,
                "seq": chunk_node.seq,
                "vec": vec,
            },
        )

    def upsert_entity(
        self,
        key: str,
        name: str,
        type: str,  # noqa: A002 - mirrors domain vocabulary
        description: str,
        embedding: list[float] | None,
    ) -> None:
        """MERGE an entity by canonical_key (get-or-create + field update)."""
        self._session.execute(
            "MERGE (e:Entity {canonical_key: $key}) "
            "SET e.name = $name, e.type = $type, e.description = $description, "
            f"e.embedding = CASE WHEN $vec IS NULL THEN e.embedding "
            f"ELSE {self._vector_expr} END",
            {
                "key": key,
                "name": name,
                "type": type,
                "description": description,
                "vec": list(embedding) if embedding is not None else None,
            },
        )

    def relate(
        self,
        src_key: str,
        rel_type: str,
        dst_key: str,
        description: str,
        confidence: float,
        *,
        source_chunk: str,
    ) -> None:
        """MERGE an idempotent RELATES_TO edge carrying relation metadata."""
        self._session.execute(
            "MATCH (s:Entity {canonical_key: $src}), (d:Entity {canonical_key: $dst}) "
            "MERGE (s)-[r:RELATES_TO {rel_type: $rel_type}]->(d) "
            "SET r.description = $description, r.confidence = $confidence, "
            "r.source_chunk = $source_chunk",
            {
                "src": src_key,
                "dst": dst_key,
                "rel_type": rel_type,
                "description": description,
                "confidence": confidence,
                "source_chunk": source_chunk,
            },
        )

    def mention(self, chunk_id: str, entity_key: str) -> None:
        """MERGE an idempotent Chunk-[:MENTIONS]->Entity edge."""
        self._session.execute(
            "MATCH (c:Chunk {id: $cid}), (e:Entity {canonical_key: $ekey}) "
            "MERGE (c)-[:MENTIONS]->(e)",
            {"cid": chunk_id, "ekey": entity_key},
        )


# ── GraphStore ─────────────────────────────────────────────────────────────────


class GraphStore:
    """Backend-isolating graph adapter wrapping a :class:`runic.ogm.Session`.

    Parameters
    ----------
    driver:
        An OGM driver (e.g. from :func:`runic.ogm.driver.factory.create_driver`).
    settings:
        Runtime configuration; ``backend`` selects the dialect and
        ``embedding_dim`` is the REAL vector-index dimension (never 0).
    schema_models:
        OGM model classes to bootstrap. Defaults to the generic ontology models.
    """

    def __init__(
        self,
        driver: Any,
        settings: RagSettings,
        schema_models: list[type] | None = None,
        *,
        adapter: Any = None,
    ) -> None:
        self._driver = driver
        self._settings = settings
        self._models: list[type] = schema_models or Ontology.default().schema_models()
        self._dialect: _Dialect | None = _DIALECTS.get(settings.backend)
        # An optional pre-built migrate adapter (constructor injection / DIP).
        # When omitted, one is derived from the driver/settings per backend.
        self._adapter: Any = adapter

    # ── Schema bootstrap ──────────────────────────────────────────────────────

    def bootstrap_schema(self) -> None:
        """Ensure entity types, then create indexes idempotently (FACTS 2/5).

        VECTOR indexes are created with the REAL ``settings.embedding_dim`` (never
        the placeholder 0 that ``SchemaManager.sync_schema`` would use). Already
        existing indexes/constraints are tolerated.
        """
        adapter = self._build_adapter()
        if adapter is None:
            # A silent no-op here would leave every vector/fulltext query to
            # degrade invisibly; fail loudly so the misconfiguration is seen.
            from runic.rag.exceptions import ConfigError

            msg = (
                f"Cannot bootstrap schema: no migrate adapter for backend "
                f"{self._settings.backend!r}. For FalkorDB the driver must expose "
                f"falkordb_connection(); for Neo4j/Memgraph/ArcadeDB/AGE the "
                f"connection settings must be configured (or pass adapter=)."
            )
            raise ConfigError(msg)

        from runic.migrate import SchemaManager

        # Vertex/edge types are created implicitly by the MERGE writes, so this
        # pre-creation is best-effort: some backends reject or don't support the
        # DDL via Bolt (ArcadeDB ``CREATE VERTEX TYPE``) or at all (AGE). Log and
        # continue — the writes still create the labels on demand.
        try:
            SchemaManager(adapter).ensure_entity_types(self._models)
        except Exception as exc:  # noqa: BLE001 - types created on write; non-fatal
            log.info(
                "ensure_entity_types skipped for %s (types created on write): %s",
                self._settings.backend,
                exc,
            )

        dim = self._settings.embedding_dim
        if dim <= 0:
            msg = "embedding_dim must be > 0 for vector indexes"
            raise ValueError(msg)

        # Subtypes share the "Entity" label, so dedupe specs across all models
        # to avoid re-creating identical indexes (and duplicate fulltext props).
        all_specs = set()
        for model in self._models:
            all_specs |= extract_declared_specs(model)

        fulltext_by_label: dict[str, list[str]] = {}
        for spec in all_specs:
            self._apply_spec(adapter, spec, dim, fulltext_by_label)

        for label, props in fulltext_by_label.items():
            self._ignore_exists(
                lambda lbl=label, p=props: adapter.create_fulltext_index(lbl, *p)
            )

    def _apply_spec(
        self,
        adapter: Any,
        spec: Any,
        dim: int,
        fulltext_by_label: dict[str, list[str]],
    ) -> None:
        """Route one IndexSpec to the matching adapter DDL call (idempotent).

        VECTOR/FULLTEXT indexes are created only for backends whose dialect uses
        the native proc; brute-force backends need no such index.
        """
        native_vector = self._dialect is not None and self._dialect.native_vector
        native_fulltext = (
            self._dialect is not None and self._dialect.fulltext_proc is not None
        )
        if spec.index_type == "VECTOR":
            if native_vector:
                self._ignore_exists(
                    lambda: adapter.create_vector_index(
                        spec.label, spec.property, dim, "cosine"
                    )
                )
        elif spec.index_type == "FULLTEXT":
            if native_fulltext:
                props = fulltext_by_label.setdefault(spec.label, [])
                if spec.property not in props:
                    props.append(spec.property)
        elif spec.index_type == "RANGE":
            self._best_effort(
                lambda: adapter.create_range_index(spec.label, spec.property),
                "range index",
            )
        elif spec.index_type == "UNIQUE":
            self._best_effort(
                lambda: adapter.create_constraint(
                    "UNIQUE", "NODE", spec.label, [spec.property]
                ),
                "unique constraint",
            )

    @staticmethod
    def _best_effort(action: Any, what: str) -> None:
        """Run an OPTIONAL schema action; log and continue on any failure.

        Range indexes and unique constraints are query-time optimisations (PK
        uniqueness is also enforced by the MERGE writes), so a backend that
        rejects or cannot express the DDL (ArcadeDB/AGE over Bolt) must not fail
        bootstrap — every read/write path works without them.
        """
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - optional optimisation; non-fatal
            text = str(exc).lower()
            if "already" in text or "duplicate" in text or "equivalent" in text:
                log.debug("%s already present: %s", what, exc)
            else:
                log.info("Skipped optional %s (backend rejected DDL): %s", what, exc)

    @staticmethod
    def _ignore_exists(action: Any) -> None:
        """Run *action*, tolerating idempotency and unsupported-DDL errors.

        Swallows 'already exists' style idempotency errors and
        ``NotImplementedError`` — a backend that lacks this Cypher-level DDL
        (e.g. AGE has no index/constraint DDL); the portable read paths cover it.
        """
        try:
            action()
        except NotImplementedError as exc:
            log.info(
                "Backend lacks this DDL; relying on the portable fallback: %s", exc
            )
        except Exception as exc:  # noqa: BLE001 - normalise idempotency
            text = str(exc).lower()
            # Match positive "already present" signals only — NOT a bare "exist",
            # which also appears in "does not exist" (a genuine failure).
            if "already" in text or "duplicate" in text or "equivalent" in text:
                log.debug("Index/constraint already present: %s", exc)
                return
            raise

    def _build_adapter(self) -> Any | None:
        """Build a migrate adapter for the configured backend (all five)."""
        if self._adapter is not None:
            return self._adapter

        from runic.migrate.adapters import create_adapter

        s = self._settings
        backend = s.backend
        if backend == "falkordb":
            from runic.migrate.adapters.falkordb import FalkorDBAdapter

            conn = getattr(self._driver, "falkordb_connection", None)
            if callable(conn):
                db, graph = conn()
                return FalkorDBAdapter(db, graph)
            return None
        if backend == "neo4j":
            host, port = _parse_bolt_uri(s.neo4j_uri or "bolt://localhost")
            return create_adapter(
                "neo4j",
                host=host,
                port=port,
                database=s.neo4j_database,
                username=s.neo4j_username or "neo4j",
                password=s.neo4j_password or "",
            )
        if backend == "memgraph":
            host, port = _parse_bolt_uri(s.memgraph_uri or "bolt://localhost:7687")
            return create_adapter(
                "memgraph",
                host=host,
                port=port,
                database=s.memgraph_database,
                username=s.memgraph_username or "",
                password=s.memgraph_password or "",
            )
        if backend == "arcadedb":
            return create_adapter(
                "arcadedb",
                host=s.arcadedb_host,
                port=s.arcadedb_port,
                database=s.arcadedb_database,
                username=s.arcadedb_username,
                password=s.arcadedb_password or "",
            )
        if backend == "age":
            return create_adapter(
                "age",
                host=s.age_host,
                port=s.age_port,
                database=s.age_database,
                graph=s.age_graph,
                username=s.age_username,
                password=s.age_password or "",
            )
        return None

    # ── Writer ────────────────────────────────────────────────────────────────

    @contextmanager
    def writer(self) -> Iterator[_Writer]:
        """Open ONE session as a unit of work; commit on clean exit."""
        expr = (
            self._dialect.vector_write("$vec") if self._dialect is not None else "$vec"
        )
        with Session(self._driver) as session:
            yield _Writer(session, expr)
            session.commit()

    # ── Vector search ───────────────────────────────────────────────────────────

    def vector_search(
        self,
        *,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None = None,
    ) -> list[ScoredKey]:
        """KNN search returning canonical keys with normalized similarity [0, 1].

        Uses the raw backend proc (FACT 3); falls back to brute-force Python
        cosine (FACT 6) when the backend lacks a vector index or the proc errors.
        """
        if self._dialect is None or not self._dialect.native_vector:
            return self._brute_force(label, prop, query_vec, k, type_filter)
        try:
            return self._proc_vector_search(label, prop, query_vec, k, type_filter)
        except Exception as exc:  # noqa: BLE001 - classify before degrading
            if _is_index_missing(exc):
                log.warning(
                    "Vector index for %s.%s missing; brute-force fallback "
                    "(did you call bootstrap_schema?): %s",
                    label,
                    prop,
                    exc,
                )
                return self._brute_force(label, prop, query_vec, k, type_filter)
            log.exception(
                "Vector search failed for %s.%s (not a missing-index error)",
                label,
                prop,
            )
            raise

    def _proc_vector_search(
        self,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None,
    ) -> list[ScoredKey]:
        dialect = self._dialect
        assert dialect is not None  # narrowed by caller  # noqa: S101
        # Over-fetch so a type filter still yields k results after WHERE pruning.
        fetch_k = k * 4 if type_filter else k
        proc = dialect.vector_proc(label, prop, fetch_k)
        cypher = proc
        where = ""
        if type_filter:
            where = " WHERE node.type = $type_filter OR $type_filter IN labels(node)"
        cypher = (
            f"{proc}{where} "
            "RETURN node.canonical_key AS key, node.id AS cid, score AS score "
            f"LIMIT {fetch_k}"
        )
        params: dict[str, Any] = {"q": list(query_vec)}
        if "$k" in proc:
            params["k"] = fetch_k
        if type_filter:
            params["type_filter"] = type_filter

        result = self._driver.execute(cypher, params)
        scored: list[ScoredKey] = []
        for row in result.rows:
            key = row[0] if row[0] is not None else row[1]
            if key is None:
                continue
            scored.append(ScoredKey(key=str(key), score=dialect.normalize(row[2])))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    def _brute_force(
        self,
        label: str,
        prop: str,
        query_vec: list[float],
        k: int,
        type_filter: str | None,
    ) -> list[ScoredKey]:
        """Pure-Python cosine over all (key, embedding) rows for the label."""
        key_prop = "canonical_key" if label == "Entity" else "id"
        where = ""
        params: dict[str, Any] = {}
        if type_filter:
            where = "WHERE n.type = $type_filter OR $type_filter IN labels(n) "
            params["type_filter"] = type_filter
        cypher = f"MATCH (n:{label}) {where}RETURN n.{key_prop} AS key, n.{prop} AS emb"
        result = self._driver.execute(cypher, params)
        scored: list[ScoredKey] = []
        for row in result.rows:
            key, emb = row[0], row[1]
            if key is None or emb is None:
                continue
            scored.append(ScoredKey(key=str(key), score=_cosine(query_vec, list(emb))))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    # ── Fulltext search ──────────────────────────────────────────────────────────

    def fulltext_search(
        self,
        *,
        label: str,
        prop: str,
        query: str,
        k: int,
    ) -> list[ScoredKey]:
        """Fulltext search via the native proc (FACT 4), or a portable fallback.

        Backends without a native fulltext proc (Memgraph/ArcadeDB/AGE) fall back
        to a pure-Python token-overlap scan so retrieval still works everywhere.
        """
        if self._dialect is None or self._dialect.fulltext_proc is None:
            return self._brute_force_fulltext(label, prop, query, k)
        key_prop = "canonical_key" if label == "Entity" else "id"
        proc = self._dialect.fulltext_proc(label)
        cypher = f"{proc} RETURN node.{key_prop} AS key, score AS score LIMIT {int(k)}"
        try:
            result = self._driver.execute(cypher, {"q": query})
        except Exception as exc:  # noqa: BLE001 - classify before returning empty
            if _is_index_missing(exc):
                log.warning(
                    "Fulltext index for %s missing; returning no hits "
                    "(did you call bootstrap_schema?): %s",
                    label,
                    exc,
                )
                return []
            log.exception(
                "Fulltext search failed for %s (not a missing-index error)",
                label,
            )
            raise
        hits: list[ScoredKey] = []
        for row in result.rows:
            if row[0] is None:
                continue
            hits.append(ScoredKey(key=str(row[0]), score=float(row[1])))
        return hits

    def _brute_force_fulltext(
        self, label: str, prop: str, query: str, k: int
    ) -> list[ScoredKey]:
        """Portable token-overlap fulltext: fetch candidates, score in Python.

        For ``Entity`` it matches the query terms against ``name`` + ``description``;
        for any other label it matches the single *prop* field. Used on backends
        with no native fulltext index (Memgraph/ArcadeDB/AGE).
        """
        terms = [t for t in query.lower().split() if t]
        if not terms:
            return []
        key_prop = "canonical_key" if label == "Entity" else "id"
        if label == "Entity":
            cypher = (
                f"MATCH (n:{label}) "
                f"RETURN n.{key_prop} AS key, n.name AS a, n.description AS b"
            )
        else:
            cypher = (
                f"MATCH (n:{label}) RETURN n.{key_prop} AS key, n.{prop} AS a, '' AS b"
            )
        result = self._driver.execute(cypher, {})
        scored: list[ScoredKey] = []
        for row in result.rows:
            if row[0] is None:
                continue
            text = f"{row[1] or ''} {row[2] or ''}".lower()
            score = float(sum(text.count(term) for term in terms))
            if score > 0:
                scored.append(ScoredKey(key=str(row[0]), score=score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:k]

    # ── Hydration / traversal ─────────────────────────────────────────────────────

    def get_entities(self, keys: list[str]) -> list[EntityHit]:
        """Hydrate entities for the given canonical keys (score defaults to 1.0)."""
        if not keys:
            return []
        result = self._driver.execute(
            "MATCH (e:Entity) WHERE e.canonical_key IN $keys "
            "RETURN e.canonical_key, e.name, e.type, e.description",
            {"keys": keys},
        )
        return [
            EntityHit(
                canonical_key=str(row[0]),
                name=str(row[1] or ""),
                type=str(row[2] or ""),
                description=str(row[3] or ""),
                score=1.0,
            )
            for row in result.rows
            if row[0] is not None
        ]

    def expand(
        self, keys: list[str], *, max_hops: int
    ) -> tuple[list[EntityHit], list[RelationHit]]:
        """Bounded multi-hop traversal (ADR-018: one traversal query, no N+1)."""
        if not keys or max_hops < 1:
            return self.get_entities(keys), []
        hops = max(1, int(max_hops))
        result = self._driver.execute(
            f"MATCH (s:Entity) WHERE s.canonical_key IN $keys "
            f"MATCH path = (s)-[:RELATES_TO*1..{hops}]->(t:Entity) "
            "WITH relationships(path) AS rels "
            "UNWIND rels AS r "
            "WITH DISTINCT startNode(r) AS sn, endNode(r) AS en, r "
            # Explicit AS aliases: AGE maps RETURN items to SQL columns by name,
            # so unaliased sn.canonical_key + en.canonical_key would collide.
            "RETURN sn.canonical_key AS sk, sn.name AS sname, sn.type AS stype, "
            "sn.description AS sdesc, en.canonical_key AS ek, en.name AS ename, "
            "en.type AS etype, en.description AS edesc, "
            "r.rel_type AS rtype, r.description AS rdesc",
            {"keys": keys},
        )
        entities: dict[str, EntityHit] = {}
        for hit in self.get_entities(keys):
            entities[hit.canonical_key] = hit
        relations: list[RelationHit] = []
        for row in result.rows:
            self._collect_hit(entities, row[0], row[1], row[2], row[3])
            self._collect_hit(entities, row[4], row[5], row[6], row[7])
            if row[0] is not None and row[4] is not None:
                relations.append(
                    RelationHit(
                        source_key=str(row[0]),
                        target_key=str(row[4]),
                        rel_type=str(row[8] or ""),
                        description=str(row[9] or ""),
                    )
                )
        return list(entities.values()), relations

    @staticmethod
    def _collect_hit(
        sink: dict[str, EntityHit],
        key: Any,
        name: Any,
        type_: Any,
        description: Any,
    ) -> None:
        """Add an EntityHit (score 1.0) to *sink* if *key* is new."""
        if key is None or str(key) in sink:
            return
        sink[str(key)] = EntityHit(
            canonical_key=str(key),
            name=str(name or ""),
            type=str(type_ or ""),
            description=str(description or ""),
            score=1.0,
        )

    def chunks_for_entities(self, keys: list[str], *, limit: int) -> list[ChunkHit]:
        """Chunks that MENTION any given entity, newest/lowest-seq first."""
        if not keys:
            return []
        result = self._driver.execute(
            "MATCH (c:Chunk)-[:MENTIONS]->(e:Entity) "
            "WHERE e.canonical_key IN $keys "
            "WITH DISTINCT c "
            "RETURN c.id, c.text, c.source, c.seq "
            "ORDER BY c.seq ASC "
            f"LIMIT {int(limit)}",
            {"keys": keys},
        )
        return [
            ChunkHit(
                id=str(row[0]),
                text=str(row[1] or ""),
                source=str(row[2] or ""),
                score=1.0,
            )
            for row in result.rows
            if row[0] is not None
        ]
