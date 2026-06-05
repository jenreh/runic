from __future__ import annotations

import importlib.util
import logging
import re
import secrets
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal

from mako.template import Template

from runic.migrate.exceptions import MultipleBasesError, MultipleHeadsError

if TYPE_CHECKING:
    from runic.migrate.introspect import OpCall

log = logging.getLogger(__name__)


class RevisionNotFound(Exception):
    pass


class AmbiguousRevision(Exception):
    pass


@dataclass
class Revision:
    revision: str
    down_revision: str | tuple[str, ...] | None
    branch_labels: list[str]
    depends_on: list[str]
    irreversible: bool
    snapshot: bool
    message: str
    create_date: datetime
    path: Path
    module: Any = field(default=None, repr=False)


@dataclass
class RevisionInfo:
    revision: str
    down_revision: str | tuple[str, ...] | None
    message: str
    create_date: datetime
    is_head: bool
    is_branch_point: bool


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _down_revision_parents(rev: Revision) -> set[str]:
    if rev.down_revision is None:
        return set()
    if isinstance(rev.down_revision, tuple):
        return set(rev.down_revision)
    return {rev.down_revision}


# ---------------------------------------------------------------------------
# Op-call rendering — used by `runic baseline` to generate script bodies
# ---------------------------------------------------------------------------


def _render_op_call(op: OpCall) -> str:
    """Render a single OpCall as a Python expression string (no indentation)."""
    parts = [repr(a) for a in op.args]
    parts += [f"{k}={v!r}" for k, v in op.kwargs.items()]
    call = f"op.{op.method}({', '.join(parts)})"
    if op.comment is not None:
        return f"# {call}  # {op.comment}"
    return call


def render_op_body(ops: list[OpCall]) -> str:
    """Convert a list of OpCall objects into an indented function body.

    Emits ``# --- Indexes ---`` and ``# --- Constraints ---`` section headers
    whenever the category changes.  The input order is preserved so that
    ``full_downgrade_ops`` (constraints-first) renders correctly — the renderer
    must not re-sort the list.
    """
    if not ops:
        return "    pass"

    lines: list[str] = []
    current_section: str | None = None

    for op in ops:
        section = "Constraints" if "constraint" in op.method else "Indexes"
        if section != current_section:
            lines.append(f"    # --- {section} ---")
            current_section = section
        lines.append(f"    {_render_op_call(op)}")

    return "\n".join(lines)


class ScriptDirectory:
    def __init__(self) -> None:
        self._revisions: dict[str, Revision] = {}

    @classmethod
    def load(cls, script_location: Path) -> ScriptDirectory:
        sd = cls()
        versions_dir = script_location / "versions"
        if not versions_dir.exists():
            return sd
        for py_file in sorted(versions_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                mod = _load_module(py_file)
                rev = Revision(
                    revision=mod.revision,
                    down_revision=getattr(mod, "down_revision", None),
                    branch_labels=getattr(mod, "branch_labels", []),
                    depends_on=getattr(mod, "depends_on", []),
                    irreversible=getattr(mod, "irreversible", False),
                    snapshot=getattr(mod, "snapshot", False),
                    message=getattr(mod, "message", ""),
                    create_date=getattr(mod, "create_date", datetime.now(UTC)),
                    path=py_file,
                    module=mod,
                )
                sd._revisions[rev.revision] = rev
                log.debug("loaded revision: %s from %s", rev.revision, py_file.name)
            except Exception:
                log.warning("failed to load revision from %s", py_file)
                raise
        return sd

    # ------------------------------------------------------------------
    # DAG queries
    # ------------------------------------------------------------------

    def get_heads(self) -> list[Revision]:
        """All revisions not referenced as down_revision by any other."""
        referenced: set[str] = set()
        for rev in self._revisions.values():
            referenced.update(_down_revision_parents(rev))
        heads = [r for r in self._revisions.values() if r.revision not in referenced]
        return sorted(heads, key=lambda r: r.create_date, reverse=True)

    def get_base(self) -> Revision:
        """Revision with down_revision is None; raises MultipleBasesError if >1."""
        bases = [r for r in self._revisions.values() if r.down_revision is None]
        if len(bases) > 1:
            raise MultipleBasesError(
                f"multiple base revisions: {[r.revision for r in bases]!r}"
            )
        if not bases:
            raise RevisionNotFound("no base revision found")
        return bases[0]

    def get_branch_points(self) -> list[Revision]:
        """Revisions that appear as down_revision in two or more scripts."""
        parent_count: dict[str, int] = {}
        for rev in self._revisions.values():
            for parent in _down_revision_parents(rev):
                parent_count[parent] = parent_count.get(parent, 0) + 1
        return [
            self._revisions[rev_id]
            for rev_id, count in parent_count.items()
            if count >= 2 and rev_id in self._revisions
        ]

    def walk_revisions(
        self,
        start: str | None,
        end: str | None,
        direction: Literal["up", "down"],
    ) -> Iterator[Revision]:
        """Yield revisions in application order between start (exclusive) and end (inclusive).

        start=None → from base; end=None → to/from head.
        Raises MultipleHeadsError when direction is "up" and end is None and multiple heads exist.
        """
        if end is None:
            heads = self.get_heads()
            if direction == "up" and len(heads) > 1:
                raise MultipleHeadsError(
                    "Multiple heads detected — run `runic heads` to inspect. "
                    "Use `merge` to resolve or specify an explicit target revision."
                )
            end = heads[0].revision if heads else None

        if end is None:
            return

        revisions = self.iterate_revisions(start, end)

        if direction == "down":
            revisions = list(reversed(revisions))

        yield from revisions

    def revision_history(self, verbose: bool = False) -> list[RevisionInfo]:  # noqa: ARG002
        """Full chronological list (oldest first)."""
        heads = {r.revision for r in self.get_heads()}
        branch_points = {r.revision for r in self.get_branch_points()}
        all_revs = sorted(self._revisions.values(), key=lambda r: r.create_date)
        return [
            RevisionInfo(
                revision=r.revision,
                down_revision=r.down_revision,
                message=r.message,
                create_date=r.create_date,
                is_head=r.revision in heads,
                is_branch_point=r.revision in branch_points,
            )
            for r in all_revs
        ]

    def get_revision(self, rev_id: str) -> Revision:
        """Look up a revision by id, unique prefix, or the symbols 'head' / 'base'."""
        if rev_id == "head":
            heads = self.get_heads()
            if len(heads) > 1:
                raise MultipleHeadsError(
                    "Multiple heads detected — use `runic heads` to inspect. "
                    "Use `merge` to resolve or specify an explicit target."
                )
            if not heads:
                raise RevisionNotFound("no revisions found")
            return heads[0]
        if rev_id == "base":
            return self.get_base()
        if rev_id in self._revisions:
            return self._revisions[rev_id]
        matches = [r for r in self._revisions if r.startswith(rev_id)]
        if len(matches) == 1:
            return self._revisions[matches[0]]
        if len(matches) > 1:
            raise AmbiguousRevision(f"prefix {rev_id!r} matches: {matches}")
        raise RevisionNotFound(f"revision {rev_id!r} not found")

    # ------------------------------------------------------------------
    # Phase 0 compatibility
    # ------------------------------------------------------------------

    def head(self) -> str | None:
        heads = self.get_heads()
        return heads[0].revision if heads else None

    def iterate_revisions(
        self, base_rev: str | None, target_rev: str
    ) -> list[Revision]:
        """Return ordered revisions between base_rev and target_rev.

        Upgrade path: returns ascending order.
        Downgrade path: returns descending order (revisions to downgrade).
        """
        target = self.get_revision(target_rev)

        upgrade_chain: list[Revision] = []
        cur: Revision | None = target
        found_base = False
        while cur is not None:
            upgrade_chain.append(cur)
            parents = _down_revision_parents(cur)
            if not parents:
                found_base = base_rev is None
                break
            if base_rev and base_rev in parents:
                found_base = True
                break
            parent_id = next(iter(parents))
            cur = self._revisions.get(parent_id)

        if found_base or base_rev is None:
            upgrade_chain.reverse()
            if base_rev:
                upgrade_chain = [r for r in upgrade_chain if r.revision != base_rev]
            return upgrade_chain

        base = self.get_revision(base_rev)
        down_chain: list[Revision] = []
        cur = base
        while cur is not None:
            if cur.revision == target.revision:
                break
            down_chain.append(cur)
            parents = _down_revision_parents(cur)
            if not parents:
                break
            parent_id = next(iter(parents))
            cur = self._revisions.get(parent_id)

        return down_chain

    def get_children(self, rev_id: str) -> list[str]:
        """Return revision ids whose down_revision includes rev_id."""
        return [
            r.revision
            for r in self._revisions.values()
            if rev_id in _down_revision_parents(r)
        ]

    # ------------------------------------------------------------------
    # Phase 4 — topological upgrade path
    # ------------------------------------------------------------------

    def _ancestors(self, rev_id: str) -> set[str]:
        """Return all ancestor revision ids including rev_id itself."""
        seen: set[str] = set()
        stack = [rev_id]
        while stack:
            r = stack.pop()
            if r in seen:
                continue
            seen.add(r)
            rev = self._revisions.get(r)
            if rev is None:
                continue
            stack.extend(_down_revision_parents(rev))
        return seen

    def topological_upgrade_path(
        self,
        from_revs: list[str] | None,
        to_rev: str,
    ) -> list[Revision]:
        """Return revisions to apply in valid topological order from from_revs to to_rev.

        Uses Kahn's BFS algorithm. Raises MultipleHeadsError when to_rev='head' and
        multiple heads exist. Returns [] when already at to_rev.
        """
        if to_rev == "head":
            heads = self.get_heads()
            if len(heads) > 1:
                raise MultipleHeadsError(
                    "Multiple heads detected — run `runic heads` to inspect. "
                    "Use `merge` to resolve or specify an explicit target revision."
                )
            if not heads:
                return []
            to_rev = heads[0].revision
        else:
            to_rev = self.get_revision(to_rev).revision

        from_set = set(from_revs or [])

        # All ancestors of each from_rev (including from_rev itself) = already satisfied
        already_satisfied: set[str] = set()
        for r in from_set:
            already_satisfied.update(self._ancestors(r))

        # Ancestors of to_rev that still need applying
        target_ancestors = self._ancestors(to_rev)
        to_apply_ids = target_ancestors - already_satisfied

        if not to_apply_ids:
            return []

        # Kahn's topological sort
        in_degree: dict[str, int] = dict.fromkeys(to_apply_ids, 0)
        children: dict[str, list[str]] = {rid: [] for rid in to_apply_ids}  # noqa: C420

        for rid in to_apply_ids:
            rev = self._revisions[rid]
            for parent in _down_revision_parents(rev):
                if parent in to_apply_ids:
                    in_degree[rid] += 1
                    children[parent].append(rid)

        queue: deque[str] = deque(rid for rid in to_apply_ids if in_degree[rid] == 0)
        result: list[Revision] = []

        while queue:
            rid = queue.popleft()
            result.append(self._revisions[rid])
            for child in children[rid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(result) != len(to_apply_ids):
            raise RuntimeError("cycle detected in revision graph")

        return result

    @staticmethod
    def generate_revision_id() -> str:
        return secrets.token_hex(6)

    def create(
        self,
        message: str,
        head: str | tuple[str, ...] | None,
        script_location: Path,
        *,
        branch_labels: list[str] | None = None,
        depends_on: list[str] | None = None,
        upgrade_body: str = "    pass",
        downgrade_body: str = "    pass",
        rev_id: str | None = None,
        truncate_slug_length: int = 40,
        file_template: str | None = None,
    ) -> Path:
        rev_id = rev_id or self.generate_revision_id()
        slug = re.sub(r"[^\w]", "_", message.lower())[:truncate_slug_length]
        if file_template is not None:
            now = datetime.now(UTC)
            filename = (
                file_template
                % {
                    "rev": rev_id,
                    "slug": slug,
                    "year": now.year,
                    "month": now.month,
                    "day": now.day,
                    "hour": now.hour,
                    "minute": now.minute,
                }
            ) + ".py"
        else:
            filename = f"{rev_id}_{slug}.py"

        template_path = Path(__file__).parent / "templates" / "script.py.mako"
        tmpl = Template(template_path.read_text())  # noqa: S702
        content = tmpl.render(
            up_revision=rev_id,
            down_revision=head,
            branch_labels=branch_labels or [],
            depends_on=depends_on or [],
            message=message,
            create_date=datetime.now(UTC),
            upgrade_body=upgrade_body,
            downgrade_body=downgrade_body,
        )

        versions_dir = script_location / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        out_path = versions_dir / filename
        out_path.write_text(content)
        log.info("created revision: %s", out_path)
        return out_path
