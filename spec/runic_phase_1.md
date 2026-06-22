# FalkorMigrate — Claude Code Prompts (Phase 1)

---

## Phase 1 — Revision Graph, History & Inspection

### Task

Extend the `falkormigrate` package built in Phase 0 with the full revision DAG,
multi-head support, and the five read/management CLI commands: `history`, `heads`,
`branches`, `stamp`, `show`. After Phase 1 the framework supports non-linear history
inspection, database baselining without running migrations, and the full set of CLI
commands needed for day-to-day operation.

This phase is purely additive — no Phase 0 behaviour changes except where explicitly
noted below.

---

### Context

All Phase 0 context applies unchanged. Key additions:

**Multi-head state:** `VersionNode` currently stores a single `revision` string.
Phase 1 must extend storage to a **list** property `revisions: list[str]` while
remaining backward-compatible with existing single-revision nodes (reading a string
property and coercing to a list).

**DAG model:** The revision graph is a directed acyclic graph where each `Revision` node
has zero or one parent (`down_revision: str | None`) or, for a merge revision, a
**tuple** of parents. A head is any revision that is not the `down_revision` of any
other. The base has `down_revision = None`. A branch-point is any revision that is the
`down_revision` of two or more scripts.

**`stamp` semantics:** Sets `VersionNode` to the requested revision(s) **without**
running any `upgrade()` or `downgrade()`. Used to baseline an existing DB, fix a
corrupted version pointer, or mark "head" after manual ops. `stamp base` clears the
pointer.

---

### Requirements

**1. Extend `Revision` dataclass (`script.py`)**

- Change `down_revision: str | None` to `down_revision: str | tuple[str, ...] | None`.
- Add `branch_labels: list[str]` (already scaffolded, now used in DAG methods).

**2. Extend `ScriptDirectory` (`script.py`)**

Add or rewrite these methods:

- `get_heads() -> list[Revision]` — all revisions not referenced as `down_revision` by
  any other. Sorted by `create_date` descending.

- `get_base() -> Revision` — revision with `down_revision is None`. Raises
  `MultipleBasesError` if there is more than one (not supported in Phase 1 — only a
  single base is allowed).

- `get_branch_points() -> list[Revision]` — revisions that appear as `down_revision` in
  two or more scripts.

- `walk_revisions(start: str | None, end: str | None,
                  direction: Literal["up","down"]) -> Iterator[Revision]`
  — generalize `iterate_revisions` from Phase 0; yield revisions in application order
  between `start` (exclusive) and `end` (inclusive). Both `None` values are valid
  (`start=None` → walk from base; `end=None` → walk to head). Raises
  `MultipleHeadsError` when direction is `"up"` and there is more than one head and
  `end` is not specified.

- `revision_history(verbose: bool = False) -> list[RevisionInfo]` — full chronological
  list; `RevisionInfo` is a dataclass with `revision`, `down_revision`, `message`,
  `create_date`, `is_head: bool`, `is_branch_point: bool`.

- `get_revision(rev_id: str) -> Revision` — now also accepts the special symbols
  `"head"` (single head only), `"base"`, `"heads"` (returns all heads as a list — only
  valid in `stamp`). Raises `MultipleHeadsError` when `"head"` is used and there are
  multiple heads.

**3. Extend `VersionNode` (`version.py`)**

- Store revisions as a list property: `SET v.revisions = $revisions` (list of strings).
- `get() -> list[str]` — returns the current revision list (empty list if unset).
- `get_single() -> str | None` — convenience; raises `MultipleHeadsError` if list has
  > 1 entry (used by `current` display).
- `set(revision: str) -> None` — replaces list with `[revision]`.
- `set_multiple(revisions: list[str]) -> None` — sets the full list (for `stamp heads`
  after a future merge).
- `clear() -> None` — sets `revisions = []`.
- Backward-compatible: if the node has an old `revision` string property (Phase 0
  node), read it and migrate to `revisions` list on first write.

**4. Extend `MigrationContext` (`context.py`)**

- `upgrade()` and `downgrade()` must now check for multiple heads using
  `ScriptDirectory.get_heads()`; raise `MultipleHeadsError` with a clear message
  ("Multiple heads detected — run `falkormigrate heads` to inspect. Use `merge` to
  resolve or specify an explicit target revision.") when target is `"head"` and multiple
  heads exist.
- `stamp(target: str, purge: bool = False) -> None`:
  - `target = "base"` → `VersionNode.clear()`.
  - `target = "heads"` → `VersionNode.set_multiple([r.revision for r in get_heads()])`.
  - `target = "<rev>"` → `VersionNode.set(resolved_revision_id)`.
  - `purge=True` → clear the version node first, then stamp.
  - Does **not** run any migration scripts.

**5. New CLI commands (`cli.py`)**

- **`history`** — print all revisions chronologically (oldest → newest).
  Options: `--verbose` (include `create_date`, `down_revision`, branch labels);
  `--indicate-current` (mark the currently-stamped revision with `(current)`);
  `--range <start>:<end>` (inclusive rev range).
  Format example (non-verbose):

  ```
  ae1027a6acf  (head) add email index
  1975ea83b712         initial schema
  ```

- **`heads`** — print all head revisions (one per line with id and message). If there
  is exactly one head, suffix with `(single head)`. If multiple, suffix with
  `(MULTIPLE HEADS — use merge to resolve)`.

- **`branches`** — print all branch-point revisions (revisions with two or more
  dependent scripts). Each line: `<rev_id>  <message>  [<child1>, <child2>]`.

- **`stamp <target>`** — sets version pointer without running migrations.
  Options: `--purge` (clear before stamping); `--ini <path>`.
  Accepts `base`, `heads`, or any revision id / prefix.

- **`show <rev>`** — print full metadata for a single revision:
  revision id, `down_revision`, message, create date, `irreversible`, `snapshot`,
  `branch_labels`, `depends_on`, and the resolved file path.

**6. Tests**

Add to the test suite (do not modify passing Phase 0 tests):

- `test_script_dag.py`:
  - `get_heads()` returns single head on linear chain.
  - `get_heads()` returns two heads when two scripts share the same `down_revision`.
  - `get_branch_points()` returns the shared parent.
  - `walk_revisions` up and down on a 3-revision linear chain.
  - `walk_revisions` up raises `MultipleHeadsError` when target is `"head"` and two
    heads exist.
  - Prefix lookup via `get_revision()` still works.

- `test_version_multihead.py`:
  - `get()` returns empty list on fresh node.
  - `set_multiple` stores and retrieves two revisions.
  - `get_single()` raises `MultipleHeadsError` when two revisions stored.
  - Backward-compat: node with old `revision` string property is transparently read as
    single-element list.

- `test_context_stamp.py`:
  - `stamp("base")` calls `VersionNode.clear()` with no migration calls.
  - `stamp("heads")` calls `VersionNode.set_multiple()`.
  - `stamp` with an unknown revision raises `RevisionNotFound`.
  - `upgrade` raises `MultipleHeadsError` when two heads exist and target is `"head"`.

- `test_cli_phase1.py` (using `typer.testing.CliRunner`):
  - `history` output contains both revisions in order, with `(current)` marker.
  - `heads` output contains the head revision id.
  - `show <rev>` output includes `Revision ID:`, `Revises:`, `Message:`.
  - `stamp base` exits 0 and calls no migration functions.

---

### Deliverables

- All Phase 1 modules updated (`script.py`, `version.py`, `context.py`, `cli.py`).
- Five new CLI commands fully functional.
- Full test suite passing (Phase 0 + Phase 1 tests) with ≥ 80 % coverage.
- `README.md` updated with `history`, `heads`, `stamp`, `show` usage examples.

---

### Success criteria

```bash
# Assume two chained migration files exist in versions/

uv run falkormigrate history --indicate-current
# ae1027a6acf  (head) (current)  add email index
# 1975ea83b712                   initial schema

uv run falkormigrate heads
# ae1027a6acf  add email index  (single head)

uv run falkormigrate show ae1027
# Revision ID: ae1027a6acf
# Revises:     1975ea83b712
# Message:     add email index
# ...

uv run falkormigrate stamp base
# Stamped: <none>

uv run falkormigrate current
# <none>

task test     # all tests pass, coverage ≥ 80%
task lint     # no lint errors
```

---

### Out of scope (Phase 1)

- `merge` command and merge revisions (tuple `down_revision`) — those exist in the
  datamodel but the `merge` CLI command ships in Phase 4.
- Full-text / vector / rename-property `op.*` helpers.
- `snapshot=True` / `GRAPH.COPY` wiring.
- Live integration tests (all tests remain mocked).
- Autogenerate.
- Async client support.
