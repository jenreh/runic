# Quickstart

This page takes you from a fresh install to a working migration in about
five minutes.  The example uses FalkorDB; swap the adapter name and
connection kwargs for any other supported backend (see [installation](../installation)).

Prerequisites: runic installed ([installation](../installation)) and a graph database
reachable — e.g. FalkorDB at `falkor://localhost:6379`.

## Step 1 — Initialise the migration directory

Run `runic init` from your project root.  It creates a small directory
tree that runic uses to store revision scripts and your database connection
config:

```bash
$ runic init
Created runic environment at runic/
  runic/env.py
  runic/script.py.mako
  runic/versions/
```

`runic/` is the default directory name.  Pass any path to place it
elsewhere:

```bash
$ runic init migrations
Created runic environment at migrations/
  migrations/env.py
  migrations/script.py.mako
  migrations/versions/
  .runic  (config pointer — commit this file)
```

When you use a custom directory, runic writes a `.runic` marker file in
the current directory so that subsequent commands (`runic upgrade`,
`runic info`, …) resolve the config automatically — no `--config` flag
needed.

Three files are created:

`env.py`
: Executed by the CLI whenever a live database connection is needed.
  It reads your connection URL from an environment variable and calls
  `context.configure()`.

`script.py.mako`
: Mako template used by `runic revision` to generate new migration
  files.  You rarely need to edit this.

`versions/`
: Empty directory (with a `.gitkeep`) where generated revision scripts
  are placed.

## Step 2 — Configure your connection

Open `runic/env.py`.  The generated file reads connection details from
environment variables.

**No-auth (local dev):**

```python
adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
)
```

**With authentication** — embed credentials directly in the URL:

```python
# password only:   falkor://:mypassword@localhost:6379
# user+password:   falkor://myuser:mypassword@localhost:6379
adapter = create_adapter(
    "falkordb",
    url=os.getenv("FALKORDB_URL", "falkor://:mypassword@localhost:6379"),
    graph_name=os.getenv("FALKORDB_GRAPH", "my_graph"),
)
```

Alternatively, supply explicit `host`/`port`/`username`/`password`
kwargs instead of a URL — see the commented-out *Variant B* block in `env.py`.

The generated `context.configure()` call has additional commented-out options
you may want to enable:

```python
context.configure(
    adapter,
    # target_manifest=target_manifest,  # enable schema drift detection
    # track_checksums=True,             # set False to disable checksum recording
    # track_installed_by=True,          # set False to skip OS-user attribution
)
```

Set connection environment variables (here `FALKORDB_URL` and `FALKORDB_GRAPH`)
in your environment or a `.env` file loaded by your shell.

**Using a different backend** — swap `create_adapter` name and kwargs:

```python
# ArcadeDB (Bolt protocol)
adapter = create_adapter(
    "arcadedb",
    host=os.getenv("ARCADEDB_HOST", "localhost"),
    database=os.getenv("ARCADEDB_DATABASE", "my_db"),
)

# Neo4j
adapter = create_adapter(
    "neo4j",
    host=os.getenv("NEO4J_HOST", "localhost"),
    database=os.getenv("NEO4J_DATABASE", "neo4j"),
    password=os.getenv("NEO4J_PASSWORD", ""),
)

# Apache AGE (PostgreSQL)
adapter = create_adapter(
    "age",
    host=os.getenv("AGE_HOST", "localhost"),
    graph=os.getenv("AGE_GRAPH", "my_graph"),
    password=os.getenv("POSTGRES_PASSWORD", ""),
)
```

All backends support the same `upgrade`/`downgrade`/`stamp`/`current`
workflow.  Schema-drift autogenerate (`runic revision --autogenerate`) is
FalkorDB-only — see [autogenerate](./autogenerate.md) and [limitations](./limitations.md).

## Step 3 — Create your first revision

```bash
$ runic revision -m "add person email index"
Created revision: runic/versions/3f9a12c1_add_person_email_index.py
```

Open the generated file.  It contains two empty functions:

```python
revision = "3f9a12c1"
down_revision = None          # None = this is the first revision
branch_labels = []
depends_on = []
irreversible = False
snapshot = False

def upgrade(op) -> None:
    pass

def downgrade(op) -> None:
    pass
```

Edit `upgrade` and `downgrade` to describe the schema change:

```python
def upgrade(op) -> None:
    op.create_range_index("Person", "email")

def downgrade(op) -> None:
    op.drop_range_index("Person", "email")
```

## Step 4 — Preview the migration (optional)

`--preview` prints the operations that *would* run without touching the
database:

```bash
$ runic upgrade --preview
CREATE RANGE INDEX: CREATE INDEX FOR (n:Person) ON (n.email) params=None
```

## Step 5 — Apply the migration

```bash
$ runic upgrade
Upgraded to: 3f9a12c1ab4e
```

## Step 6 — Check the current revision

```bash
$ runic current
3f9a12c1 — add person email index
```

## Step 7 — Roll back

```bash
$ runic downgrade base
Downgraded to: base

$ runic current
<none>
```

## Next steps

* [integration](./integration.md) — revision anatomy, ordering rules, and 7 annotated
  patterns including irreversible flags and snapshot-based rollback
* [operations_reference](./operations_reference.md) — full list of `op.*` calls
* [autogenerate](./autogenerate.md) — generate migration scripts from a schema manifest
