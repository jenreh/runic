from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from runic.config import Config
from runic.exceptions import MultipleHeadsError
from runic.operations import GraphOperations, _bind_op
from runic.script import RevisionNotFound, ScriptDirectory
from runic.version import VersionNode

log = logging.getLogger(__name__)

_MULTIPLE_HEADS_MSG = (
    "Multiple heads detected — run `runic heads` to inspect. "
    "Use `merge` to resolve or specify an explicit target revision."
)


class IrreversibleMigrationError(Exception):
    pass


class MigrationContext:
    def __init__(
        self,
        config: Config,
        db: Any,
        graph: Any,
        preview: bool = False,
    ) -> None:
        self._config = config
        self._db = db
        self._graph = graph
        self._graph_name: str = graph.name
        self._preview = preview
        self._version_node = VersionNode(graph)
        self._script_dir = ScriptDirectory.load(config.script_location)
        self._ops = GraphOperations(graph, db, preview=preview)
        _bind_op(self._ops)

    def get_revision_message(self, rev_id: str) -> str | None:
        try:
            return self._script_dir.get_revision(rev_id).message
        except Exception:
            return None

    def enable_preview(self) -> None:
        self._preview = True
        self._ops._preview = True  # noqa: SLF001

    @property
    def preview_log(self) -> list[str]:
        return self._ops.preview_log

    def current(self) -> str | None:
        return self._version_node.get_single()

    def upgrade(self, target: str = "head") -> None:
        resolved_target: str | None = target
        if target == "head":
            heads = self._script_dir.get_heads()
            if len(heads) > 1:
                raise MultipleHeadsError(_MULTIPLE_HEADS_MSG)
            resolved_target = heads[0].revision if heads else None
            if resolved_target is None:
                log.info("no revisions found, nothing to upgrade")
                return

        current = self._version_node.get_single()
        assert resolved_target is not None
        revisions = self._script_dir.iterate_revisions(current, resolved_target)

        if not revisions:
            log.info("already at target revision: %s", resolved_target)
            return

        for rev in revisions:
            snap_name = f"{self._graph_name}__premig_{rev.revision}"
            if rev.snapshot and not self._preview:
                self._ops.snapshot(snap_name)

            log.info("upgrading to revision: %s — %s", rev.revision, rev.message)
            try:
                rev.module.upgrade(self._ops)
            except Exception:
                if rev.snapshot and not self._preview:
                    log.warning(
                        "upgrade failed, restoring snapshot for revision %s",
                        rev.revision,
                    )
                    self._ops.restore_snapshot(snap_name)
                log.error(
                    "upgrade failed at revision %s; database remains at %s",
                    rev.revision,
                    current,
                )
                raise
            if not self._preview:
                self._version_node.set(rev.revision)
            current = rev.revision

    def downgrade(self, target: str, *, force: bool = False) -> None:
        current = self._version_node.get_single()
        if current is None:
            log.info("nothing to downgrade, no current revision")
            return

        if target == "base":
            revisions = list(
                reversed(self._script_dir.iterate_revisions(None, current))
            )
        else:
            revisions = self._script_dir.iterate_revisions(current, target)

        for rev in revisions:
            if rev.irreversible and not force:
                raise IrreversibleMigrationError(
                    f"revision {rev.revision!r} is marked irreversible; "
                    "use force=True to override"
                )

        for rev in revisions:
            snap_name = f"{self._graph_name}__premig_{rev.revision}"
            used_snapshot = False

            if rev.snapshot and not self._preview:
                existing = self._db.list_graphs()
                if snap_name in existing:
                    log.info("restoring snapshot for revision %s", rev.revision)
                    self._ops.restore_snapshot(snap_name)
                    used_snapshot = True

            if not used_snapshot:
                log.info("downgrading revision: %s — %s", rev.revision, rev.message)
                try:
                    rev.module.downgrade(self._ops)
                except Exception:
                    log.error("downgrade failed at revision %s", rev.revision)
                    raise

            if not self._preview:
                if rev.down_revision is None:
                    self._version_node.clear()
                else:
                    parent = (
                        rev.down_revision
                        if isinstance(rev.down_revision, str)
                        else rev.down_revision[0]
                    )
                    self._version_node.set(parent)

    def stamp(self, target: str, *, purge: bool = False) -> None:
        if purge:
            self._version_node.clear()

        if target == "base":
            self._version_node.clear()
            log.info("stamped: base (cleared)")
        elif target == "heads":
            heads = self._script_dir.get_heads()
            self._version_node.set_multiple([r.revision for r in heads])
            log.info("stamped: heads %s", [r.revision for r in heads])
        else:
            rev = self._script_dir.get_revision(target)
            self._version_node.set(rev.revision)
            log.info("stamped: %s", rev.revision)


# ---------------------------------------------------------------------------
# Module-level singleton API (called from user's env.py)
# ---------------------------------------------------------------------------

_context: MigrationContext | None = None


def configure(
    connection: Any,
    graph: Any,
    script_location: Path | None = None,
    version_strategy: str = "node",
    preview: bool = False,
    *,
    _env_path: Path | None = None,
) -> None:
    global _context
    loc = script_location
    if loc is None and _env_path is not None:
        loc = _env_path.parent
    if loc is None:
        loc = Path("runic")
    cfg = Config(script_location=loc, version_strategy=version_strategy)
    _context = MigrationContext(cfg, connection, graph, preview=preview)
    log.debug("context configured: script_location=%s", loc)


def get() -> MigrationContext:
    if _context is None:
        raise RuntimeError("runic context not configured — was env.py executed?")
    return _context


def is_preview() -> bool:
    return _context._preview if _context else False  # noqa: SLF001


# Re-export RevisionNotFound so env.py users can import from runic.context
__all__ = [
    "IrreversibleMigrationError",
    "MigrationContext",
    "RevisionNotFound",
    "configure",
    "get",
    "is_preview",
]
