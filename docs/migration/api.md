# Migration API Reference

> **Note:** This is a manually-maintained API reference. For the authoritative API, read the [source on GitHub](https://github.com/jenreh/runic/tree/main/src/runic).

`runic.migrate` is the schema migration engine. For the full workflow see
[quickstart](./quickstart.md) and the CLI reference; the CLI is documented in
the operations reference.

---

## runic.migrate.Runic

`Runic` is the single class a developer needs. It combines all DB-connected
operations (`upgrade`, `downgrade`, `stamp`, `current`) with offline DAG
queries (`get_history`, `get_heads`, `create_revision`) in one coherent API.

### Constructor

```python
Runic(
    adapter: GraphAdapter,
    script_location: Path,
    *,
    preview: bool = False,
    target_manifest: SchemaManifest | None = None,
    track_checksums: bool = True,
    track_installed_by: bool = True,
    truncate_slug_length: int = 40,
    file_template: str | None = None,
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `adapter` | `GraphAdapter` | — | Database adapter that drives all graph operations. |
| `script_location` | `Path` | — | Directory that contains `env.py` and the `versions/` sub-folder. |
| `preview` | `bool` | `False` | When `True` all mutating operations are logged but not executed. |
| `target_manifest` | `SchemaManifest \| None` | `None` | Optional schema manifest used for autogenerate diff. |
| `track_checksums` | `bool` | `True` | Store and verify SHA-256 checksums for applied revision scripts. |
| `track_installed_by` | `bool` | `True` | Record the OS user or `RUNIC_INSTALLED_BY` env var alongside each applied revision. |
| `truncate_slug_length` | `int` | `40` | Maximum character length of the human-readable slug in generated file names. |
| `file_template` | `str \| None` | `None` | Custom `%(rev)s_%(slug)s`-style format string for revision file names. |

### Properties

#### `adapter`

```python
@property
def adapter(self) -> GraphAdapter: ...
```

The `GraphAdapter` this context was constructed with.

#### `target_manifest`

```python
@property
def target_manifest(self) -> SchemaManifest | None: ...
```

The optional `SchemaManifest` supplied at construction time.

#### `script_location`

```python
@property
def script_location(self) -> Path: ...
```

The root directory that contains `env.py` and `versions/`.

#### `preview_log`

```python
@property
def preview_log(self) -> list[str]: ...
```

Ordered list of preview-mode operation descriptions accumulated since the
instance was created (or since the last clear). Only populated when `preview=True`.

### DB-connected operations

#### `upgrade`

```python
def upgrade(
    self,
    target: str = "head",
    *,
    validate_on_migrate: bool = False,
    installed_by: str | None = None,
) -> None: ...
```

Apply all pending revisions up to `target`.

- `target` — a revision id, unique prefix, `"head"`, or a relative `"+N"` offset.
- `validate_on_migrate` — run `validate()` before the first script executes; raises `ValueError` on mismatch.
- `installed_by` — override the attribution string stored alongside each revision. Falls back to `RUNIC_INSTALLED_BY` env var, then the OS user.

#### `downgrade`

```python
def downgrade(self, target: str, *, force: bool = False) -> None: ...
```

Revert applied revisions down to `target`.

- `target` — a revision id, `"base"`, or a relative `"-N"` offset.
- `force` — allow downgrading through revisions marked `irreversible = True`.

Raises `IrreversibleMigrationError` when an irreversible revision is encountered and `force=False`.

#### `stamp`

```python
def stamp(self, target: str, *, purge: bool = False) -> None: ...
```

Mark the database as being at `target` **without** running any migration
scripts. Useful for baselining an existing database.

- `target` — a revision id, `"base"` (clears the version node), or `"heads"` (stamps all current head revisions).
- `purge` — clear the version node before stamping.

#### `current`

```python
def current(self) -> str | None: ...
```

Return the single revision id currently recorded in the version node, or
`None` when no revision has been applied.

#### `validate`

```python
def validate(self) -> list[str]: ...
```

Verify that each applied revision script still matches its stored checksum.
Returns a list of error strings — an empty list means all checksums are valid.
Returns `[]` immediately when `track_checksums=False`.

#### `enable_preview`

```python
def enable_preview(self) -> None: ...
```

Switch the instance into preview mode after construction. Subsequent mutating
operations are logged to `preview_log` instead of being executed.

### Offline DAG queries

These methods work purely from the revision scripts on disk; no database
connection is required.

#### `get_history`

```python
def get_history(self, range_: str | None = None) -> list[RevisionInfo]: ...
```

Return revision history, newest-first.

- `range_` — optional `"start:end"` slice (either side may be omitted to mean
  base / head respectively).

#### `get_heads`

```python
def get_heads(self) -> list[Revision]: ...
```

Return all head revisions — revisions that are not referenced as
`down_revision` by any other revision.

#### `get_branch_points`

```python
def get_branch_points(self) -> list[tuple[Revision, list[str]]]: ...
```

Return each branch-point revision paired with the revision ids of its direct
children.

#### `get_revision_message`

```python
def get_revision_message(self, rev_id: str) -> str | None: ...
```

Return the human-readable message for `rev_id`, or `None` if the revision
cannot be found.

#### `create_revision`

```python
def create_revision(
    self,
    message: str,
    head: str | None = None,
    rev_id: str | None = None,
    branch_labels: list[str] | None = None,
    depends_on: list[str] | None = None,
) -> Path: ...
```

Scaffold a new migration script under `script_location/versions/` and return
its path.

- `message` — short description used in the file name slug and stored in the script.
- `head` — parent revision id (defaults to the current `head`).
- `rev_id` — override the auto-generated 12-hex-character id.
- `branch_labels` — label strings to attach to this revision.
- `depends_on` — additional revision ids that must be applied first.

#### `show_revision`

```python
def show_revision(self, rev: str) -> Revision: ...
```

Return full metadata for a single revision identified by its id or a unique
prefix. Raises `RevisionNotFound` when no match exists.

---

## IrreversibleMigrationError

Raised by `downgrade()` when it encounters a revision that has
`irreversible = True` and `force=False` was not passed.

```python
class IrreversibleMigrationError(Exception): ...
```

---

## Programmatic usage example

```python
import logging
from pathlib import Path
from runic import Runic
from runic.migrate.adapters import create_adapter

log = logging.getLogger(__name__)

adapter = create_adapter(
    "falkordb",
    url="falkor://:mypassword@localhost:6379",
    graph_name="my_graph",
)

runic = Runic(adapter, script_location=Path("runic/"))

errors = runic.validate()
if errors:
    raise RuntimeError("\n".join(errors))

runic.upgrade("head", installed_by="deploy-bot")
log.info("current: %s", runic.current())

history = runic.get_history()
for entry in history:
    log.info("%s  %s", entry.revision, entry.message)

runic.downgrade("base")
```

---

## runic.migrate.init

```python
def init(directory: Path, *, force: bool = False) -> None: ...
```

Scaffold a new runic migration environment on disk. Creates the directory
structure (`versions/`, `env.py`, `script.py.mako`) needed by the CLI and
`Runic`.

- `directory` — root directory to initialise.
- `force` — overwrite if the directory already exists.

Raises `FileExistsError` when `directory` exists and `force=False`.

---

## runic.migrate.context

The `runic.migrate.context` module exposes a module-level singleton API that
`env.py` uses so the CLI can discover the configured context after executing
the file.

::: warning
SDK users should prefer instantiating `Runic` directly rather than using this
module-level API.
:::

### `configure`

```python
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
) -> None: ...
```

Create the module-level `Runic` singleton. Called from `env.py` before any
command runs.

### `get`

```python
def get() -> Runic: ...
```

Return the configured singleton. Raises `RuntimeError` when `configure()` has
not been called yet.

### `is_preview`

```python
def is_preview() -> bool: ...
```

Return `True` when the singleton was configured with `preview=True`.

---

## runic.migrate.adapters

### `create_adapter`

```python
def create_adapter(backend: str, **kwargs: Any) -> GraphAdapter: ...
```

Instantiate a named adapter from keyword arguments. Supported `backend`
values: `"falkordb"`, `"arcadedb"`, `"age"`, `"neo4j"`, `"memgraph"`.

Two connection variants are supported for `"falkordb"`:

**URL variant** — credentials embedded in the connection string:

```python
create_adapter(
    "falkordb", url="falkor://:mypassword@localhost:6379", graph_name="my_graph"
)
```

**Params variant** — explicit host/port/auth kwargs:

```python
create_adapter(
    "falkordb",
    host="localhost",
    port=6379,
    username="myuser",
    password="mypassword",
    graph_name="my_graph",
)
```

Raises `KeyError` for unknown backend names.

---

## runic.migrate.operations

### `GraphOperations`

Migration-script API that combines data manipulation with schema DDL, both
with preview mode support. Migration scripts receive this object as their
`ops` argument:

```python
def upgrade(ops: GraphOperations) -> None:
    ops.create_range_index("Person", "email")
    ops.rename_property("Person", "fname", "first_name")
```

Extends `DataOperations` from `runic.ogm.operations`.

#### `create_range_index`

```python
def create_range_index(self, label: str, prop: str, *, rel: bool = False) -> None: ...
```

Create a range index on `label.prop`. Pass `rel=True` for relationship labels.

#### `drop_range_index`

```python
def drop_range_index(self, label: str, prop: str, *, rel: bool = False) -> None: ...
```

Drop a range index on `label.prop`.

#### `create_fulltext_index`

```python
def create_fulltext_index(
    self,
    label: str,
    *props: str,
    language: str | None = None,
    stopwords: list[str] | None = None,
) -> None: ...
```

Create a fulltext index on `label` covering the given properties.

#### `drop_fulltext_index`

```python
def drop_fulltext_index(self, label: str, *props: str) -> None: ...
```

Drop a fulltext index.

#### `create_vector_index`

```python
def create_vector_index(
    self,
    label: str,
    prop: str,
    dimension: int,
    similarity: str,
    *,
    m: int = 16,
    ef_construction: int = 200,
    ef_runtime: int = 10,
) -> None: ...
```

Create an HNSW vector index on `label.prop`.

- `dimension` — vector length.
- `similarity` — distance metric (e.g. `"cosine"`, `"euclidean"`).
- `m`, `ef_construction`, `ef_runtime` — HNSW tuning parameters.

#### `drop_vector_index`

```python
def drop_vector_index(self, label: str, prop: str) -> None: ...
```

Drop a vector index.

#### `create_constraint`

```python
def create_constraint(
    self, kind: str, entity: str, label: str, props: list[str]
) -> None: ...
```

Create a schema constraint. `kind` is `"unique"` or `"mandatory"`; `entity`
is `"NODE"` or `"RELATIONSHIP"`.

#### `drop_constraint`

```python
def drop_constraint(
    self, kind: str, entity: str, label: str, props: list[str]
) -> None: ...
```

Drop a schema constraint.

#### `snapshot`

```python
def snapshot(self, snap_name: str) -> None: ...
```

Trigger the adapter to create a named database snapshot before a migration step.

#### `restore_snapshot`

```python
def restore_snapshot(self, snap_name: str) -> None: ...
```

Restore a previously created snapshot by name.

---

## runic.migrate.manifest

Schema manifest classes used with autogenerate. See [schema](./schema.md) for
usage examples.

### `SchemaManifest`

```python
@dataclass
class SchemaManifest:
    range_indexes: list[RangeIndex] = field(default_factory=list)
    fulltext_indexes: list[FulltextIndex] = field(default_factory=list)
    vector_indexes: list[VectorIndex] = field(default_factory=list)
    constraints: list[UniqueConstraint | MandatoryConstraint] = field(default_factory=list)
```

Describes the desired schema state passed to `Runic` as `target_manifest` for
autogenerate diffing.

### `RangeIndex`

```python
@dataclass(frozen=True)
class RangeIndex:
    label: str
    prop: str
    rel: bool = False
```

Represents a range index on a node or relationship property.

### `FulltextIndex`

```python
@dataclass(frozen=True)
class FulltextIndex:
    label: str
    props: tuple[str, ...]
    language: str | None = None
    stopwords: tuple[str, ...] | None = None
```

Represents a fulltext index with optional language and stopword configuration.

### `VectorIndex`

```python
@dataclass(frozen=True)
class VectorIndex:
    label: str
    prop: str
    dimension: int
    similarity: str
    m: int = 16
    ef_construction: int = 200
    ef_runtime: int = 10
```

Represents an HNSW vector index with its tuning parameters.

### `UniqueConstraint`

```python
@dataclass(frozen=True)
class UniqueConstraint:
    entity: str  # "NODE" | "RELATIONSHIP"
    label: str
    props: tuple[str, ...]
```

Represents a uniqueness constraint on one or more properties.

### `MandatoryConstraint`

```python
@dataclass(frozen=True)
class MandatoryConstraint:
    entity: str  # "NODE" | "RELATIONSHIP"
    label: str
    props: tuple[str, ...]
```

Represents a mandatory (non-null) constraint on one or more properties.

---

## runic.migrate.script

Internal revision DAG types returned by methods on `Runic`; rarely
constructed directly.

### `Revision`

```python
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
    module: Any
```

Full metadata for a single revision script loaded from disk.

### `RevisionInfo`

```python
@dataclass
class RevisionInfo:
    revision: str
    down_revision: str | tuple[str, ...] | None
    message: str
    create_date: datetime
    is_head: bool
    is_branch_point: bool
```

Lightweight summary returned by `Runic.get_history()`.

### `RevisionNotFound`

Raised when a revision id or prefix does not match any script on disk.

```python
class RevisionNotFound(Exception): ...
```

### `AmbiguousRevision`

Raised when a short prefix matches more than one revision id.

```python
class AmbiguousRevision(Exception): ...
```

---

## runic.migrate.exceptions — Migration Exceptions

### `MultipleHeadsError`

Raised when an operation that requires a single head (e.g. `upgrade("head")`)
encounters more than one head revision in the DAG.

```python
class MultipleHeadsError(Exception): ...
```

### `MultipleBasesError`

Raised when the revision DAG contains more than one root revision
(`down_revision = None`).

```python
class MultipleBasesError(Exception): ...
```

### `ConstraintFailedError`

Raised when a schema constraint check fails during migration execution.

```python
class ConstraintFailedError(Exception): ...
```

### `ConstraintTimeoutError`

Raised when waiting for a constraint to become consistent exceeds the allowed
timeout.

```python
class ConstraintTimeoutError(Exception): ...
```

---

## runic.migrate.testing

Pytest fixtures for integration tests. Requires `falkordblite` (`pip install falkordblite`).

### `falkordb_graph`

```python
@pytest.fixture
def falkordb_graph(falkordb_server: Any) -> Any: ...
```

Yield a `(db, graph)` tuple backed by a shared session-scoped
`redislite.FalkorDB` server. Each invocation uses a unique graph name so
tests are fully isolated. The graph is deleted on teardown.

### `runic_context`

```python
@pytest.fixture
def runic_context(falkordb_graph: Any, tmp_path: Path) -> Any: ...
```

Yield a configured `Runic` instance backed by an ephemeral falkordblite
graph and a temporary `script_location` on disk. Ready for use in migration
integration tests.
