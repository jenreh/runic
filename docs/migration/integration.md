# OGM and Migrations

This guide explains how `runic.ogm` models and `runic.migrate` migrations
fit together across the full lifecycle of a project — from the first day of
development through to a production schema under version control.

::: info See also
[examples/migrate/](https://github.com/jenreh/runic/tree/main/examples/migrate)
— Runnable migration examples referenced throughout this page.
:::

---

## How schema management evolves

Schema management in runic follows three distinct stages as a project matures:

| Stage | When | Approach |
|-------|------|----------|
| **1** | Early development, schema changing rapidly | `SchemaManager.sync_schema()` — reads your OGM models and creates indexes instantly, no migration file needed |
| **2** | Schema stabilises, ready for version control | `runic baseline` — introspects the live graph and generates the root migration file |
| **3** | Any schema change going forward | Hand-written revision files; `runic check` gates CI on drift |

---

## Stage 1 — Development bootstrap

`SchemaManager` reads index declarations directly from OGM `Field` annotations
and issues the required DDL. Use it in a one-off bootstrap script so your local
dev graph is up to speed instantly, without writing a migration:

```python
# scripts/bootstrap_schema.py — run once per dev environment
from runic.migrate import SchemaManager, create_adapter
from myapp.models import User, Post, Article, KnowsEdge

adapter = create_adapter(
    "falkordb",
    url="falkor://localhost:6379",
    graph_name="myapp_dev",
)
schema = SchemaManager(adapter)

# Creates all indexes declared on your models
schema.sync_schema([User, Post, Article, KnowsEdge])

# Check what ended up in the graph
print(schema.get_schema_diff([User, Post, Article, KnowsEdge]))
```

`sync_schema` skips specs that already exist, so it is safe to call repeatedly.

**What it reads** — the `SchemaManager` walks every `Node`/`Edge` subclass
you pass and translates each `Field` annotation into a DDL call:

```python
from runic.ogm import Node, Field

class User(Node, labels=["User"]):
    id: str = Field(primary_key=True)
    email: str = Field(unique=True)          # UNIQUE constraint + RANGE index
    name: str = Field(index=True)            # RANGE index
    bio: str = Field(index_type="FULLTEXT")  # FULLTEXT index
    embedding: list[float] = Field(index_type="VECTOR", default=None)
```

::: tip
Use `SchemaManager` for development and CI bootstrap. For production
deployments, prefer versioned migrations.
:::

---

## Stage 2 — Baseline an existing graph

Once the schema is stable and ready for version control, run `runic baseline`.
It introspects the live graph, writes a root migration file with
`down_revision = None`, and stamps the version node so runic treats it as
already applied:

```bash
# Scaffold the runic directory if not done yet
runic init

# Introspect the live graph, generate the initial migration, and stamp it
runic baseline -m "initial schema"

# View the generated file
runic show <rev_id>
```

After running, `runic baseline` prints a ready-to-paste `SchemaManifest`
block for your `env.py`:

```python
# Paste into env.py — enables runic revision --autogenerate
from runic.migrate.manifest import RangeIndex, UniqueConstraint, SchemaManifest

target_manifest = SchemaManifest(
    range_indexes=[
        RangeIndex(label="User", prop="email"),
        RangeIndex(label="User", prop="name"),
    ],
    fulltext_indexes=[],
    vector_indexes=[],
    constraints=[
        UniqueConstraint(entity="NODE", label="User", props=["email"]),
    ],
)
```

Add `target_manifest=target_manifest` to your `context.configure(...)` call
to enable `runic revision --autogenerate` going forward.

::: info
The baseline generator uses `dimension=0` as a placeholder for vector
indexes — replace with the real dimension value before committing.
:::

---

## Stage 3 — Explicit versioned migrations

From this point on, every schema change gets a hand-written revision:

```bash
runic revision -m "add Article fulltext index"
# edit the generated file
runic upgrade head
```

Use `runic revision --autogenerate -m "..."` when `target_manifest` is set
in `env.py` — runic diffs the manifest against the live schema and emits
candidate `op.*` calls. Always review before applying.

Use `runic check` in CI to gate deployments when the live schema diverges from
the manifest:

```yaml
# .github/workflows/ci.yml (example)
- name: Check schema drift
  run: runic check   # exits non-zero when live schema ≠ manifest
```

---

## Revision file anatomy

When you run `runic revision -m "some message"`, runic generates a Python file
in `runic/versions/`:

```python
"""add person email index

Revision ID: 3f9a12c1ab4e
Revises: None
Create Date: 2026-05-30T09:00:00+00:00
"""
from datetime import UTC, datetime

message = "add person email index"
create_date = datetime.fromisoformat("2026-05-30T09:00:00+00:00")

revision = "3f9a12c1ab4e"
down_revision = None        # None = root of the chain
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    pass


def downgrade(op) -> None:
    pass
```

The module-level variables are the revision's metadata:

`revision`
: Unique 12-character hex ID, auto-generated by `runic revision`.

`down_revision`
: The revision ID this one builds on top of. `None` means this is the
first revision. For merge revisions it is a tuple of two IDs.

`branch_labels`
: Optional list of symbolic names for this branch (e.g. `["feature-x"]`).

`depends_on`
: Additional revisions that must be applied before this one, across
independent branches.

`irreversible`
: Set to `True` to prevent `runic downgrade` from running
`downgrade(op)` on this revision without `--force`. Use it for
changes that delete data permanently.

`snapshot`
: Set to `True` to tell runic to take a full graph snapshot (via
`GRAPH.COPY`) before applying `upgrade(op)`. On failure the snapshot
is restored automatically.

### The `upgrade` and `downgrade` functions

Both functions receive a single argument `op` — a `GraphOperations` instance
— that exposes all supported schema operations.

```python
def upgrade(op) -> None:
    op.create_range_index("Person", "email")
    # UNIQUE constraints also need a backing range index
    op.create_constraint("UNIQUE", "NODE", "Person", ["email"])

def downgrade(op) -> None:
    # Drop constraints BEFORE their backing indexes
    op.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    op.drop_range_index("Person", "email")
```

::: tip
Always write `downgrade` when you write `upgrade`. Even if you never
expect to roll back, having a working `downgrade` lets you use
`runic test` for round-trip validation.
:::

### Marking a revision irreversible

For destructive changes (dropping a label, deleting nodes), set
`irreversible = True`:

```python
revision = "e1a2b3c4"
irreversible = True

def upgrade(op) -> None:
    op.run_cypher("MATCH (n:LegacyUser) DETACH DELETE n")

def downgrade(op) -> None:
    pass   # cannot recreate deleted data
```

Attempting to downgrade past this revision without `--force` raises
`IrreversibleMigrationError`.

### Enabling snapshots

For risky migrations on production data, set `snapshot = True`:

```python
snapshot = True

def upgrade(op) -> None:
    op.relabel_nodes("User", "Person")
```

runic calls `GRAPH.COPY` before running `upgrade(op)`. If the upgrade
raises an exception the snapshot is restored automatically.

::: warning
Snapshots copy the entire graph and can be expensive for large graphs.
:::

### Chaining revisions

Each new revision that `runic revision` generates sets `down_revision` to
the current head automatically:

```bash
$ runic revision -m "add email fulltext index"
Created revision: runic/versions/7b3d9e2f_add_email_fulltext_index.py
```

The new file will contain:

```python
revision = "7b3d9e2f"
down_revision = "3f9a12c1ab4e"   # points back to the previous revision
```

Linear history chain:

```text
None ← 3f9a12c1ab4e ← 7b3d9e2f  (head)
```

---

## Applying and rolling back

### How runic tracks state

runic stores the current revision inside your graph as a special node with
label `_FalkorMigrateVersion`. The node holds a `revisions` list property.
No external file or table is involved — the version travels with the graph.

- **Delete the graph → lose the version pointer.** Stamp the new graph with
  `runic stamp` before running migrations on it.
- **Copy the graph → copy the version pointer.** A copied graph already knows
  which revision it is at.

### Basic upgrade

```bash
# Apply all pending revisions up to head
runic upgrade

# Apply up to a specific revision
runic upgrade 3f9a12c1

# Apply the next N revisions only
runic upgrade +2
```

### Basic downgrade

```bash
# Revert to a specific revision
runic downgrade 3f9a12c1

# Revert all the way to no revisions applied
runic downgrade base

# Undo the last N revisions
runic downgrade -1
```

### Preview before executing

`--preview` prints every operation that *would* be executed without touching
the database. The version node is not stamped:

```bash
$ runic upgrade --preview
CREATE RANGE INDEX: CREATE INDEX FOR (n:Person) ON (n.email) params=None
CREATE CONSTRAINT: UNIQUE NODE Person ['email']

$ runic current
<none>   # version node unchanged
```

### The `stamp` command

`stamp` sets the version pointer *without* running any migration code.
Useful when adopting runic on an existing graph:

```bash
runic stamp 3f9a12c1       # mark graph as already at this revision
runic stamp base           # reset version to "no revision applied"
runic stamp heads          # stamp all current heads at once
```

---

## Inspecting history

### `runic history`

Print all revisions, newest first:

```bash
$ runic history
7b3d9e2f         (head)                add email fulltext index
3f9a12c1                               add person email index
```

### `runic current`

Print the currently applied revision (requires a database connection):

```bash
$ runic current
7b3d9e2f — add email fulltext index
```

### `runic heads`

Print all head revisions — revisions that no other revision points back to.
When there are multiple heads, `runic upgrade head` will refuse to run:

```bash
# Multiple heads — must merge or specify explicit ID
$ runic heads
c1d2e3f4  add vector index      (MULTIPLE HEADS — use merge to resolve)
7b3d9e2f  add email fulltext    (MULTIPLE HEADS — use merge to resolve)
```

### `runic show`

Print full metadata for a single revision:

```bash
$ runic show 3f9a12c1
Revision ID:   3f9a12c1ab4e
Revises:       <base>
Message:       add person email index
Irreversible:  False
Snapshot:      False
```

---

## Field annotation → `op.*` translation

When writing migrations by hand, translate each OGM `Field()` annotation into
the corresponding `op.*` call:

| OGM Field annotation | `upgrade` call(s) | `downgrade` call(s) |
|----------------------|-------------------|---------------------|
| `Field(index=True)` | `create_range_index(label, prop)` | `drop_range_index(label, prop)` |
| `Field(unique=True)` | `create_range_index(...)` then `create_constraint("UNIQUE", "NODE", label, [prop])` | `drop_constraint("UNIQUE", ...)` then `drop_range_index(...)` |
| `Field(index_type="FULLTEXT")` | `create_fulltext_index(label, *props)` | `drop_fulltext_index(label, *props)` |
| `Field(index_type="VECTOR")` | `create_vector_index(label, prop, dim, sim)` | `drop_vector_index(label, prop)` |
| No index annotation | *(no op.\* call needed)* | — |

---

## Ordering rules

The order of `op.*` calls within `upgrade` and `downgrade` matters.

::: danger
**Upgrade** — create indexes **before** constraints. `UNIQUE` constraints
require a backing range index to already exist.

**Downgrade** — drop constraints **before** their backing indexes.

**Relabelling** — when relabelling nodes, always relabel **before** creating
indexes on the new label.
:::

| Operation pair | Upgrade order | Downgrade order |
|----------------|---------------|-----------------|
| Indexes vs constraints | indexes **first** | constraints **first** |
| Multiple indexes | any order | any order |
| Relabel then index on new label | relabel **first** | drop index **first** |
| Data migration vs schema | data ops **last** | data ops **first** |

---

## Common migration patterns

### Pattern 1 — Initial migration

The root migration has `down_revision = None`. Create all indexes first,
then constraints.

```python
revision = "a1b2c3d4e5f6"
down_revision = None          # root — no parent
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    # Indexes first
    op.create_range_index("User", "created_at")
    op.create_range_index("User", "email")
    # UNIQUE constraint after backing range index
    op.create_constraint("UNIQUE", "NODE", "User", ["email"])

    op.create_fulltext_index("Post", "title", "body", language="english")
    op.create_range_index("Post", "published_at")
    op.create_vector_index("Product", "embedding", 256, "cosine")


def downgrade(op) -> None:
    # Constraints first
    op.drop_constraint("UNIQUE", "NODE", "User", ["email"])
    op.drop_range_index("User", "email")
    op.drop_range_index("User", "created_at")
    op.drop_fulltext_index("Post", "title", "body")
    op.drop_range_index("Post", "published_at")
    op.drop_vector_index("Product", "embedding")
```

### Pattern 2 — Baseline-generated migration

`runic baseline -m 'baseline'` produces a file like this. The upgrade body
is the full live schema; downgrade reverses it in constraint-before-index order.

```python
revision = "ba5el1ne0000"
down_revision = None


def upgrade(op) -> None:
    # Introspected from live graph — indexes first, then constraints
    op.create_range_index("User", "created_at")
    op.create_range_index("User", "email")
    op.create_fulltext_index("Post", "title", "body")
    op.create_range_index("Post", "published_at")
    # dimension introspected as 0 — replace with real value before committing
    op.create_vector_index("Product", "embedding", 0, "cosine")
    op.create_constraint("UNIQUE", "NODE", "User", ["email"])


def downgrade(op) -> None:
    op.drop_constraint("UNIQUE", "NODE", "User", ["email"])
    op.drop_range_index("User", "email")
    op.drop_range_index("User", "created_at")
    op.drop_fulltext_index("Post", "title", "body")
    op.drop_range_index("Post", "published_at")
    op.drop_vector_index("Product", "embedding")
```

### Pattern 3 — Add property indexes in a follow-on revision

```python
revision = "c3d4e5f6a7b8"
down_revision = "ba5el1ne0000"   # previous revision


def upgrade(op) -> None:
    op.create_fulltext_index("Article", "title", "summary")
    op.create_range_index("Article", "published_at")


def downgrade(op) -> None:
    op.drop_fulltext_index("Article", "title", "summary")
    op.drop_range_index("Article", "published_at")
```

### Pattern 4 — Irreversible property rename with snapshot

Set `irreversible = True` so runic refuses to downgrade without `--force`.
Set `snapshot = True` so runic copies the graph before running upgrade and
restores automatically on failure.

```python
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
irreversible = True    # downgrade will fail without --force
snapshot = True        # graph copied before upgrade; restored on failure


def upgrade(op) -> None:
    # Batched rename: processes nodes in pages of 10 000
    op.rename_property("Person", "name", "full_name")
    op.run_cypher(
        "MATCH (p:Person) WHERE p.name IS NOT NULL REMOVE p.name"
    )


def downgrade(op) -> None:
    # Reached only with --force; data loss possible
    op.rename_property("Person", "full_name", "name")
```

### Pattern 5 — Relabel nodes with backend guard

`relabel_nodes` requires multi-label support. On Apache AGE or ArcadeDB it
raises `NotImplementedError`. Use it only when you know the target backend.

```python
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
snapshot = True   # safety net


def upgrade(op) -> None:
    # Raises NotImplementedError on Apache AGE / ArcadeDB
    op.relabel_nodes("Member", "User")
    # Re-create the range index under the new label
    op.create_range_index("User", "email")


def downgrade(op) -> None:
    op.drop_range_index("User", "email")
    op.relabel_nodes("User", "Member")
```

### Pattern 6 — Mandatory constraint with data guard

Add a `MANDATORY` constraint only after confirming — or fixing — that all
nodes satisfy it. Use a Cypher back-fill in upgrade before creating the
constraint.

```python
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"


def upgrade(op) -> None:
    # Back-fill missing values so the constraint won't fail on create
    op.run_cypher(
        "MATCH (u:User) WHERE u.email IS NULL "
        "SET u.email = 'unknown+' + id(u) + '@example.com'"
    )
    op.create_range_index("User", "email")
    op.create_constraint("MANDATORY", "NODE", "User", ["email"])


def downgrade(op) -> None:
    op.drop_constraint("MANDATORY", "NODE", "User", ["email"])
    # Leave the range index; removing it is a separate decision
```

### Pattern 7 — Seed reference data idempotently

`op.seed` uses `MERGE` semantics — re-running is safe.

```python
revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"

_CATEGORIES = [
    {"code": "books", "label": "Books"},
    {"code": "electronics", "label": "Electronics"},
    {"code": "clothing", "label": "Clothing"},
]


def upgrade(op) -> None:
    op.create_range_index("Category", "code")
    op.create_constraint("UNIQUE", "NODE", "Category", ["code"])
    op.seed(
        "MERGE (c:Category {code: row.code}) SET c.label = row.label",
        _CATEGORIES,
    )


def downgrade(op) -> None:
    op.run_cypher("MATCH (c:Category) DETACH DELETE c")
    op.drop_constraint("UNIQUE", "NODE", "Category", ["code"])
    op.drop_range_index("Category", "code")
```

---

## `SchemaManifest` in `env.py`

The `SchemaManifest` is the source of truth for `runic revision --autogenerate`
and `runic check`. Declare every index and constraint your models need:

```python
# runic/env.py
from runic.migrate import create_adapter
from runic.migrate.manifest import (
    FulltextIndex,
    RangeIndex,
    SchemaManifest,
    UniqueConstraint,
    VectorIndex,
)

adapter = create_adapter(
    "falkordb",
    url="falkor://localhost:6379",
    graph_name="myapp",
)

target_manifest = SchemaManifest(
    range_indexes=[
        RangeIndex(label="User", prop="email"),
        RangeIndex(label="User", prop="name"),
        RangeIndex(label="Post", prop="published_at"),
    ],
    fulltext_indexes=[
        FulltextIndex(label="Post", props=["title", "body"]),
        FulltextIndex(label="Article", props=["title", "summary"]),
    ],
    vector_indexes=[
        VectorIndex(label="Product", prop="embedding", dimension=256, similarity="cosine"),
    ],
    constraints=[
        UniqueConstraint(entity="NODE", label="User", props=["email"]),
    ],
)

def context_configure(context):
    context.configure(
        adapter=adapter,
        target_manifest=target_manifest,
        version_table="_RunicMigrateVersion",
    )
```

`runic revision --autogenerate` diffs `target_manifest` against the live
schema and emits the `op.*` calls needed to reconcile them. Always review
the generated file before applying.

---

## See also

- [operations_reference](./operations_reference.md) — full `op.*` API
- [autogenerate](./autogenerate.md) — how `--autogenerate` works in detail
- [schema](./schema.md) — `IndexManager` and `SchemaManager` API reference
- [testing](./testing.md) — round-trip migration testing with `runic test`
- [branching](./branching.md) — working with branches and merge revisions
- [cli_reference](./cli_reference.md) — complete flag reference for all commands
