import logging
from pathlib import Path
from typing import Any

from runic.config import Config
from runic.operations import GraphOperations, _bind_op
from runic.script import ScriptDirectory
from runic.version import VersionNode

log = logging.getLogger(__name__)


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
        return self._version_node.get()

    def upgrade(self, target: str = "head") -> None:
        resolved_target: str | None = target
        if target == "head":
            resolved_target = self._script_dir.head()
            if resolved_target is None:
                log.info("no revisions found, nothing to upgrade")
                return

        current = self._version_node.get()
        assert resolved_target is not None
        revisions = self._script_dir.iterate_revisions(current, resolved_target)

        if not revisions:
            log.info("already at target revision: %s", resolved_target)
            return

        for rev in revisions:
            log.info("upgrading to revision: %s — %s", rev.revision, rev.message)
            try:
                rev.module.upgrade(self._ops)
            except Exception:
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
        current = self._version_node.get()
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
                    self._version_node.set(rev.down_revision)


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
