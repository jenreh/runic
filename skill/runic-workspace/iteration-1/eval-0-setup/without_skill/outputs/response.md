This walkthrough uses the actual runic API as shipped. The graph is called `socialnet` and FalkorDB listens on `localhost:6379`.

---

## Step 1 — Install runic

```
pip install runic
```

Or, if your project uses uv:

```
uv add runic
```

---

## Step 2 — Scaffold the migration environment

Run the init command from your project root. By convention this creates a `runic/` directory next to your application code.

```
runic init
```

Output:

```
Created runic environment at runic/
  runic/env.py
  runic/script.py.mako
  runic/versions/
```

Three artefacts are created:

- `runic/env.py` — the connection/configuration file that runic executes before every command.
- `runic/script.py.mako` — the Mako template used to render new migration files.
- `runic/versions/` — directory that will hold your migration scripts.

---

## Step 3 — Configure env.py

Open `runic/env.py`. The scaffolded content looks like this:

```python
import os

from runic import context
from runic.adapters import create_adapter

adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
)
context.configure(adapter)
```

Edit the default graph name to match your setup:

```python
import os

from runic import context
from runic.adapters import create_adapter

adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "socialnet"),
)
context.configure(adapter)
```

The `FALKORDB_URL` and `FALKORDB_GRAPH` environment variables override the defaults at runtime, so you never need to hard-code credentials. For local dev the defaults are correct as-is — `falkor://localhost:6379` and `socialnet`.

`create_adapter` is a factory that accepts the string `"falkordb"` plus `url` and `graph_name`. Internally it calls `FalkorDBAdapter.from_url(url, graph_name)`, which hands you a `FalkorDBAdapter` that satisfies the `GraphAdapter` protocol.

The `context.configure(adapter)` call registers the adapter in a module-level singleton. Every subsequent CLI command (upgrade, downgrade, current, …) re-executes `env.py` to rehydrate that singleton before doing any work.

---

## Step 4 — Create the first migration

Generate an empty migration script:

```
runic revision -m "add User email range index and unique constraint"
```

Output:

```
Created revision: runic/versions/1a2b3c4d5e6f_add_user_email_range_index_and_unique_constraint.py
```

The generated file (truncated to the editable parts):

```python
revision = "1a2b3c4d5e6f"
down_revision = None
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    pass


def downgrade(op) -> None:
    pass
```

Replace the `upgrade` and `downgrade` bodies so the file reads:

```python
"""add User email range index and unique constraint

Revision ID: 1a2b3c4d5e6f
Revises: None
Create Date: 2026-05-30T12:00:00+00:00
"""
from datetime import UTC, datetime

message = "add User email range index and unique constraint"
create_date = datetime.fromisoformat("2026-05-30T12:00:00+00:00")

revision = "1a2b3c4d5e6f"
down_revision = None
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    # A range index is required before FalkorDB will enforce a UNIQUE constraint.
    # create_constraint("UNIQUE", ...) also auto-creates the backing range index
    # if it is missing, but being explicit here makes the migration self-documenting
    # and keeps downgrade symmetrical.
    op.create_range_index("User", "email")
    op.create_constraint("UNIQUE", "NODE", "User", ["email"])


def downgrade(op) -> None:
    # Always drop the constraint before dropping its backing index.
    op.drop_constraint("UNIQUE", "NODE", "User", ["email"])
    op.drop_range_index("User", "email")
```

### What each call does

`op.create_range_index("User", "email")`
Runs `CREATE INDEX FOR (n:User) ON (n.email)` against FalkorDB. The `rel=False` default is correct for node properties.

`op.create_constraint("UNIQUE", "NODE", "User", ["email"])`
Issues a `GRAPH.CONSTRAINT CREATE` Redis command. FalkorDB enforces uniqueness asynchronously; runic polls `CALL db.constraints()` every 0.5 s (up to 30 retries) until the status reaches `OPERATIONAL`. If status becomes `FAILED` it raises `ConstraintFailedError` immediately.

`op.drop_constraint("UNIQUE", "NODE", "User", ["email"])`
Issues `GRAPH.CONSTRAINT DROP`. Must precede the `drop_range_index` call; FalkorDB refuses to drop an index while a constraint still references it.

`op.drop_range_index("User", "email")`
Runs `DROP INDEX ON :User(email)`.

---

## Step 5 — Apply the migration

```
runic upgrade
```

Without an explicit target this applies all pending revisions up to `head`. Output:

```
Upgraded to: head
```

Verify the current revision:

```
runic current
```

Output:

```
1a2b3c4d5e6f — add User email range index and unique constraint
```

---

## Step 6 — Optional: round-trip test before applying to production

runic ships a built-in test command that forks an ephemeral copy of the graph, runs upgrade → downgrade → upgrade, then deletes it:

```
runic test 1a2b3c4d5e6f
```

Output:

```
runic test 1a2b3c4d5e6f
─────────────────────────────────────────────
Phase A (upgrade):    ✓  nodes=0  indices=1  constraints=1
Phase B (downgrade):  ✓  nodes=0  indices=0  constraints=0
Phase C (idempotency):✓  nodes=0  indices=1  constraints=1
─────────────────────────────────────────────
PASSED
```

If any phase fails, the ephemeral graph is still cleaned up and the command exits with code 1.

---

## Summary of commands

| Goal | Command |
|---|---|
| Scaffold environment | `runic init` |
| Create empty script | `runic revision -m "..."` |
| Apply all pending | `runic upgrade` |
| Apply to specific rev | `runic upgrade <rev-id>` |
| Roll back one step | `runic downgrade -1` |
| Roll back everything | `runic downgrade base` |
| Show applied revision | `runic current` |
| Round-trip test | `runic test <rev-id>` |
| Show history | `runic history` |

---

## Key API facts

- `FalkorDBAdapter.from_url(url, graph_name)` is the direct constructor; `create_adapter("falkordb", url=..., graph_name=...)` is its factory wrapper.
- Connection URL scheme is `falkor://host:port` (not `redis://`).
- `context.configure(adapter)` must be called in `env.py`; the CLI re-executes that file before each command.
- Default config path for all commands is `runic/env.py`; override with `--config path/to/env.py`.
- `create_constraint("UNIQUE", ...)` automatically creates the backing range index if absent, but explicit `create_range_index` in `upgrade` is recommended for clarity and clean `downgrade` symmetry.
- Constraint creation is asynchronous in FalkorDB; runic polls until `OPERATIONAL` or raises after timeout.
