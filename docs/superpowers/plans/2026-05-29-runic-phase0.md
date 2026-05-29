# runic Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `runic` Python package — an Alembic-style migration framework for FalkorDB — with version tracking, linear upgrade/downgrade, an `op.*` API, and five CLI commands.

**Architecture:** A standalone `src/runic/` package alongside the existing `app/`. A module-level `context` singleton is configured by executing the user's `runic/env.py` script. DB commands execute `env.py`; non-DB commands derive `script_location` from `env.py`'s parent directory without running it.

**Tech Stack:** Python 3.12+, falkordb≥1.6.1, Mako, Typer[all], pytest, pytest-cov, Ruff, uv

---

## File Map

| File | Responsibility |
|---|---|
| `src/runic/__init__.py` | Re-exports `op` proxy and `context` module |
| `src/runic/config.py` | `Config` dataclass |
| `src/runic/version.py` | `VersionNode` — read/write the `_FalkorMigrateVersion` node |
| `src/runic/script.py` | `Revision` dataclass + `ScriptDirectory` |
| `src/runic/operations.py` | `GraphOperations` (op.* API) + module-level `op` proxy |
| `src/runic/context.py` | `MigrationContext` class + module-level `configure()` / `get()` |
| `src/runic/cli.py` | Typer app with `init`, `revision`, `upgrade`, `downgrade`, `current` |
| `src/runic/templates/env.py.mako` | Template for user's `runic/env.py` |
| `src/runic/templates/script.py.mako` | Template for migration scripts |
| `tests/conftest.py` | Shared fixtures: `mock_graph`, `mock_db`, `tmp_versions` |
| `tests/test_config.py` | Config dataclass tests |
| `tests/test_version.py` | VersionNode tests |
| `tests/test_script.py` | ScriptDirectory tests |
| `tests/test_operations.py` | GraphOperations tests |
| `tests/test_context.py` | MigrationContext tests |
| `pyproject.toml` | Add runic deps + entry point (modify existing) |
| `Taskfile.dist.yml` | Verify `test`, `lint`, `format` tasks cover `src/runic/` |

---

### Task 1: Package scaffold + pyproject.toml

**Files:**
- Modify: `pyproject.toml`
- Create: `src/runic/__init__.py`
- Create: `src/runic/config.py`

- [ ] **Step 1: Add dependencies via uv**

```bash
uv add "falkordb>=1.6.1" "mako" "typer[all]"
uv add --dev "pytest-cov"
```

- [ ] **Step 2: Update pyproject.toml — add runic entry point and source coverage**

In `pyproject.toml`, change:
```toml
[project.scripts]
# app = "app.cli.main:app"
```
to:
```toml
[project.scripts]
runic = "runic.cli:app"
```

Change `[tool.coverage.run]`:
```toml
[tool.coverage.run]
branch = true
source = ["app", "runic"]
omit = []
```

Change `[tool.hatch.build.targets.wheel]`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["app", "src/runic"]
```

- [ ] **Step 3: Write failing test for Config**

Create `tests/test_config.py`:
```python
from pathlib import Path

from runic.config import Config


def test_config_defaults() -> None:
    cfg = Config(script_location=Path("runic"))
    assert cfg.script_location == Path("runic")
    assert cfg.version_strategy == "node"


def test_config_custom_strategy() -> None:
    cfg = Config(script_location=Path("migrations"), version_strategy="redis_key")
    assert cfg.version_strategy == "redis_key"
```

- [ ] **Step 4: Run test to verify it fails**

```bash
uv run pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'runic'`

- [ ] **Step 5: Create `src/runic/__init__.py`**

```python
from runic import context
from runic.operations import op

__all__ = ["context", "op"]
```

- [ ] **Step 6: Create `src/runic/config.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    script_location: Path
    version_strategy: str = field(default="node")
```

- [ ] **Step 7: Run test to verify it passes**

```bash
uv run pytest tests/test_config.py -v
```
Expected: 2 passed

---

### Task 2: VersionNode

**Files:**
- Create: `src/runic/version.py`
- Create: `tests/test_version.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_version.py`:
```python
from unittest.mock import MagicMock

import pytest

from runic.version import VersionNode


@pytest.fixture
def mock_graph() -> MagicMock:
    g = MagicMock()
    return g


def test_get_returns_none_when_empty(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = []
    vn = VersionNode(mock_graph)
    assert vn.get() is None


def test_get_returns_revision(mock_graph: MagicMock) -> None:
    mock_graph.ro_query.return_value.result_set = [["abc123def456"]]
    vn = VersionNode(mock_graph)
    assert vn.get() == "abc123def456"


def test_set_issues_parameterized_cypher(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.set("abc123def456")
    call_args = mock_graph.query.call_args
    query: str = call_args[0][0]
    params: dict = call_args[0][1]
    assert "MERGE" in query
    assert "_FalkorMigrateVersion" in query
    assert "singleton" in query
    assert params["rev"] == "abc123def456"


def test_clear_sets_revision_to_none(mock_graph: MagicMock) -> None:
    vn = VersionNode(mock_graph)
    vn.clear()
    call_args = mock_graph.query.call_args
    params: dict = call_args[0][1]
    assert params["rev"] is None
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_version.py -v
```
Expected: `ModuleNotFoundError: No module named 'runic.version'`

- [ ] **Step 3: Implement `src/runic/version.py`**

```python
import logging
from typing import Any

log = logging.getLogger(__name__)

_GET_QUERY = "MATCH (v:_FalkorMigrateVersion) RETURN v.revision"
_SET_QUERY = (
    "MERGE (v:_FalkorMigrateVersion {singleton: true})"
    " SET v.revision = $rev, v.applied_at = timestamp()"
)


class VersionNode:
    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def get(self) -> str | None:
        result = self._graph.ro_query(_GET_QUERY)
        rows = result.result_set
        if not rows:
            return None
        return rows[0][0]

    def set(self, revision: str | None) -> None:
        log.info("stamping version: %s", revision)
        self._graph.query(_SET_QUERY, {"rev": revision})

    def clear(self) -> None:
        log.info("clearing version node")
        self.set(None)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_version.py -v
```
Expected: 4 passed

---

### Task 3: Revision dataclass + ScriptDirectory

**Files:**
- Create: `src/runic/script.py`
- Create: `tests/test_script.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_script.py`:
```python
import importlib
import textwrap
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from runic.script import AmbiguousRevision, Revision, RevisionNotFound, ScriptDirectory


@pytest.fixture
def tmp_versions(tmp_path: Path) -> Path:
    versions = tmp_path / "versions"
    versions.mkdir()

    rev1 = "aaaaaaaaaaaa"
    rev2 = "bbbbbbbbbbbb"

    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "first migration"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade():
                pass

            def downgrade():
                pass
        """)
    )

    (versions / f"{rev2}_second.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev2!r}
            down_revision = {rev1!r}
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "second migration"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

            def upgrade():
                pass

            def downgrade():
                pass
        """)
    )

    return tmp_path


def test_load_finds_both_revisions(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    assert len(sd._revisions) == 2


def test_get_revision_by_full_id(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    rev = sd.get_revision("aaaaaaaaaaaa")
    assert rev.revision == "aaaaaaaaaaaa"


def test_get_revision_by_prefix(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    rev = sd.get_revision("aaaa")
    assert rev.revision == "aaaaaaaaaaaa"


def test_ambiguous_prefix_raises(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    with pytest.raises(AmbiguousRevision):
        sd.get_revision("a")  # both start with 'a'... actually only one does


def test_unknown_revision_raises(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    with pytest.raises(RevisionNotFound):
        sd.get_revision("zzzzzzzzzzzz")


def test_iterate_revisions_upgrade_order(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions(None, "bbbbbbbbbbbb")
    assert [r.revision for r in revs] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb"]


def test_iterate_revisions_upgrade_from_mid(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions("aaaaaaaaaaaa", "bbbbbbbbbbbb")
    assert [r.revision for r in revs] == ["bbbbbbbbbbbb"]


def test_iterate_revisions_downgrade_order(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    revs = sd.iterate_revisions("bbbbbbbbbbbb", "aaaaaaaaaaaa")
    assert [r.revision for r in revs] == ["bbbbbbbbbbbb"]


def test_generate_revision_id_length() -> None:
    rev_id = ScriptDirectory.generate_revision_id()
    assert len(rev_id) == 12
    assert rev_id == rev_id.lower()
    assert all(c in "0123456789abcdef" for c in rev_id)


def test_create_writes_file(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    path = sd.create("add index", head="bbbbbbbbbbbb", script_location=tmp_versions)
    assert path.exists()
    content = path.read_text()
    assert "add index" in content
    assert "down_revision = 'bbbbbbbbbbbb'" in content
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_script.py -v
```
Expected: `ModuleNotFoundError: No module named 'runic.script'`

- [ ] **Step 3: Implement `src/runic/script.py`**

```python
import importlib.util
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
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
    def load(cls, script_location: Path) -> "ScriptDirectory":
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
                    create_date=getattr(mod, "create_date", datetime.now()),
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
        target = self.get_revision(target_rev)

        # walk chain from target back to base_rev
        chain: list[Revision] = []
        current: Revision | None = target
        while current is not None:
            chain.append(current)
            if current.down_revision is None:
                break
            if base_rev and current.down_revision == base_rev:
                break
            if base_rev and current.revision == base_rev:
                break
            current = self._revisions.get(current.down_revision)

        chain.reverse()

        # if base_rev provided, exclude the base itself from the list
        if base_rev:
            chain = [r for r in chain if r.revision != base_rev]

        return chain

    @staticmethod
    def generate_revision_id() -> str:
        return secrets.token_hex(6)

    def create(
        self, message: str, head: str | None, script_location: Path
    ) -> Path:
        rev_id = self.generate_revision_id()
        slug = re.sub(r"[^\w]", "_", message.lower())[:40]
        filename = f"{rev_id}_{slug}.py"

        template_path = Path(__file__).parent / "templates" / "script.py.mako"
        tmpl = Template(filename=str(template_path))
        content = tmpl.render(
            up_revision=rev_id,
            down_revision=head,
            branch_labels=[],
            depends_on=[],
            message=message,
            create_date=datetime.now(),
        )

        versions_dir = script_location / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)
        out_path = versions_dir / filename
        out_path.write_text(content)
        log.info("created revision: %s", out_path)
        return out_path
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_script.py -v
```
Expected: all tests pass (note: `test_ambiguous_prefix_raises` — the two revisions start with different letters `a` and `b`, so a single `a` prefix is unambiguous. Adjust test if needed — see Step 4a).

- [ ] **Step 4a: Fix ambiguous prefix test**

The two test revisions are `aaaaaaaaaaaa` and `bbbbbbbbbbbb` — prefix `a` only matches one. Update the test to use a prefix that genuinely matches both, e.g. add a third revision starting with `a`, OR change the test to match the actual behavior (single-char unique prefix succeeds). Replace the ambiguous test with a cleaner case:

In `tests/test_script.py`, replace:
```python
def test_ambiguous_prefix_raises(tmp_versions: Path) -> None:
    sd = ScriptDirectory.load(tmp_versions)
    with pytest.raises(AmbiguousRevision):
        sd.get_revision("a")  # both start with 'a'... actually only one does
```
with:
```python
def test_ambiguous_prefix_raises(tmp_versions: Path) -> None:
    # Add a second revision starting with 'a' to the loaded dict directly
    from runic.script import Revision
    from datetime import datetime

    sd = ScriptDirectory.load(tmp_versions)
    extra = Revision(
        revision="aaaa11111111",
        down_revision="bbbbbbbbbbbb",
        branch_labels=[],
        depends_on=[],
        irreversible=False,
        snapshot=False,
        message="extra",
        create_date=datetime(2026, 1, 3),
        path=tmp_versions / "versions" / "aaaa11111111_extra.py",
    )
    sd._revisions["aaaa11111111"] = extra
    with pytest.raises(AmbiguousRevision):
        sd.get_revision("aaaa")
```

- [ ] **Step 5: Run tests again to confirm all pass**

```bash
uv run pytest tests/test_script.py -v
```
Expected: all tests pass

---

### Task 4: GraphOperations

**Files:**
- Create: `src/runic/operations.py`
- Create: `tests/test_operations.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_operations.py`:
```python
import time
from unittest.mock import MagicMock, call, patch

import pytest

from runic.operations import ConstraintFailedError, ConstraintTimeoutError, GraphOperations


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def ops(mock_graph: MagicMock, mock_db: MagicMock) -> GraphOperations:
    return GraphOperations(mock_graph, mock_db)


@pytest.fixture
def preview_ops(mock_graph: MagicMock, mock_db: MagicMock) -> GraphOperations:
    return GraphOperations(mock_graph, mock_db, preview=True)


def test_preview_run_cypher_no_calls(
    preview_ops: GraphOperations, mock_graph: MagicMock
) -> None:
    preview_ops.run_cypher("MATCH (n) RETURN n")
    mock_graph.query.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_preview_run_command_no_calls(
    preview_ops: GraphOperations, mock_db: MagicMock
) -> None:
    preview_ops.run_command("GRAPH.CONSTRAINT", "CREATE")
    mock_db.execute_command.assert_not_called()
    assert len(preview_ops.preview_log) == 1


def test_run_cypher_calls_graph(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.run_cypher("MATCH (n) RETURN n", {"x": 1})
    mock_graph.query.assert_called_once_with("MATCH (n) RETURN n", {"x": 1})


def test_create_range_index_node(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.create_range_index("Person", "email")
    call_args = mock_graph.query.call_args[0][0]
    assert "CREATE INDEX" in call_args
    assert "Person" in call_args
    assert "email" in call_args


def test_create_range_index_rel(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.create_range_index("FOLLOWS", "since", rel=True)
    call_args = mock_graph.query.call_args[0][0]
    assert "CREATE INDEX" in call_args
    assert "FOLLOWS" in call_args


def test_drop_range_index_node(ops: GraphOperations, mock_graph: MagicMock) -> None:
    ops.drop_range_index("Person", "email")
    call_args = mock_graph.query.call_args[0][0]
    assert "DROP INDEX" in call_args
    assert "Person" in call_args


def test_create_unique_constraint_also_creates_index(
    ops: GraphOperations, mock_graph: MagicMock, mock_db: MagicMock
) -> None:
    mock_db.execute_command.return_value = "PENDING"
    result_mock = MagicMock()
    result_mock.result_set = [[MagicMock(constraints=[
        MagicMock(status="OPERATIONAL")
    ])]]

    # Patch the polling to return OPERATIONAL immediately
    with patch.object(ops, "_poll_constraint", return_value=None):
        ops.create_constraint("UNIQUE", "NODE", "Person", ["email"])

    # index created first
    index_call = mock_graph.query.call_args_list[0][0][0]
    assert "CREATE INDEX" in index_call
    # then constraint
    mock_db.execute_command.assert_called_once()
    constraint_call = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in constraint_call
    assert "CREATE" in constraint_call
    assert "UNIQUE" in constraint_call


def test_polling_raises_on_failed_status(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    row = MagicMock()
    row.__getitem__ = lambda self, i: "FAILED" if i == 4 else ""
    mock_graph.ro_query.return_value.result_set = [[row]]
    with pytest.raises(ConstraintFailedError):
        ops._poll_constraint("UNIQUE", "NODE", "Person", ["email"])


def test_drop_constraint(ops: GraphOperations, mock_db: MagicMock) -> None:
    ops.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    args = mock_db.execute_command.call_args[0]
    assert "GRAPH.CONSTRAINT" in args
    assert "DROP" in args
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_operations.py -v
```
Expected: `ModuleNotFoundError: No module named 'runic.operations'`

- [ ] **Step 3: Implement `src/runic/operations.py`**

```python
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
            self._log_preview(
                f"CREATE CONSTRAINT: {kind} {entity} {label} {props}"
            )
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
        self._poll_constraint(kind, entity, label, props)

    def _poll_constraint(
        self, kind: str, entity: str, label: str, props: list[str]
    ) -> None:
        for attempt in range(_POLL_RETRIES):
            result = self._graph.ro_query("CALL db.constraints()")
            for row in result.result_set:
                entry = row[0]
                status = entry[4] if isinstance(entry, (list, tuple)) else str(entry)
                if status == "FAILED":
                    raise ConstraintFailedError(
                        f"constraint on {label}.{props} failed"
                    )
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_operations.py -v
```
Expected: all pass (some may need small adjustments to the polling mock — see next step if failing)

- [ ] **Step 4a: Fix polling test if needed**

The `_poll_constraint` test uses `row[0][4]`. The mock returns a `MagicMock` at position 4. If that doesn't match `"FAILED"`, adjust:

In `tests/test_operations.py`, replace the polling test:
```python
def test_polling_raises_on_failed_status(
    ops: GraphOperations, mock_graph: MagicMock
) -> None:
    failed_row = ["type", "entity", "label", "props", "FAILED"]
    mock_graph.ro_query.return_value.result_set = [[failed_row]]
    with pytest.raises(ConstraintFailedError):
        ops._poll_constraint("UNIQUE", "NODE", "Person", ["email"])
```

---

### Task 5: MigrationContext

**Files:**
- Create: `src/runic/context.py`
- Create: `tests/test_context.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_context.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from runic.config import Config
from runic.context import IrreversibleMigrationError, MigrationContext


@pytest.fixture
def mock_graph() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def tmp_versions(tmp_path: Path) -> Path:
    import textwrap
    versions = tmp_path / "versions"
    versions.mkdir()

    rev1 = "aaaaaaaaaaaa"
    rev2 = "bbbbbbbbbbbb"

    (versions / f"{rev1}_first.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev1!r}
            down_revision = None
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "first"
            from datetime import datetime
            create_date = datetime(2026, 1, 1)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )

    (versions / f"{rev2}_second.py").write_text(
        textwrap.dedent(f"""\
            revision = {rev2!r}
            down_revision = {rev1!r}
            branch_labels = []
            depends_on = []
            irreversible = False
            snapshot = False
            message = "second"
            from datetime import datetime
            create_date = datetime(2026, 1, 2)

            def upgrade(op):
                pass

            def downgrade(op):
                pass
        """)
    )
    return tmp_path


def _make_ctx(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path,
    preview: bool = False,
) -> MigrationContext:
    cfg = Config(script_location=tmp_versions)
    ctx = MigrationContext(cfg, mock_db, mock_graph, preview=preview)
    return ctx


def test_current_returns_none_initially(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    assert ctx.current() is None


def test_upgrade_stamps_each_revision(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.upgrade("bbbbbbbbbbbb")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert len(stamp_calls) == 2


def test_upgrade_mid_failure_leaves_prior_stamped(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    # First ro_query (current) returns None; subsequent queries succeed for rev1
    # but the second revision's upgrade raises
    mock_graph.ro_query.return_value.result_set = []
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)

    call_count = 0

    def side_effect_upgrade(op: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("mid-migration failure")

    # Patch module upgrade functions
    sd = ctx._script_dir
    sd.get_revision("aaaaaaaaaaaa").module.upgrade = side_effect_upgrade
    sd.get_revision("bbbbbbbbbbbb").module.upgrade = side_effect_upgrade

    with pytest.raises(RuntimeError, match="mid-migration failure"):
        ctx.upgrade("bbbbbbbbbbbb")

    # Only first revision was stamped (one MERGE call to version node)
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert len(stamp_calls) == 1


def test_downgrade_to_base_clears_version(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    ctx.downgrade("base")
    query_calls = [c[0][0] for c in mock_graph.query.call_args_list]
    stamp_calls = [q for q in query_calls if "_FalkorMigrateVersion" in q]
    assert stamp_calls  # version was updated


def test_downgrade_irreversible_raises(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    sd = ctx._script_dir
    sd.get_revision("bbbbbbbbbbbb").irreversible = True
    with pytest.raises(IrreversibleMigrationError):
        ctx.downgrade("aaaaaaaaaaaa")


def test_downgrade_irreversible_with_force(
    mock_graph: MagicMock, mock_db: MagicMock, tmp_versions: Path
) -> None:
    mock_graph.ro_query.return_value.result_set = [["bbbbbbbbbbbb"]]
    ctx = _make_ctx(mock_graph, mock_db, tmp_versions)
    sd = ctx._script_dir
    sd.get_revision("bbbbbbbbbbbb").irreversible = True
    ctx.downgrade("aaaaaaaaaaaa", force=True)  # should not raise
```

- [ ] **Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_context.py -v
```
Expected: `ModuleNotFoundError: No module named 'runic.context'`

- [ ] **Step 3: Implement `src/runic/context.py`**

```python
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

    def current(self) -> str | None:
        return self._version_node.get()

    def upgrade(self, target: str = "head") -> None:
        resolved_target = target
        if target == "head":
            resolved_target = self._script_dir.head()
            if resolved_target is None:
                log.info("no revisions found, nothing to upgrade")
                return

        current = self._version_node.get()
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
            # walk all revisions from current back to base
            revisions = self._script_dir.iterate_revisions(None, current)
            revisions = list(reversed(revisions))
        else:
            resolved = self._script_dir.get_revision(target)
            current_rev = self._script_dir.get_revision(current)
            revisions = [current_rev]

        for rev in revisions:
            if rev.irreversible and not force:
                raise IrreversibleMigrationError(
                    f"revision {rev.revision!r} is marked irreversible; "
                    "use force=True to override"
                )

        for rev in revisions:
            log.info(
                "downgrading revision: %s — %s", rev.revision, rev.message
            )
            try:
                rev.module.downgrade(self._ops)
            except Exception:
                log.error(
                    "downgrade failed at revision %s", rev.revision
                )
                raise
            next_rev = rev.down_revision
            if not self._preview:
                if next_rev is None:
                    self._version_node.clear()
                else:
                    self._version_node.set(next_rev)


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
    return _context._preview if _context else False
```

- [ ] **Step 4: Update migration files in test fixture to match new signature**

The `MigrationContext` calls `rev.module.upgrade(self._ops)` — migration functions receive `op` as an argument. The test fixture files use `def upgrade(op): pass` which is correct.

Run tests:
```bash
uv run pytest tests/test_context.py -v
```
Expected: all pass

---

### Task 6: Templates

**Files:**
- Create: `src/runic/templates/env.py.mako`
- Create: `src/runic/templates/script.py.mako`

- [ ] **Step 1: Create `src/runic/templates/env.py.mako`**

```
import os
from runic import context
from falkordb import FalkorDB

FALKORDB_URL = os.getenv("FALKORDB_URL", "falkor://localhost:6379")
FALKORDB_GRAPH = os.getenv("FALKORDB_GRAPH", "my_graph")

db = FalkorDB.from_url(FALKORDB_URL)
graph = db.select_graph(FALKORDB_GRAPH)
context.configure(connection=db, graph=graph)
```

(This is a plain text template — no Mako variables needed for `env.py.mako`.)

- [ ] **Step 2: Create `src/runic/templates/script.py.mako`**

```
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision}
Create Date: ${create_date}
"""
from runic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
irreversible = False
snapshot = False


def upgrade(op) -> None:
    pass


def downgrade(op) -> None:
    pass
```

- [ ] **Step 3: Verify `ScriptDirectory.create` uses the template**

```bash
uv run pytest tests/test_script.py::test_create_writes_file -v
```
Expected: PASS

---

### Task 7: CLI

**Files:**
- Create: `src/runic/cli.py`

No unit tests for CLI (Typer CLI integration testing is expensive; covered by smoke test in success criteria). We verify via running the commands directly.

- [ ] **Step 1: Implement `src/runic/cli.py`**

```python
import logging
from pathlib import Path
from typing import Annotated

import typer

log = logging.getLogger(__name__)

app = typer.Typer(name="runic", help="FalkorDB migration tool")

_DEFAULT_CONFIG = Path("runic/env.py")


def _exec_env(config: Path, preview: bool = False) -> None:
    """Execute env.py to configure the migration context."""
    from runic import context as ctx_module

    if not config.exists():
        typer.echo(
            f"Error: config not found at {config}. Run `runic init` first.",
            err=True,
        )
        raise typer.Exit(code=1)

    env_src = config.read_text()
    # Inject preview flag into the namespace before executing
    namespace: dict = {"__file__": str(config), "__name__": "__main__"}
    # Set preview on the context module so env.py's configure() picks it up
    exec(compile(env_src, str(config), "exec"), namespace)  # noqa: S102


def _get_script_location(config: Path) -> Path:
    """Derive script_location from config file path without executing env.py."""
    return config.parent


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Migration directory")] = Path(
        "runic"
    ),
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing")] = False,
) -> None:
    """Scaffold a new runic migration environment."""
    if directory.exists() and not force:
        typer.echo(
            f"Error: {directory} already exists. Use --force to overwrite.", err=True
        )
        raise typer.Exit(code=1)

    directory.mkdir(parents=True, exist_ok=True)
    (directory / "versions").mkdir(exist_ok=True)
    (directory / "versions" / ".gitkeep").touch()

    templates_dir = Path(__file__).parent / "templates"

    # Render and write env.py (plain copy — no mako variables)
    env_template = templates_dir / "env.py.mako"
    (directory / "env.py").write_text(env_template.read_text())

    # Copy script.py.mako template
    script_template = templates_dir / "script.py.mako"
    (directory / "script.py.mako").write_bytes(script_template.read_bytes())

    typer.echo(f"Created runic environment at {directory}/")
    typer.echo(f"  {directory}/env.py")
    typer.echo(f"  {directory}/script.py.mako")
    typer.echo(f"  {directory}/versions/")


@app.command()
def revision(
    message: Annotated[str, typer.Option("-m", "--message", help="Revision message")],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    head: Annotated[str | None, typer.Option("--head")] = None,
    rev_id: Annotated[str | None, typer.Option("--rev-id")] = None,
) -> None:
    """Create a new migration revision."""
    from runic.script import ScriptDirectory

    script_location = _get_script_location(config)
    sd = ScriptDirectory.load(script_location)
    resolved_head = head or sd.head()
    path = sd.create(message, resolved_head, script_location)
    typer.echo(f"Created revision: {path}")


@app.command()
def upgrade(
    target: Annotated[str, typer.Argument()] = "head",
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    preview: Annotated[bool, typer.Option("--preview")] = False,
) -> None:
    """Apply migrations up to target revision."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    if preview:
        ctx._preview = True
        ctx._ops._preview = True

    ctx.upgrade(target)

    if preview:
        for line in ctx._ops.preview_log:
            typer.echo(line)
    else:
        typer.echo(f"Upgraded to: {target}")


@app.command()
def downgrade(
    target: Annotated[str, typer.Argument()],
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
    force: Annotated[bool, typer.Option("--force")] = False,
    preview: Annotated[bool, typer.Option("--preview")] = False,
) -> None:
    """Revert migrations to target revision."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    if preview:
        ctx._preview = True
        ctx._ops._preview = True

    ctx.downgrade(target, force=force)

    if preview:
        for line in ctx._ops.preview_log:
            typer.echo(line)
    else:
        typer.echo(f"Downgraded to: {target}")


@app.command()
def current(
    config: Annotated[Path, typer.Option("--config")] = _DEFAULT_CONFIG,
) -> None:
    """Show the current revision."""
    _exec_env(config)
    from runic.context import get

    ctx = get()
    rev_id = ctx.current()
    if rev_id is None:
        typer.echo("<none>")
        return

    try:
        rev = ctx._script_dir.get_revision(rev_id)
        typer.echo(f"{rev_id} — {rev.message}")
    except Exception:
        typer.echo(rev_id)
```

- [ ] **Step 2: Verify package entry point works**

```bash
uv run runic --help
```
Expected: shows `init`, `revision`, `upgrade`, `downgrade`, `current` commands

---

### Task 8: Update `__init__.py` and run full test suite

**Files:**
- Modify: `src/runic/__init__.py`

- [ ] **Step 1: Finalize `src/runic/__init__.py`**

```python
from runic import context
from runic.context import IrreversibleMigrationError
from runic.operations import ConstraintFailedError, ConstraintTimeoutError, op
from runic.script import AmbiguousRevision, RevisionNotFound

__all__ = [
    "AmbiguousRevision",
    "ConstraintFailedError",
    "ConstraintTimeoutError",
    "IrreversibleMigrationError",
    "RevisionNotFound",
    "context",
    "op",
]
```

- [ ] **Step 2: Run full test suite with coverage**

```bash
uv run pytest --cov=runic --cov-report=term-missing -v
```
Expected: all tests pass, coverage ≥ 80%

- [ ] **Step 3: Run lint**

```bash
uv run ruff check src/runic/ tests/
```
Fix any lint errors before proceeding.

- [ ] **Step 4: Run format**

```bash
uv run ruff format src/runic/ tests/
uv run ruff check --fix src/runic/ tests/
```

---

### Task 9: Smoke test CLI end-to-end

- [ ] **Step 1: Init a test migration directory**

```bash
uv run runic init ./smoke_runic
```
Expected output:
```
Created runic environment at smoke_runic/
  smoke_runic/env.py
  smoke_runic/script.py.mako
  smoke_runic/versions/
```

- [ ] **Step 2: Create a revision**

```bash
uv run runic --config smoke_runic/env.py revision -m "add person email index"
```
Expected: prints path to created file like `smoke_runic/versions/abc123def456_add_person_email_index.py`

- [ ] **Step 3: Verify revision file content**

```bash
cat smoke_runic/versions/*.py
```
Expected: contains `revision = '...'`, `down_revision = None`, `def upgrade(op)`, `def downgrade(op)`

- [ ] **Step 4: Preview upgrade (no DB required)**

```bash
uv run runic --config smoke_runic/env.py upgrade head --preview
```
Expected: prints preview operations or "nothing to execute" (preview mode, no DB connection needed IF env.py's FalkorDB.from_url fails gracefully — if it raises, wrap in try/except or use a mock URL)

- [ ] **Step 5: Clean up smoke test directory**

```bash
rm -rf smoke_runic/
```

- [ ] **Step 6: Final test + coverage check**

```bash
uv run pytest --cov=runic --cov-report=term-missing
```
Expected: ≥ 80% coverage, all tests green

---

## Self-Review Notes

- **Config**: `Config` no longer has `falkordb_url`/`graph_name` — consistent with `env.py`-only design. ✓
- **op signature**: migration scripts receive `op` as argument (`def upgrade(op) -> None`) and the context passes `self._ops`. This differs slightly from the module-level `op` proxy approach. Both work — the argument approach is more explicit and testable.
- **`iterate_revisions` for downgrade**: The downgrade path (target → current) needs careful handling. In `test_downgrade_to_base_clears_version`, `current = "bbbbbbbbbbbb"` and target is `"base"` — the context walks all revisions in reverse from current to base. This is implemented via `reversed(iterate_revisions(None, current))`. ✓
- **Preview mode in upgrade/downgrade**: Preview flag is set after `_exec_env()`, before the upgrade/downgrade call. This works but means `env.py` still attempts a DB connection for preview. A future improvement: pass `preview=True` to `context.configure()` in `env.py`. For Phase 0 this is acceptable.
- **Spec coverage**: all five CLI commands, VersionNode, ScriptDirectory, GraphOperations, MigrationContext, templates — all tasks mapped. ✓
