# Installation

## Requirements

* Python 3.14 or newer
* A running graph database instance (see backend sections below)

The core `runic-py` package has no graph-driver dependency. Install only
the optional extra for the backend you use.

## Install from PyPI

```bash
# FalkorDB
uv add "runic-py[falkordb]"

# Neo4j
uv add "runic-py[neo4j]"

# Memgraph  (uses the Neo4j Bolt driver)
uv add "runic-py[memgraph]"

# ArcadeDB  (uses the Neo4j Bolt driver)
uv add "runic-py[arcadedb]"

# Apache AGE  (PostgreSQL extension, requires psycopg)
uv add "runic-py[age]"

# All backends at once
uv add "runic-py[all]"
```

### Available extras

| Extra | Package installed | Backend |
| --- | --- | --- |
| `falkordb` | `falkordb` | FalkorDB |
| `neo4j` | `neo4j` | Neo4j |
| `memgraph` | `neo4j` (Bolt) | Memgraph |
| `arcadedb` | `neo4j` (Bolt) | ArcadeDB |
| `age` | `psycopg[binary]` | Apache AGE (PostgreSQL) |
| `all` | all of the above | every supported backend |

Verify the installation:

```bash
runic --help
```

You should see the runic help text listing all available commands.

## FalkorDB

Start a local FalkorDB instance with Docker:

```bash
docker run -p 6379:6379 falkordb/falkordb
```

For integration testing without an external server, install
[falkordblite](https://pypi.org/project/falkordblite/):

```bash
uv add --dev falkordblite
```

See [migration/testing](./migration/testing.md) for how to use the embedded server in your test suite.

## Neo4j

Start a local Neo4j instance with Docker:

```bash
docker run -p 7474:7474 -p 7687:7687 neo4j:latest
```

## Memgraph

Memgraph speaks the Bolt protocol, so the `memgraph` extra installs the
Neo4j driver:

```bash
docker run -p 7687:7687 memgraph/memgraph
```

## ArcadeDB

ArcadeDB also exposes a Bolt endpoint. The `arcadedb` extra installs the
Neo4j driver:

```bash
docker run -p 2480:2480 -p 2424:2424 -p 7687:7687 arcadedata/arcadedb
```

## Apache AGE

Apache AGE is a PostgreSQL extension. The `age` extra installs
`psycopg[binary]`:

```bash
docker run -p 5432:5432 -e POSTGRES_PASSWORD=postgres apache/age
```

## Development install

Clone the repository and install all dev dependencies:

```bash
git clone https://github.com/jenreh/runic
cd runic
uv sync --all-groups
```
