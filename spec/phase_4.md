# FalkorMigrate — Claude Code Prompts (Phase 4)

---

## Phase 4 — Autogenerate, Merge & CI Gate

### Task

Deliver the three convenience features that complete the framework for larger teams:

1. **`merge` command** — creates a merge revision with a tuple `down_revision`,
   plus a topological upgrade path so the engine can apply both branch heads and
   the merge revision in a single `upgrade` call.
2. **Autogenerate** — a declarative `SchemaManifest` (indexes + constraints),
   a live-schema introspector, a diff engine, and `revision --autogenerate` which
   emits candidate `op.*` calls into a new revision file for human review.
3. **`check` command** — non-zero exit when autogenerate would produce any ops;
   intended as a CI gate (`task check` / `pre-push` hook).

Secondary additions bound tightly to the above:

- `revision` gains `--branch-label` and `--depends-on` flags (flags already exist
  in the `Revision` dataclass but were never wired into the CLI / `create()`).
- `ScriptDirectory.create()` is extended to accept all revision metadata.
- An optional post-generation formatting hook runs `ruff format` (or a
  user-supplied command) on generated files.
- `context.configure()` gains a `target_manifest` parameter so autogenerate can
  read the manifest without extra plumbing.

Phase 4 is explicitly marked *nice-to-have* in the concept document — the framework
is complete without it. Keep every addition additive; do not change behaviour of any
Phase 0–3 code path that is not required by Phase 4.

---

### Context

**What is already implemented (Phases 0–3):**

- `runic/script.py` — `Revision` dataclass with `down_revision: str | tuple[str, ...] | None`,
  `branch_labels: list[str]`, `depends_on: list[str]`, `snapshot: bool`, `irreversible: bool`.
  `ScriptDirectory` with `get_heads()`, `get_base()`, `get_branch_points()`,
  `walk_revisions()`, `revision_history()`, `iterate_revisions()`, `create()`.
- `runic/version.py` — `VersionNode` with `get() → list[str]`, `set`, `set_multiple`, `clear`.
- `runic/context.py` — `MigrationContext` with `upgrade`, `downgrade`, `stamp`;
  module-level `configure(connection, graph, ...) → None`.
- `runic/operations.py` — full `GraphOperations` including `snapshot()` / `restore_snapshot()`
  (added in Phase 3), all index/constraint/data ops, module-level `op` proxy.
- `runic/testing.py` — `falkordb_graph` / `runic_context` pytest fixtures (Phase 3).
- `runic/cli.py` — all Phase 0–3 commands; `revision` command currently hardcodes
  `branch_labels=[]` and `depends_on=[]` and passes `head: str | None` to `create()`.
- `runic/templates/script.py.mako` — current template has `${up_revision}`,
  `${down_revision}`, `${branch_labels}`, `${depends_on}` and a fixed `pass` body.

**Key gap to address:** `ScriptDirectory.iterate_revisions()` performs a linear chain
walk — it cannot traverse a merge node (tuple `down_revision`). A topological sort
is needed for the upgrade path when multiple heads are present.

**Autogenerate scope (from spec §2.9):** Only indexes and constraints are
introspectable. Labels, relationship types, and properties materialize implicitly
and cannot be diffed. Autogenerate cannot detect renames (sees drop + add) and cannot
generate data migrations. All generated output is **candidate code requiring human
review** — the framework must make this unmistakably clear in the generated file.

**FalkorDB introspection caveats (from spec §caveats):**
> `db.indexes()` / `db.constraints()` field names were not fully verifiable from
> public documentation.

The introspector **must** verify exact column names and positions against a running
FalkorDB instance before shipping. The safe approach is to use named-key access if
the result set supports it, or to document the assumed column order and add an
assertion that fails loudly if the shape changes.

---

### Requirements

**1. `ScriptDirectory.topological_upgrade_path()` (`script.py`)**

Add a new method:

```python
def topological_upgrade_path(
    self,
    from_revs: list[str] | None,
    to_rev: str,
) -> list[Revision]:
```

- `from_revs` — the revisions currently applied (from `VersionNode.get()`);
  `None` or `[]` means base (nothing applied).
- `to_rev` — the target revision id (or `"head"`).
- Returns revisions in a **valid topological application order** between the
  `from_revs` set and `to_rev` (inclusive), using Kahn's algorithm (BFS topological
  sort). A revision is eligible when all its `down_revision` parents are either in
  `from_revs` or already yielded.
- Raises `MultipleHeadsError` if `to_rev == "head"` and multiple heads exist.
- Raises `RevisionNotFound` if `to_rev` is not reachable from `from_revs`.
- For a linear chain (no merge nodes) the result must be identical to
  `iterate_revisions` — this is a backward-compatibility invariant verified by tests.

Keep `iterate_revisions()` unchanged — it is still used by `downgrade()`.

**2. `MigrationContext.upgrade()` — topological path (`context.py`)**

Replace the `self._script_dir.iterate_revisions(current, resolved_target)` call with:

```python
from_revs = self._version_node.get()  # list[str], empty at base
revisions = self._script_dir.topological_upgrade_path(from_revs or None, resolved_target)
```

After upgrading a merge revision to `M` (where `M.down_revision` is a tuple),
call `self._version_node.set(M.revision)` — the multi-head state collapses to a
single head after the merge.

**3. `merge` CLI command (`cli.py`)**

```
runic merge <r1> <r2> -m "message" [--config PATH] [--branch-label LABEL]
```

Behaviour:

1. Load `ScriptDirectory` from `config`.
2. Resolve `r1` and `r2` to full revision ids (via `get_revision()`).
3. Verify both are current heads (`get_heads()`) — warn (but do not error) if
   either is not a head, since `--splice`-style merges are valid.
4. Call `ScriptDirectory.create()` with
   `down_revision=(r1_full, r2_full)` and the supplied message.
5. Print the created file path.

**4. `ScriptDirectory.create()` extension (`script.py`)**

Extend the signature to:

```python
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
) -> Path:
```

- `head` now accepts a tuple for merge revisions.
- `branch_labels` and `depends_on` default to `[]` if `None`.
- `upgrade_body` and `downgrade_body` are indented code blocks (4-space indent) that
  replace the `pass` statements in the template.
- `rev_id` — if supplied, use it instead of generating a random one (for autogenerate
  determinism in tests and for `--rev-id` CLI flag).

**5. Template update (`runic/templates/script.py.mako`)**

Replace the fixed `pass` bodies with template variables:

```mako
def upgrade(op) -> None:
${upgrade_body}


def downgrade(op) -> None:
${downgrade_body}
```

Render `upgrade_body` and `downgrade_body` as pre-indented strings; the template
does **not** add extra indentation.

**6. `revision` command — new flags (`cli.py`)**

Add to the existing `revision` command:

- `--branch-label TEXT` — passed through to `create()`.
- `--depends-on TEXT` — multiple allowed (`typer.Option(..., multiple=True)`);
  passed through to `create()`.
- `--rev-id TEXT` — override auto-generated revision id.
- `--autogenerate` (bool flag) — triggers autogenerate; see §7 below.
- `--format` (bool flag, default `False`) — run `ruff format <file>` on the
  generated file after creation (swallow error if `ruff` is not installed, log
  at `WARNING`).

**7. `runic/manifest.py` — declarative schema manifest**

Create a new module with plain dataclasses (no external deps):

```python
@dataclass
class RangeIndex:
    label: str
    prop: str
    rel: bool = False

@dataclass
class FulltextIndex:
    label: str
    props: list[str]
    language: str | None = None
    stopwords: list[str] | None = None

@dataclass
class VectorIndex:
    label: str
    prop: str
    dimension: int
    similarity: str
    m: int = 16
    ef_construction: int = 200
    ef_runtime: int = 10

@dataclass
class UniqueConstraint:
    entity: str   # "NODE" | "RELATIONSHIP"
    label: str
    props: list[str]

@dataclass
class MandatoryConstraint:
    entity: str
    label: str
    props: list[str]

@dataclass
class SchemaManifest:
    range_indexes: list[RangeIndex] = field(default_factory=list)
    fulltext_indexes: list[FulltextIndex] = field(default_factory=list)
    vector_indexes: list[VectorIndex] = field(default_factory=list)
    constraints: list[UniqueConstraint | MandatoryConstraint] = field(default_factory=list)
```

Export all names from `runic/__init__.py`.

**8. `runic/introspect.py` — live schema reader**

Create a module that queries a live graph and returns a normalised view.

Public API:

```python
@dataclass
class LiveSchema:
    range_indexes: list[RangeIndex]
    fulltext_indexes: list[FulltextIndex]
    vector_indexes: list[VectorIndex]
    constraints: list[UniqueConstraint | MandatoryConstraint]

def read_live_schema(graph: Any) -> LiveSchema: ...
```

Implementation:

- Issue `graph.ro_query("CALL db.indexes() YIELD *")` (or the equivalent without
  `YIELD *` if the FalkorDB version does not support it — verify against installed
  version).
- **Important:** The exact column names / positions returned by `CALL db.indexes()`
  and `CALL db.constraints()` are not formally documented. Determine the shape by
  running against a live FalkorDB instance (`falkordblite` works). Add an assertion
  or a clear `NotImplementedError` if the shape does not match expectations, so a
  version upgrade surfaces as an immediate error rather than silent misparse.
- Exclude any index or constraint whose label is `_FalkorMigrateVersion`.
- Map each row to the appropriate dataclass using type/entity-type/label/props fields.
- For constraints, also read `status` and only include `OPERATIONAL` ones in
  `LiveSchema` (a `PENDING` or `UNDER CONSTRUCTION` constraint is not yet enforced).

**9. `runic/autogen.py` — diff engine and code generator**

```python
@dataclass
class DiffOp:
    action: Literal["create", "drop"]
    op_call: str        # Python source line, e.g. 'op.create_range_index("Person", "email")'
    inverse_call: str   # Corresponding reverse op for downgrade body

def diff_schema(manifest: SchemaManifest, live: LiveSchema) -> list[DiffOp]: ...
def render_upgrade_body(ops: list[DiffOp]) -> str: ...
def render_downgrade_body(ops: list[DiffOp]) -> str: ...
```

Diff rules:

- Convert both manifest and live schema to a canonical set of frozen keys
  (a tuple of `(kind, entity, label, props_tuple, ...)`).
- `to_create = manifest_set - live_set` → `DiffOp(action="create", ...)`.
- `to_drop = live_set - manifest_set` → `DiffOp(action="drop", ...)`.
- **Ordering in upgrade body:**
  1. Drop ops: UNIQUE/MANDATORY constraints first (before their backing index),
     then drop indexes.
  2. Create ops: indexes first (UNIQUE constraint requires prior index), then
     constraints.
- **Ordering in downgrade body:** reverse of upgrade.
- `render_upgrade_body` returns a 4-space-indented, newline-separated string of
  `op.*` calls, prefixed with the comment:
  ```python
  # AUTOGENERATED — review before applying; cannot detect renames
  ```
- `render_downgrade_body` returns the same structure for the inverse ops.

**10. `revision --autogenerate` wiring (`cli.py`)**

When `--autogenerate` is passed to the `revision` command:

1. Execute `env.py` (via `_exec_env`) to get a configured `MigrationContext`.
2. Retrieve `target_manifest` from `context.get()._target_manifest`; if `None`,
   exit with error: `"--autogenerate requires target_manifest to be set in env.py"`.
3. Read live schema: `introspect.read_live_schema(context.get()._graph)`.
4. Compute diff: `autogen.diff_schema(manifest, live)`.
5. If diff is empty, print `"No schema changes detected."` and exit 0 without
   creating a file.
6. Generate upgrade/downgrade bodies via `render_upgrade_body` / `render_downgrade_body`.
7. Call `ScriptDirectory.create(..., upgrade_body=..., downgrade_body=...)`.
8. Print the created path with a `[CANDIDATE — review before applying]` suffix.

**11. `context.configure()` — `target_manifest` parameter (`context.py`)**

Add `target_manifest: SchemaManifest | None = None` to `configure()` and store it
on `MigrationContext` as `self._target_manifest`. No other behaviour changes.

**12. `check` command (`cli.py`)**

```
runic check [--config PATH]
```

1. Execute `env.py`.
2. Retrieve `target_manifest`; if `None`, exit with error.
3. Read live schema.
4. Compute diff.
5. If diff is non-empty, print each pending op and exit **non-zero (1)**:

   ```
   Pending schema changes (run `runic revision --autogenerate -m "..."` to generate):
     + op.create_range_index("Person", "email")
     - op.drop_vector_index("Document", "old_embedding")
   ```

6. If diff is empty, print `"Schema up-to-date."` and exit 0.

This command is designed to be called in CI (`task check` or `pre-push` hook).

**13. Tests**

Add to the test suite without modifying passing Phase 0–3 tests.

`tests/test_autogen.py` (unit, no live DB):

- `test_diff_empty_when_schemas_match` — manifest and live identical → empty diff.
- `test_diff_creates_missing_range_index` — manifest has `RangeIndex("Person", "email")`,
  live is empty → one `DiffOp(action="create")` with `op_call` containing
  `create_range_index`.
- `test_diff_drops_extra_index` — live has index not in manifest → `DiffOp(action="drop")`.
- `test_diff_unique_constraint_ordering` — create path emits index before constraint;
  drop path emits constraint before index.
- `test_render_upgrade_body_contains_comment` — output starts with autogenerated comment.
- `test_render_downgrade_body_is_inverse` — upgrade creates index → downgrade drops it.

`tests/test_merge.py` (unit, mocked):

- `test_create_merge_revision` — `ScriptDirectory.create()` with tuple `down_revision`
  generates a file with `down_revision = ('r1', 'r2')`.
- `test_topological_path_linear` — 3-revision linear chain: result equals
  `iterate_revisions` output.
- `test_topological_path_merge` — two branches `A→B` and `A→C`, merge revision
  `M(down_revision=(B, C))`; `topological_upgrade_path(from_revs=["A"], to_rev="M")`
  returns `[B, C, M]` or `[C, B, M]` (either order of B and C is valid; only M must
  be last).
- `test_topological_path_from_both_heads` — DB is at `[B, C]`, upgrading to `M`
  returns `[M]` only.
- `test_upgrade_context_merges_version_node` — after applying merge revision M,
  `VersionNode.get()` returns `["M"]` (single entry).

`tests/test_manifest.py` (unit):

- `test_schema_manifest_defaults` — `SchemaManifest()` has empty lists.
- `test_range_index_eq` — two `RangeIndex("Person", "email")` instances compare equal
  (used for set-based diff).

`tests/test_check_command.py` (unit, mocked CLI):

- `test_check_exits_0_when_no_diff` — mock diff returns empty → exit 0.
- `test_check_exits_1_when_pending_ops` — mock diff returns one op → exit 1.
- `test_check_exits_1_when_no_manifest` — `target_manifest` is `None` → exit 1.

Integration test additions in `tests/test_integration.py`
(guarded with `pytest.importorskip("falkordblite")`):

- `test_autogen_round_trip` — configure manifest with one `RangeIndex`, start from
  empty graph, call `revision --autogenerate`, apply generated revision with
  `upgrade("head")`, verify `CALL db.indexes()` returns the expected index,
  call `downgrade("base")`, verify index absent.
- `test_merge_upgrade` — create two branch scripts (each adding one node), a merge
  revision; start from base, call `upgrade("head")` (which should hit the merge),
  assert both nodes exist and `VersionNode.get()` returns single merge revision id.

---

### Deliverables

- `runic/manifest.py` — new module.
- `runic/introspect.py` — new module.
- `runic/autogen.py` — new module.
- `runic/script.py` — `topological_upgrade_path()` added; `create()` extended.
- `runic/templates/script.py.mako` — `upgrade_body` / `downgrade_body` variables.
- `runic/context.py` — `target_manifest` parameter on `configure()` and stored on
  `MigrationContext`.
- `runic/cli.py` — `merge` and `check` commands; `revision` gains `--autogenerate`,
  `--branch-label`, `--depends-on`, `--rev-id`, `--format`.
- `runic/__init__.py` — export `SchemaManifest`, `RangeIndex`, `FulltextIndex`,
  `VectorIndex`, `UniqueConstraint`, `MandatoryConstraint`.
- `tests/test_autogen.py`, `tests/test_merge.py`, `tests/test_manifest.py`,
  `tests/test_check_command.py` — new unit test files.
- All existing tests still pass; total coverage ≥ 80 %.

---

### Success criteria

```bash
# Scaffold and autogenerate
uv run runic revision --autogenerate -m "add email index" --config runic/env.py
# Created revision: runic/versions/ae1027a6acf_add_email_index.py  [CANDIDATE — review before applying]

# Merge two branches
uv run runic merge b1a2c3d4e5f6 9f8e7d6c5b4a -m "merge person and org branches"
# Created revision: runic/versions/1234567890ab_merge_person_and_org_branches.py

# CI gate — exits 1 when schema is stale
uv run runic check --config runic/env.py
# Pending schema changes (run `runic revision --autogenerate -m "..."` to generate):
#   + op.create_range_index("Person", "email")
# (exit code 1)

# CI gate — exits 0 when up-to-date
uv run runic check --config runic/env.py
# Schema up-to-date.
# (exit code 0)

task test    # all tests pass, coverage ≥ 80 %
task lint    # no errors
task format  # clean
```

---

### Out of scope (Phase 4)

- Autogenerate for node/relationship structure (labels, properties) — not
  introspectable; out of scope by design.
- Rename detection — autogenerate sees rename as drop + create; operator must
  hand-edit to use `op.rename_property`.
- `depends_on` cross-stream ordering enforcement in the upgrade runner — the field
  is written into revision files but the runner does not reorder based on it.
- Multi-`--name` / multiple independent lineage configs (the Alembic multi-db
  analogue) — out of scope.
- `edit <rev>` command (opens revision in `$EDITOR`).
- Async (`asyncio`) client support.
- Post-gen hooks other than `ruff format` (e.g. Black, isort) — the `--format`
  flag calls `ruff format` only; generalised hook configuration is deferred.
