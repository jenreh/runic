import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_POLL_RETRIES = 30
_POLL_INTERVAL = 0.5


class ConstraintFailedError(Exception):
    pass


class ConstraintTimeoutError(Exception):
    pass


class GraphOperations:
    def __init__(self, graph: Any, db: Any, preview: bool = False) -> None:
        self._graph = graph
        self._db = db
        self._preview = preview
        self.preview_log: list[str] = []

    def _log_preview(self, description: str) -> None:
        self.preview_log.append(description)
        log.info("[preview] %s", description)

    def run_cypher(self, query: str, params: dict | None = None) -> Any:
        if self._preview:
            self._log_preview(f"CYPHER: {query} params={params}")
            return None
        return self._graph.query(query, params) if params else self._graph.query(query)

    def run_command(self, *args: Any) -> Any:
        if self._preview:
            self._log_preview(f"COMMAND: {' '.join(str(a) for a in args)}")
            return None
        return self._db.execute_command(*args)

    def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if rel:
            query = f"CREATE INDEX FOR ()-[r:{label}]->() ON (r.{prop})"
        else:
            query = f"CREATE INDEX FOR (n:{label}) ON (n.{prop})"
        if self._preview:
            self._log_preview(f"CREATE RANGE INDEX: {query}")
            return
        log.info("creating range index on %s.%s", label, prop)
        self._graph.query(query)

    def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None:
        if rel:
            query = f"DROP INDEX ON :{label}({prop})"
        else:
            query = f"DROP INDEX ON :{label}({prop})"
        if self._preview:
            self._log_preview(f"DROP RANGE INDEX: {query}")
            return
        log.info("dropping range index on %s.%s", label, prop)
        self._graph.query(query)

    def create_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if self._preview:
            self._log_preview(f"CREATE CONSTRAINT: {kind} {entity} {label} {props}")
            return
        if kind == "UNIQUE":
            for prop in props:
                self.create_range_index(label, prop)
        prop_count = str(len(props))
        log.info("creating %s constraint on %s %s %s", kind, entity, label, props)
        self._db.execute_command(
            "GRAPH.CONSTRAINT",
            "CREATE",
            label,
            kind,
            entity,
            label,
            "PROPERTIES",
            prop_count,
            *props,
        )
        self._poll_constraint(label, props)

    def _poll_constraint(self, label: str, props: list[str]) -> None:
        for _ in range(_POLL_RETRIES):
            result = self._graph.ro_query("CALL db.constraints()")
            for row in result.result_set:
                entry = row[0]
                status = entry[4] if isinstance(entry, (list, tuple)) else str(entry)
                if status == "FAILED":
                    raise ConstraintFailedError(f"constraint on {label}.{props} failed")
                if status == "OPERATIONAL":
                    return
            time.sleep(_POLL_INTERVAL)
        raise ConstraintTimeoutError(
            f"constraint on {label}.{props} did not become OPERATIONAL"
        )

    def drop_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        if self._preview:
            self._log_preview(f"DROP CONSTRAINT: {kind} {entity} {label} {props}")
            return
        prop_count = str(len(props))
        log.info("dropping %s constraint on %s %s %s", kind, entity, label, props)
        self._db.execute_command(
            "GRAPH.CONSTRAINT",
            "DROP",
            label,
            kind,
            entity,
            label,
            "PROPERTIES",
            prop_count,
            *props,
        )


_op: GraphOperations | None = None


def _get_op() -> GraphOperations:
    if _op is None:
        raise RuntimeError("op not bound — call context.configure() first")
    return _op


def _bind_op(ops: GraphOperations) -> None:
    global _op
    _op = ops


class _OpProxy:
    """Module-level op proxy delegating to the bound GraphOperations instance."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_get_op(), name)


op = _OpProxy()
