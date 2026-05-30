---
name: runic
description: |
  Expert guide for runic — an Alembic-style FalkorDB graph schema migration
  tool. Use whenever the user works with runic: CLI commands, migration file
  anatomy, op.* API, env.py config, autogenerate, branching/merge, or testing.
  Invoke for any versions/*.py file, `runic` CLI question, or FalkorDB schema
  change task.
---

# Runic — FalkorDB Migration Tool

Runic is an Alembic-style migration framework for FalkorDB. It tracks schema
versions in a `(:_FalkorMigrateVersion)` node inside each graph and drives
upgrades/downgrades via Python scripts stored in `versions/`.

For real migration file examples see [examples/](examples/).  
For the full `op.*` API and `SchemaManifest` see [references/op-api.md](references/op-api.md).  
For autogenerate, programmatic SDK, testing, and branching see [references/advanced.md](references/advanced.md).

---

## Quick-start

```bash
pip install runic          # or: uv add runic

runic init                 # scaffold runic/ directory
# edit runic/env.py to point at your FalkorDB instance
runic revision -m "create user index"
# edit the generated versions/*.py (see examples/ for patterns)
runic upgrade head
```

---

## Directory layout (after `runic init`)

```
runic/
├── env.py            # executed on every CLI call; configures adapter + context
├── script.py.mako    # Mako template for new revision files
└── versions/
    ├── .gitkeep
    └── <rev_id>_<slug>.py
```

Default config: `runic/env.py` — override with `--config path/to/env.py`.

---

## env.py

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

For autogenerate/check, add `target_manifest` — see [references/advanced.md](references/advanced.md).

---

## CLI reference

| Command | Description |
|---|---|
| `runic init [DIR]` | Scaffold migration environment (default: `runic/`) |
| `runic revision -m "msg"` | Create new empty revision at current head |
| `runic revision -m "msg" --autogenerate` | Diff manifest vs live; emit candidate ops |
| `runic upgrade [TARGET]` | Apply upgrades to TARGET (default: `head`) |
| `runic upgrade TARGET --preview` | Print ops without executing |
| `runic downgrade TARGET` | Revert to TARGET (`base`, `-1`, rev id) |
| `runic downgrade TARGET --force` | Revert through `irreversible` revisions |
| `runic current` | Show applied revision |
| `runic history` | List all revisions newest-first |
| `runic history --verbose --indicate-current` | Include create_date, flag current |
| `runic history --range start:end` | Slice of history |
| `runic heads` | List all head revisions (multiple = branched) |
| `runic branches` | List branch-point revisions |
| `runic stamp TARGET` | Set version pointer without running migrations |
| `runic stamp base --purge` | Clear version pointer |
| `runic show REV` | Print full metadata for a revision |
| `runic test REV` | Round-trip test: upgrade → downgrade → upgrade |
| `runic test REV --url URL --graph NAME` | Same against an explicit DB |
| `runic merge R1 R2 -m "msg"` | Create merge revision for two heads |
| `runic check` | CI gate: non-zero exit if manifest has pending changes |

**Relative targets:** `+1` / `+2` (upgrade N steps), `-1` / `-2` (downgrade N steps).

---

## Migration file anatomy

```python
"""create user email index

Revision ID: 1975ea83b712
Revises: None
Create Date: 2026-05-30T14:00:00+00:00
"""
from datetime import UTC, datetime

message = "create user email index"
create_date = datetime.fromisoformat("2026-05-30T14:00:00+00:00")

revision = "1975ea83b712"
down_revision = None       # None = base; str = parent id; tuple = merge revision
branch_labels = []
depends_on = []
irreversible = False       # True → refuse downgrade unless --force
snapshot = False           # True → GRAPH.COPY before upgrade; restore on failure


def upgrade(op) -> None:
    op.create_range_index("User", "email")
    op.create_constraint("UNIQUE", "NODE", "User", ["email"])


def downgrade(op) -> None:
    op.drop_constraint("UNIQUE", "NODE", "User", ["email"])  # constraint BEFORE index
    op.drop_range_index("User", "email")
```

**Key rules:**
- Drop constraints **before** dropping their backing range index in `downgrade`.
- Create the range index **before** a unique constraint on the same property in `upgrade`.
- Use `irreversible = True` for one-way data migrations (e.g. rename + drop old property).
- Use `snapshot = True` for risky data migrations; runic `GRAPH.COPY`s before upgrade and restores on failure/downgrade.
- Keep every data step **idempotent** — use `MERGE` / guarded `WHERE … IS NULL` writes; FalkorDB has no multi-statement transactions.

---

For the full `op.*` API signatures, see [references/op-api.md](references/op-api.md).
