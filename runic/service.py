from __future__ import annotations

import logging
from pathlib import Path

from runic.script import Revision, RevisionInfo, ScriptDirectory

log = logging.getLogger(__name__)


class RunicService:
    """Facade for all runic operations that do not require a DB connection.

    DB-connected operations (upgrade, downgrade, current, stamp) are provided
    by :class:`runic.context.MigrationContext` which is already usable as an SDK:

    .. code-block:: python

        from runic.context import configure, get

        configure(connection=conn, graph=graph, script_location=Path("runic/"))
        ctx = get()
        ctx.upgrade("head")
    """

    def __init__(self, script_location: Path) -> None:
        self._script_location = script_location
        self._sd = ScriptDirectory.load(script_location)

    # ------------------------------------------------------------------
    # Environment initialisation (static — no script directory needed)
    # ------------------------------------------------------------------

    @staticmethod
    def init(directory: Path, *, force: bool = False) -> None:
        """Scaffold a new runic migration environment on disk.

        Raises :exc:`FileExistsError` when *directory* exists and *force* is False.
        """
        if directory.exists() and not force:
            raise FileExistsError(
                f"{directory} already exists. Use force=True to overwrite."
            )
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "versions").mkdir(exist_ok=True)
        (directory / "versions" / ".gitkeep").touch()

        templates_dir = Path(__file__).parent / "templates"
        (directory / "env.py").write_text((templates_dir / "env.py.mako").read_text())
        (directory / "script.py.mako").write_bytes(
            (templates_dir / "script.py.mako").read_bytes()
        )
        log.info("initialized runic environment at %s", directory)

    # ------------------------------------------------------------------
    # Revision management
    # ------------------------------------------------------------------

    def create_revision(
        self,
        message: str,
        head: str | None = None,
        rev_id: str | None = None,
    ) -> Path:
        """Create a new migration revision script and return its path."""
        resolved_head = head if head is not None else self._sd.head()
        return self._sd.create(
            message, resolved_head, self._script_location, rev_id=rev_id
        )

    def show_revision(self, rev: str) -> Revision:
        """Return full metadata for a single revision (by id or unique prefix)."""
        return self._sd.get_revision(rev)

    # ------------------------------------------------------------------
    # History / DAG queries
    # ------------------------------------------------------------------

    def get_history(self, range_: str | None = None) -> list[RevisionInfo]:
        """Return revision history newest-first.

        *range_* accepts the ``start:end`` format understood by the CLI
        (either side may be omitted to mean base / head respectively).
        """
        if range_:
            parts = range_.split(":")
            start = parts[0].strip() or None
            end = parts[1].strip() if len(parts) > 1 else None
            heads_set = {r.revision for r in self._sd.get_heads()}
            bp_set = {r.revision for r in self._sd.get_branch_points()}
            items: list[RevisionInfo] = [
                RevisionInfo(
                    revision=r.revision,
                    down_revision=r.down_revision,
                    message=r.message,
                    create_date=r.create_date,
                    is_head=r.revision in heads_set,
                    is_branch_point=r.revision in bp_set,
                )
                for r in self._sd.walk_revisions(start, end, "up")
            ]
            return list(reversed(items))
        return list(reversed(self._sd.revision_history()))

    def get_heads(self) -> list[Revision]:
        """Return all head revisions (revisions not referenced as any down_revision)."""
        return self._sd.get_heads()

    def get_branch_points(self) -> list[tuple[Revision, list[str]]]:
        """Return each branch-point revision paired with its direct child revision ids."""
        return [
            (bp, self._sd.get_children(bp.revision))
            for bp in self._sd.get_branch_points()
        ]
