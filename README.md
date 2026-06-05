<div align="center">
  <img src="docs/source/_static/runic.svg" width="240" alt="Runic logo">

# Runic

**Graph schema migrations for FalkorDB.**

![Version](https://img.shields.io/badge/version-0.1.12-blue)
[![Python](https://img.shields.io/badge/python-3.14%2B-orange)](https://www.python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE.md)

[Features](#features) • [Installation](#installation) • [A Simple Example](#a-simple-example) • [Documentation](#documentation)

</div>

---

**Runic** is a lightweight, Alembic-style migration framework built specifically for [FalkorDB](https://falkordb.com/).
It brings robust revision tracking, linear graph migrations, and a powerful CLI to graph database environments, managing schema versioning through Cypher scripts and native FalkorDB syntax.

## Features

- **Alembic-Style Workflow** — Familiar CLI verbs like `init`, `revision`, `upgrade`, `downgrade`, and `current`.
- **Graph-Native** — Treats your database as a graph. Stores migration states intelligently inside dedicated nodes (e.g., `:_FalkorMigrateVersion`).
- **Idempotent Cypher** — Encourages explicit, heavily-guarded migration steps, supporting robust backward capability even without transactional DDLs.
- **Offline & Dry Run** — Review generated Cypher scripts thoroughly before executing them in production.
- **Rollback Snapshots** — Advanced capabilities utilizing `GRAPH.COPY` for high-risk, non-reversible data migrations.

## Installation

Install via `pip` or `uv`:

```bash
uv pip install runic
```

Or add it to an existing project:

```bash
uv add runic
```

> [!NOTE]
> Runic requires Python 3.14+ and is optimized for the latest FalkorDB clients.

## A Simple Example

Initialize your project and generate a new revision:

```bash
# Set up a new runic environment
runic init

# Create your first revision script
runic revision -m "create user index"
```

This generates a revision file in `runic/versions`. Open it and define your upgrades and downgrades:

```python
"""create user index

Revision ID: 1975ea83b712
Revises: None
Create Date: 2026-05-30 14:00:00.000000
"""

from datetime import UTC, datetime

revision = "1975ea83b712"
down_revision = None
message = "create user index"
create_date = datetime.fromisoformat("2026-05-30T14:00:00+00:00")
branch_labels = []
depends_on = []
irreversible = False
snapshot = False


def upgrade(op) -> None:
    op.create_range_index("User", "email")


def downgrade(op) -> None:
    op.drop_range_index("User", "email")
```

Then apply your changes:

```bash
runic upgrade            # apply all pending revisions
runic downgrade          # roll back one step (default target: -1)
runic downgrade 1975e    # roll back to a revision — prefix is enough
```

## Baselining an existing graph

If you have a FalkorDB graph that was built without Runic, use `baseline` to bring it under management without re-running anything on the source:

```bash
# Introspect the live graph, generate a root revision, and stamp it as applied
runic baseline -m "baseline"
# Generated: runic/versions/<hex>_baseline.py
# Stamped:   <hex>

# Verify the graph is now tracked
runic current
# <hex>  baseline
```

The generated revision recreates all indexes and constraints from scratch — safe to replay on a fresh empty graph (CI, cloning, new tenants):

```bash
runic upgrade head   # rebuilds the full schema on an empty graph
```

Re-running `baseline` on an already-managed graph is refused:

```bash
runic baseline -m "again"
# Error: Graph already managed by runic.migrate. Use `runic upgrade` instead.
```

To mark an existing graph as baselined without generating a file (useful when you manage the revision file yourself):

```bash
runic baseline --stamp-only
```

### Baseline → autogenerate workflow

Once you have a baseline revision, use the standard autogenerate workflow to evolve the schema:

```bash
# After changing your SchemaManifest in env.py:
runic revision --autogenerate -m "add embedding index"
runic upgrade head
```

The baseline revision is the root of the chain (`down_revision = None`). Future revisions chain off it normally.

## Programmatic SDK

Use runic directly in Python — no CLI, no `env.py` needed:

```python
from pathlib import Path
from runic import Runic, init
from runic.migrate.adapters import create_adapter

# One-time setup: scaffold the migration directory
init(Path("runic/"))

# Connect and run
adapter = create_adapter(
    "falkordb",
    url="falkor://localhost:6379",
    graph_name="my_graph",
)
runic = Runic(adapter, script_location=Path("runic/"))
runic.migrate.upgrade("head")

print("current:", runic.migrate.current())
print("history:", runic.migrate.get_history())
```

`Runic` is the single class you need. It handles upgrades, downgrades, stamping, history queries, and revision creation in one coherent API.

## Documentation

For a full conceptual overview, advanced CLI usage, and deep dives into branching or multi-head resolution, visit the complete [Runic Documentation](https://runic-migrate.readthedocs.io/latest/).
