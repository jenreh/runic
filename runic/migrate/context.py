from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

from runic.migrate.adapters import GraphAdapter
from runic.migrate.manifest import SchemaManifest
from runic.migrate.operations import GraphOperations
from runic.migrate.script import (
    Revision,
    RevisionInfo,
    RevisionNotFound,
    ScriptDirectory,
)
from runic.migrate.version import VersionNode

log = logging.getLogger(__name__)


class IrreversibleMigrationError(Exception):
    pass


class Runic:
    """The single SDK entry point for runic migrations.

    Handles both DB-connected operations (upgrade, downgrade, stamp, current)
    and offline DAG queries (get_history, get_heads, create_revision, …).

    Example::

        from pathlib import Path
        from runic import Runic
        from runic.migrate.adapters.falkordb import FalkorDBAdapter

        adapter = FalkorDBAdapter.from_url("falkor://localhost:6379", "my_graph")
        runic = Runic(adapter, script_location=Path("runic/"))
        runic.migrate.upgrade("head")
    """

    def __init__(
        self,
        adapter: GraphAdapter,
        script_location: Path,
        *,
        preview: bool = False,
        target_manifest: SchemaManifest | None = None,
        track_checksums: bool = True,
        track_installed_by: bool = True,
        truncate_slug_length: int = 40,
        file_template: str | None = None,
    ) -> None:
        self._adapter = adapter
        self._script_location = script_location
        self._preview = preview
        self._target_manifest = target_manifest
        self._track_checksums = track_checksums
        self._track_installed_by = track_installed_by
        self._truncate_slug_length = truncate_slug_length
        self._file_template = file_template
        self._version_node = VersionNode(adapter)
        self._script_dir = ScriptDirectory.load(script_location)
        self._ops = GraphOperations(adapter, preview=preview)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def adapter(self) -> GraphAdapter:
        return self._adapter

    @property
    def target_manifest(self) -> SchemaManifest | None:
        return self._target_manifest

    @property
    def script_location(self) -> Path:
        return self._script_location

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def enable_preview(self) -> None:
        self._preview = True
        self._ops._preview = True  # noqa: SLF001

    @property
    def preview_log(self) -> list[str]:
        return self._ops.preview_log

    # ------------------------------------------------------------------
    # DB-connected runtime operations
    # ------------------------------------------------------------------

    def current(self) -> str | None:
        return self._version_node.get_single()

    def get_revision_message(self, rev_id: str) -> str | None:
        try:
            return self._script_dir.get_revision(rev_id).message
        except Exception:
            return None

    def _resolve_upgrade_target(self, target: str) -> str:
        """Resolve +N relative target to an absolute revision id."""
        if not target.startswith("+"):
            return target
        try:
            n = int(target[1:])
        except ValueError:
            return target
        if n == 0:
            return self._version_node.get_single() or "base"
        current_revs = self._version_node.get()
        heads = self._script_dir.get_heads()
        if not heads:
            return "head"
        from runic.migrate.exceptions import MultipleHeadsError

        if len(heads) > 1:
            raise MultipleHeadsError(
                "Cannot use +N with multiple heads — specify an explicit revision."
            )
        head_rev = heads[0].revision
        remaining = self._script_dir.topological_upgrade_path(
            current_revs or None, head_rev
        )
        if not remaining:
            return head_rev
        return remaining[min(n, len(remaining)) - 1].revision

    def _resolve_downgrade_target(self, target: str) -> str:
        """Resolve -N relative target to an absolute revision id or 'base'."""
        if not target.startswith("-"):
            return target
        try:
            n = int(target[1:])
        except ValueError:
            return target
        if n == 0:
            return self._version_node.get_single() or "base"
        current = self._version_node.get_single()
        if current is None:
            return "base"
        all_to_head = self._script_dir.iterate_revisions(None, current)
        chain = list(reversed(all_to_head))
        if n >= len(chain):
            return "base"
        return chain[n].revision

    def validate(self) -> list[str]:
        """Check that applied revisions' local files match their stored checksums.

        Returns a list of error strings (empty means everything is valid).
        Missing checksum entries are skipped (backward compatible with databases
        migrated before checksum tracking was introduced).
        Returns [] immediately when track_checksums=False.
        """
        if not self._track_checksums:
            log.debug("checksum tracking disabled — skipping validate()")
            return []

        from runic.migrate.checksum import file_checksum

        current_revs = self._version_node.get()
        if not current_revs:
            return []

        stored = self._adapter.get_checksums()
        errors: list[str] = []
        checked: set[str] = set()

        for rev_id in current_revs:
            try:
                chain = self._script_dir.iterate_revisions(None, rev_id)
            except Exception as exc:
                errors.append(f"{rev_id}: could not trace revision chain — {exc}")
                continue

            for rev in chain:
                if rev.revision in checked:
                    continue
                checked.add(rev.revision)

                if rev.revision not in stored:
                    log.debug(
                        "no checksum stored for %s (pre-checksum deployment)",
                        rev.revision,
                    )
                    continue

                current_hash = file_checksum(rev.path)
                if current_hash != stored[rev.revision]:
                    errors.append(
                        f"{rev.revision} ({rev.message}): "
                        "checksum mismatch — script was modified after being applied"
                    )

        return errors

    def upgrade(
        self,
        target: str = "head",
        *,
        validate_on_migrate: bool = False,
        installed_by: str | None = None,
    ) -> None:
        if validate_on_migrate:
            errors = self.validate()
            if errors:
                raise ValueError(
                    "Checksum validation failed before upgrade:\n"
                    + "\n".join(f"  {e}" for e in errors)
                )

        if installed_by is None and self._track_installed_by:
            installed_by = os.environ.get("RUNIC_INSTALLED_BY")
            if installed_by is None:
                import getpass

                with contextlib.suppress(Exception):
                    installed_by = getpass.getuser()

        from_revs = self._version_node.get()
        resolved_target = self._resolve_upgrade_target(target)

        revisions = self._script_dir.topological_upgrade_path(
            from_revs or None, resolved_target
        )

        if not revisions:
            log.info("already at target revision: %s", resolved_target)
            return

        for rev in revisions:
            snap_name = f"{self._adapter.name}__premig_{rev.revision}"
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
                    "upgrade failed at revision %s; database was at %s",
                    rev.revision,
                    from_revs,
                )
                raise
            if not self._preview:
                self._version_node.set(rev.revision)
                if self._track_checksums:
                    from runic.migrate.checksum import file_checksum

                    self._adapter.set_checksum(
                        rev.revision, file_checksum(rev.path), installed_by
                    )
            from_revs = [rev.revision]

    def downgrade(self, target: str, *, force: bool = False) -> None:
        current = self._version_node.get_single()
        if current is None:
            log.info("nothing to downgrade, no current revision")
            return

        resolved_target = self._resolve_downgrade_target(target)

        if resolved_target == "base":
            revisions = list(
                reversed(self._script_dir.iterate_revisions(None, current))
            )
        else:
            revisions = self._script_dir.iterate_revisions(current, resolved_target)

        for rev in revisions:
            if rev.irreversible and not force:
                raise IrreversibleMigrationError(
                    f"revision {rev.revision!r} is marked irreversible; "
                    "use force=True to override"
                )

        for rev in revisions:
            snap_name = f"{self._adapter.name}__premig_{rev.revision}"
            used_snapshot = False

            if (
                rev.snapshot
                and not self._preview
                and self._adapter.snapshot_exists(snap_name)
            ):
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

    # ------------------------------------------------------------------
    # Offline DAG queries (no DB connection needed)
    # ------------------------------------------------------------------

    def get_history(self, range_: str | None = None) -> list[RevisionInfo]:
        """Return revision history newest-first.

        *range_* accepts the ``start:end`` format (either side may be omitted
        to mean base / head respectively).
        """
        if range_:
            parts = range_.split(":")
            start = parts[0].strip() or None
            end = parts[1].strip() if len(parts) > 1 else None
            heads_set = {r.revision for r in self._script_dir.get_heads()}
            bp_set = {r.revision for r in self._script_dir.get_branch_points()}
            items: list[RevisionInfo] = [
                RevisionInfo(
                    revision=r.revision,
                    down_revision=r.down_revision,
                    message=r.message,
                    create_date=r.create_date,
                    is_head=r.revision in heads_set,
                    is_branch_point=r.revision in bp_set,
                )
                for r in self._script_dir.walk_revisions(start, end, "up")
            ]
            return list(reversed(items))
        return list(reversed(self._script_dir.revision_history()))

    def get_heads(self) -> list[Revision]:
        """Return all head revisions (not referenced as any down_revision)."""
        return self._script_dir.get_heads()

    def get_branch_points(self) -> list[tuple[Revision, list[str]]]:
        """Return each branch-point revision paired with its direct child revision ids."""
        return [
            (bp, self._script_dir.get_children(bp.revision))
            for bp in self._script_dir.get_branch_points()
        ]

    def create_revision(
        self,
        message: str,
        head: str | None = None,
        rev_id: str | None = None,
        branch_labels: list[str] | None = None,
        depends_on: list[str] | None = None,
    ) -> Path:
        """Create a new migration revision script and return its path."""
        resolved_head = head if head is not None else self._script_dir.head()
        return self._script_dir.create(
            message,
            resolved_head,
            self._script_location,
            branch_labels=branch_labels,
            depends_on=depends_on,
            rev_id=rev_id,
            truncate_slug_length=self._truncate_slug_length,
            file_template=self._file_template,
        )

    def show_revision(self, rev: str) -> Revision:
        """Return full metadata for a single revision (by id or unique prefix)."""
        return self._script_dir.get_revision(rev)

    def baseline(
        self, message: str = "baseline", *, stamp_only: bool = False
    ) -> Path | None:
        """Generate an initial migration from the live graph's schema.

        Introspects indexes and constraints, writes a revision with
        ``down_revision = None`` (root of the chain), and stamps the version
        node so Runic treats it as already applied on the source graph.

        Raises:
            GraphAlreadyManagedError: if the version node already records a
                revision — use ``runic upgrade`` instead.

        Args:
            message: Human-readable revision message.
            stamp_only: Skip writing a .py file; only stamp the version node
                with a freshly generated revision id.

        Returns:
            Path to the generated .py file, or ``None`` for ``stamp_only``.
        """
        from runic.migrate.exceptions import GraphAlreadyManagedError
        from runic.migrate.introspect import (
            full_downgrade_ops,
            full_upgrade_ops,
            introspect_graph,
        )
        from runic.migrate.script import render_op_body

        current = self._version_node.get()
        if current:
            raise GraphAlreadyManagedError(
                "Graph already managed by runic.migrate. Use `runic upgrade` instead."
            )

        rev_id = ScriptDirectory.generate_revision_id()

        if not stamp_only:
            snapshot = introspect_graph(self._adapter._graph)  # ty:ignore[unresolved-attribute]  # noqa: SLF001
            upgrade_ops = full_upgrade_ops(snapshot)
            downgrade_ops = full_downgrade_ops(snapshot)
            file_path = self._script_dir.create(
                message,
                None,
                self._script_location,
                upgrade_body=render_op_body(upgrade_ops),
                downgrade_body=render_op_body(downgrade_ops),
                rev_id=rev_id,
                truncate_slug_length=self._truncate_slug_length,
                file_template=self._file_template,
            )
            log.info("created baseline revision: %s at %s", rev_id, file_path)

        self._version_node.set(rev_id)
        log.info("stamped baseline revision: %s", rev_id)

        return None if stamp_only else file_path


# ---------------------------------------------------------------------------
# Module-level singleton API (called from user's env.py)
# ---------------------------------------------------------------------------

_context: Runic | None = None


def configure(
    adapter: GraphAdapter,
    script_location: Path | None = None,
    preview: bool = False,
    *,
    target_manifest: SchemaManifest | None = None,
    track_checksums: bool = True,
    track_installed_by: bool = True,
    truncate_slug_length: int = 40,
    file_template: str | None = None,
    _env_path: Path | None = None,
) -> None:
    global _context
    loc = script_location
    if loc is None and _env_path is not None:
        loc = _env_path.parent
    if loc is None:
        loc = Path("runic")
    _context = Runic(
        adapter,
        loc,
        preview=preview,
        target_manifest=target_manifest,
        track_checksums=track_checksums,
        track_installed_by=track_installed_by,
        truncate_slug_length=truncate_slug_length,
        file_template=file_template,
    )
    log.debug(
        "context configured: script_location=%s track_checksums=%s track_installed_by=%s",
        loc,
        track_checksums,
        track_installed_by,
    )


def get() -> Runic:
    if _context is None:
        raise RuntimeError("runic context not configured — was env.py executed?")
    return _context


def is_preview() -> bool:
    return _context._preview if _context else False  # noqa: SLF001


# Re-export RevisionNotFound so env.py users can import from runic.migrate.context
__all__ = [
    "IrreversibleMigrationError",
    "RevisionNotFound",
    "Runic",
    "configure",
    "get",
    "is_preview",
]
