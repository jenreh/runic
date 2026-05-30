<div align="center">
  <img src="docs/source/_static/runic.svg" width="240" alt="Runic logo">

# Runic

**Graph schema migrations for FalkorDB.**

![Version](https://img.shields.io/badge/version-0.1.5-blue)
[![pypi](https://img.shields.io/pypi/v/runic-migrate.svg)](https://pypi.python.org/pypi/runic-migrate)
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

from runic import op

# revision identifiers, used by Runic.
revision = "1975ea83b712"
down_revision = None


def upgrade() -> None:
    # Use Cypher to create an index
    op.run_cypher("CREATE INDEX ON :User(email)")


def downgrade() -> None:
    # Safely revert the operation
    op.run_cypher("DROP INDEX ON :User(email)")
```

Then apply your changes:

```bash
runic upgrade head
```

## Documentation

For a full conceptual overview, advanced CLI usage, and deep dives into branching or multi-head resolution, visit the complete [Runic Documentation](https://jenreh.github.io/runic/).
