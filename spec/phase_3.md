# FalkorMigrate — Claude Code Prompts (Phase 3)

---

## Phase 3 — Testing Harness & Snapshot Rollback

### Task

Add first-class testability and safe rollback to `runic`. Concretely:

1. **Snapshot wiring** — honour the `snapshot = True` flag on `Revision` by calling
   `GRAPH.COPY` before `upgrade()` and auto-restoring on failure. Expose two new
   `op` methods (`snapshot` / `restore_snapshot`) for manual use inside migration
   scripts.
2. **`runic test <rev>`** CLI command — applies `upgrade()`, `downgrade()`, then
   `upgrade()` again on an ephemeral graph and asserts round-trip parity
   (entity counts, index counts, constraint counts). Reports idempotency pass/fail.
3. **Pytest plugin / fixture** — a `runic.testing` module that provides an
   `ephemeral_graph` pytest fixture backed by `falkordblite` (embedded FalkorDB,
   no external server required) with automatic teardown.
4. **Integration tests** — real (non-mocked) tests using `falkordblite` covering
   upgrade/downgrade round-trip, idempotency, and snapshot auto-restore.

After Phase 3 the framework delivers the safety contract described in the concept
document: "stamp-after-success, idempotency, and optional snapshots."

---

### Context

**What is already implemented (Phases 0–2):**

- `runic/script.py` — `Revision` dataclass (fields include `snapshot: bool`),
  `ScriptDirectory` (DAG, `iterate_revisions`, `get_heads`, `get_branch_points`,
  `walk_revisions`, `revision_history`).
- `runic/version.py` — `VersionNode` with `get() → list[str]`, `set`,
  `set_multiple`, `clear`.
- `runic/context.py` — `MigrationContext` with `upgrade`, `downgrade`, `stamp`,
  `current`; module-level `configure` / `get` / `is_preview` singleton API;
  `IrreversibleMigrationError`.
- `runic/operations.py` — `GraphOperations` with: `run_cypher`, `run_command`,
  `create_range_index`, `drop_range_index`, `create_constraint` (polls to
  `OPERATIONAL`), `drop_constraint`, `create_fulltext_index`, `drop_fulltext_index`,
  `create_vector_index`, `drop_vector_index`, `rename_property`, `relabel_nodes`,
  `seed`. Module-level `op` proxy.
- `runic/exceptions.py` — `MultipleHeadsError`, `MultipleBasesError`.
- `runic/cli.py` — `init`, `revision`, `upgrade`, `downgrade`, `current`,
  `history`, `heads`, `branches`, `stamp`, `show`.

**Snapshot naming convention:** `{graph_name}__premig_{rev_id}` — e.g. for graph
`social` and revision `ae1027a6acf`, the snapshot graph is
`social__premig_ae1027a6acf`. A snapshot name must never match any user graph.

**`GRAPH.COPY` semantics (from `falkordb-py`):** `graph.copy(new_name: str)` creates
a full copy of the source graph including indexes and constraints; the source graph
remains fully accessible during the copy. To restore, copy the snapshot back and then
delete the snapshot.

**`falkordblite` (embedded FalkorDB for CI):** The package `falkordblite` (PyPI,
current `0.10.0`) provides an embedded FalkorDB instance — no external server
required. Per the FalkorDB docs it is the recommended CI backend. Verify the exact
constructor / URL API against the installed package before coding: the client surface
may differ slightly from `falkordb`. A pattern like
`FalkorDB(host="localhost", port=6379)` or a context manager that starts an in-process
instance is expected, but **confirm against the live package** rather than guessing.

**`graph.name` / graph identifier:** The `falkordb-py` `Graph` object returned by
`db.select_graph(name)` exposes its name. Confirm the attribute (`graph.name` or
`graph.graph_name`) against the installed version before using it in snapshot naming.

---

### Requirements

**1. `GraphOperations` — snapshot / restore (`operations.py`)**

Add two new methods:

```python
def snapshot(self, snap_name: str) -> None: ...
def restore_snapshot(self, snap_name: str) -> None: ...
```

- `snapshot(snap_name)` — calls `self._graph.copy(snap_name)`; in preview mode logs
  `SNAPSHOT: copy {graph_name} → {snap_name}` and returns.
- `restore_snapshot(snap_name)` — copies the snapshot back over the live graph and
  then deletes the snapshot:
  1. `snap_graph = self._db.select_graph(snap_name)`
  2. `snap_graph.copy(graph_name)` — overwrites the live graph data.
  3. `snap_graph.delete()` — removes the snapshot.
  In preview mode logs `RESTORE SNAPSHOT: {snap_name} → {graph_name}` and returns.

Both methods need `_graph.name` (or equivalent) to derive `graph_name`. Confirm the
correct attribute name from the installed `falkordb` package.

**2. `MigrationContext.upgrade()` — snapshot-before / restore-on-fail (`context.py`)**

When `rev.snapshot is True` for any revision about to be applied:

1. Before calling `rev.module.upgrade(self._ops)`, call
   `self._ops.snapshot(snap_name)` where
   `snap_name = f"{self._graph_name}__premig_{rev.revision}"`.
   Skip in preview mode.
2. If `rev.module.upgrade(self._ops)` raises, call
   `self._ops.restore_snapshot(snap_name)` before re-raising the exception.
   Log the restore at `WARNING` level.
3. On success do **not** delete the snapshot automatically — leave it for the
   operator to inspect or for `downgrade()` to use.

`MigrationContext` must derive `_graph_name` from the graph object (confirmed
attribute). Store it as `self._graph_name` set in `__init__`.

**3. `MigrationContext.downgrade()` — snapshot restore (`context.py`)**

After `rev.module.downgrade(self._ops)` completes successfully for a revision where
`rev.snapshot is True`:

- Check whether the snapshot graph `{graph_name}__premig_{rev.revision}` exists
  (query `self._db.list_graphs()` or equivalent).
- If it exists, restore it via `self._ops.restore_snapshot(snap_name)` **instead of**
  running the Cypher `downgrade()` operations, and log at `INFO` level:
  `"restoring snapshot for revision %s"`.
- If it does not exist, run `downgrade()` as normal (explicit downgrade code is still
  required — snapshot is the *fast path*, not a substitute for a written `downgrade()`).

**4. New module `runic/testing.py` — pytest fixtures**

Create `runic/testing.py` with:

```python
import pytest

@pytest.fixture
def falkordb_graph():
    """Yield (db, graph) backed by falkordblite; tears down after the test."""
    ...
```

Requirements:

- Imports `falkordblite` (not `falkordb`) — use the embedded client.
- Generates a unique graph name per test: `f"test_{secrets.token_hex(6)}"`.
- Yields `(db, graph)` where `graph = db.select_graph(graph_name)`.
- In teardown: `graph.delete()` (swallow `Exception` to avoid masking test failures).
- A second fixture `runic_context(falkordb_graph, tmp_path)` yields a configured
  `MigrationContext` with `script_location=tmp_path / "runic"` and calls
  `configure(db, graph, script_location=...)`.
- Module must be importable without `falkordblite` installed (guard with
  `try: import falkordblite` + a clear `pytest.skip` or `ImportError`).

**5. New CLI command `runic test <rev>` (`cli.py`)**

```
runic test <rev> [--config PATH] [--url URL] [--graph GRAPH]
```

Behaviour:

1. Connect to FalkorDB (from config or `--url` / `--graph` flags).
2. Create an ephemeral test graph: `{graph_name}__test_{rev}_{token}`.
3. Load `ScriptDirectory`; resolve `<rev>` to a `Revision`.
4. **Phase A — upgrade:** run `MigrationContext.upgrade(target=rev)` on the ephemeral
   graph. Capture entity count, index count, constraint count after.
5. **Phase B — downgrade:** run `MigrationContext.downgrade(target="base")` on the
   same graph. Capture counts after.
6. **Phase C — idempotency:** re-run `upgrade(target=rev)`. Capture counts.
7. Print a report:

   ```
   runic test ae1027a6acf
   ─────────────────────
   Phase A (upgrade):    ✓  nodes=42  indices=3  constraints=1
   Phase B (downgrade):  ✓  nodes=0   indices=0  constraints=0
   Phase C (idempotency):✓  nodes=42  indices=3  constraints=1
   ─────────────────────
   PASSED
   ```

8. Exit 0 on all phases passing, non-zero on any failure.
9. Always delete the ephemeral test graph in a `finally` block.

Implement the count helpers as private functions: `_entity_count(graph)`,
`_index_count(graph)`, `_constraint_count(graph)` using `MATCH (n) RETURN count(n)`,
`CALL db.indexes() YIELD * RETURN count(*) AS c`, and `CALL db.constraints() YIELD *
RETURN count(*) AS c`. Exclude `_FalkorMigrateVersion` nodes from `_entity_count`.

**6. Integration tests (`tests/test_integration.py`)**

These tests use `falkordblite` (real FalkorDB, not mocked). Guard the entire module
with:

```python
pytest.importorskip("falkordblite", reason="falkordblite not installed")
```

Tests to include (each uses the `falkordb_graph` fixture from `runic.testing`):

- `test_upgrade_downgrade_round_trip` — create two migration scripts (one adding a
  range index, one adding a node property). Run `upgrade("head")`, assert index
  present. Run `downgrade("base")`, assert index absent and entity count 0.
- `test_idempotency` — run `upgrade("head")` twice; assert second run is a no-op
  (entity/index counts identical to first run).
- `test_snapshot_auto_restore_on_failure` — create a revision with `snapshot = True`
  whose `upgrade()` adds one node then raises `RuntimeError`. Assert that after the
  failure the graph has zero nodes (snapshot was restored). Verify the snapshot graph
  was cleaned up (deleted) on successful restore.
- `test_snapshot_downgrade_uses_snapshot` — create a revision with `snapshot = True`,
  run `upgrade()`, confirm snapshot graph exists. Run `downgrade("base")`, confirm
  snapshot graph is deleted and entity count is 0.
- `test_irreversible_raises` — create a revision with `irreversible = True`, run
  `upgrade()`, then assert `IrreversibleMigrationError` is raised on `downgrade()`;
  pass `force=True` to confirm it proceeds.

Tests must be tagged with `@pytest.mark.integration` so they can be excluded in CI
without `falkordblite` by running `pytest -m "not integration"`.

**7. Unit tests for snapshot wiring (`tests/test_snapshot.py`)**

These tests mock `GraphOperations` and `VersionNode` as in prior phases.

- `test_upgrade_calls_snapshot_when_flag_set` — `rev.snapshot = True`; assert
  `ops.snapshot()` is called with `"{graph_name}__premig_{rev_id}"` before
  `rev.module.upgrade()`.
- `test_upgrade_restores_snapshot_on_failure` — `rev.snapshot = True`; make
  `rev.module.upgrade()` raise; assert `ops.restore_snapshot()` is called.
- `test_upgrade_no_snapshot_when_flag_false` — `rev.snapshot = False`; assert
  `ops.snapshot()` is **not** called.
- `test_downgrade_uses_snapshot_when_exists` — `rev.snapshot = True`; snapshot graph
  present in `db.list_graphs()`; assert `ops.restore_snapshot()` is called instead of
  `rev.module.downgrade()`.
- `test_downgrade_fallback_when_no_snapshot` — `rev.snapshot = True` but no snapshot
  graph; assert `rev.module.downgrade()` is called normally.

---

### Deliverables

- `runic/operations.py` — `snapshot()` and `restore_snapshot()` added to
  `GraphOperations`.
- `runic/context.py` — `MigrationContext.__init__` stores `_graph_name`;
  `upgrade()` and `downgrade()` wired with snapshot logic.
- `runic/testing.py` — new module with `falkordb_graph` and `runic_context` fixtures.
- `runic/cli.py` — `test` command added.
- `tests/test_snapshot.py` — new unit tests (mocked).
- `tests/test_integration.py` — new integration tests (falkordblite).
- All existing tests still pass; total coverage ≥ 80 %.
- `falkordblite` added as an optional dev dependency (`uv add --optional dev falkordblite`
  or `uv add falkordblite` — whichever fits the project's existing dependency layout).

---

### Success criteria

```bash
# Unit tests (mocked) pass
task test

# Integration tests pass with falkordblite installed
uv run pytest tests/test_integration.py -v -m integration

# test command on a real graph
uv run runic test ae1027a6acf --url falkor://localhost:6379 --graph social
# Phase A (upgrade):    ✓  nodes=42  indices=3  constraints=1
# Phase B (downgrade):  ✓  nodes=0   indices=0  constraints=0
# Phase C (idempotency):✓  nodes=42  indices=3  constraints=1
# PASSED

task lint    # no errors
task format  # clean
```

---

### Out of scope (Phase 3)

- Autogenerate (`revision --autogenerate`, `check`) — Phase 4.
- `merge` CLI command and multi-base handling — Phase 4.
- Snapshot progress reporting for large graphs (>1 M nodes).
- Async (`asyncio`) client support.
- Docker-based integration test infra — `falkordblite` is sufficient; Docker is the
  documented alternative but not required for this phase.
- `op.snapshot()` / `op.restore_snapshot()` called manually from user migration
  scripts are supported (they call the same `GraphOperations` methods) but
  documentation and examples are out of scope here.
