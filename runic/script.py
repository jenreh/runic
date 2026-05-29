import importlib.util
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from mako.template import Template

log = logging.getLogger(__name__)


class RevisionNotFound(Exception):
    pass


class AmbiguousRevision(Exception):
    pass


@dataclass
class Revision:
    revision: str
    down_revision: str | None
    branch_labels: list[str]
    depends_on: list[str]
    irreversible: bool
    snapshot: bool
    message: str
    create_date: datetime
    path: Path
    module: Any = field(default=None, repr=False)


def _load_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


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

    def get_revision(self, rev_id: str) -> Revision:
        if rev_id in self._revisions:
            return self._revisions[rev_id]
        matches = [r for r in self._revisions if r.startswith(rev_id)]
        if len(matches) == 1:
            return self._revisions[matches[0]]
        if len(matches) > 1:
            raise AmbiguousRevision(f"prefix {rev_id!r} matches: {matches}")
        raise RevisionNotFound(f"revision {rev_id!r} not found")

    def head(self) -> str | None:
        down_revisions = {
            r.down_revision for r in self._revisions.values() if r.down_revision
        }
        heads = [r for r in self._revisions if r not in down_revisions]
        return heads[0] if heads else None

    def iterate_revisions(
        self, base_rev: str | None, target_rev: str
    ) -> list[Revision]:
        """Return ordered revisions between base_rev and target_rev.

        Upgrade path (base_rev is ancestor of target_rev): returns ascending order.
        Downgrade path (base_rev is descendant of target_rev): returns descending order
        (revisions to be downgraded, starting from base_rev).
        """
        target = self.get_revision(target_rev)

        # Try upgrade path: walk from target back toward base_rev/root.
        upgrade_chain: list[Revision] = []
        cur: Revision | None = target
        found_base = False
        while cur is not None:
            upgrade_chain.append(cur)
            if cur.down_revision is None:
                found_base = base_rev is None
                break
            if base_rev and cur.down_revision == base_rev:
                found_base = True
                break
            cur = self._revisions.get(cur.down_revision)

        if found_base or base_rev is None:
            upgrade_chain.reverse()
            if base_rev:
                upgrade_chain = [r for r in upgrade_chain if r.revision != base_rev]
            return upgrade_chain

        # Downgrade path: base_rev is a descendant; walk from base_rev down to target.
        base = self.get_revision(base_rev)
        down_chain: list[Revision] = []
        cur = base
        while cur is not None:
            if cur.revision == target_rev:
                break
            down_chain.append(cur)
            if cur.down_revision is None:
                break
            cur = self._revisions.get(cur.down_revision)

        return down_chain

    @staticmethod
    def generate_revision_id() -> str:
        return secrets.token_hex(6)

    def create(self, message: str, head: str | None, script_location: Path) -> Path:
        rev_id = self.generate_revision_id()
        slug = re.sub(r"[^\w]", "_", message.lower())[:40]
        filename = f"{rev_id}_{slug}.py"

        template_path = Path(__file__).parent / "templates" / "script.py.mako"
        tmpl = Template(
            filename=str(template_path), strict_undefined=True, disable_unicode=False
        )  # noqa: S702
        content = tmpl.render_unicode(
            up_revision=rev_id,
            down_revision=head,
            branch_labels=[],
            depends_on=[],
            message=message,
            create_date=datetime.now(UTC),
        )

        versions_dir = script_location / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        out_path = versions_dir / filename
        out_path.write_text(content)
        log.info("created revision: %s", out_path)
        return out_path
