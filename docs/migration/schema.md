# Schema management

`runic.migrate` provides two utilities for keeping graph indexes and constraints
in sync with your model declarations:

* `IndexManager` — creates indexes for one model class at a time; low overhead, surgical control.
* `SchemaManager` — validates, diffs, and syncs indexes across a list of models.

Both accept a migrate adapter from `create_adapter()`
and are typically called **once at application startup**, not per request.

::: info See also
`examples/orm/05_schema_management.py`
   Runnable example covering `IndexManager`, `SchemaManager` validate/diff/sync,
   and multi-backend adapter creation.
:::

---

## Quick start

```python
from runic.migrate import SchemaManager
from runic.migrate.adapters import create_adapter

adapter = create_adapter(
    "neo4j",          # or "falkordb", "memgraph", "arcadedb", "age"
    host="localhost",
    database="mydb",
    password="secret",
)

schema = SchemaManager(adapter)
schema.sync_schema([Person, Trip])          # create all missing indexes
result = schema.validate_schema([Person, Trip])
print(schema.get_schema_diff([Person, Trip]))
```

For FalkorDB, the raw `FalkorDB.Graph` handle (`db.select_graph("myapp")`)
is also accepted for backward compatibility; the adapter path is preferred.

---

## Declaring indexes on models

Index hints live on `Field()` parameters:

```python
from runic.ogm import Field, Node

class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True)
    email: str = Field(unique=True)          # UNIQUE constraint
    bio: str = Field(index_type="FULLTEXT")   # fulltext index
    embedding: list[float] = Field(index_type="VECTOR")  # vector index

class Trip(Node, labels=["Trip"]):
    id: str = Field(primary_key=True)
    title: str = Field(index_type="FULLTEXT")
    start_date: str = Field(index=True)      # RANGE index
```

| Parameter | Effect |
| --- | --- |
| `index=True` | Creates a RANGE index (equality and range queries). |
| `unique=True` | Creates a UNIQUE constraint. On FalkorDB a backing RANGE index is also created automatically. |
| `index_type="FULLTEXT"` | Creates a fulltext index. Multiple fields with the same label are batched into a single `create_fulltext_index(label, *props)` call. |
| `index_type="VECTOR"` | Creates a vector index. Backends that require a dimension at creation time (Neo4j, Memgraph) need the index pre-created with the correct dimension via a migration op — `IndexManager` passes `dimension=0` as a placeholder. |

---

## IndexManager

`IndexManager` creates indexes for one model class at a time.

```python
from runic.migrate import IndexManager
from runic.migrate.adapters import create_adapter

adapter = create_adapter("neo4j", host="localhost", database="neo4j", password="secret")
manager = IndexManager(adapter)

manager.create_indexes(Person)    # create declared indexes; skip if already present
manager.ensure_indexes(Trip)      # alias — preferred name for startup code
```

| Method | Description |
| --- | --- |
| `create_indexes(cls, if_not_exists=True)` | Create all declared indexes on *cls*. FULLTEXT specs for the same label are batched into one call. When `if_not_exists=True` (default) existing specs are skipped. |
| `ensure_indexes(cls)` | Alias for `create_indexes(cls, if_not_exists=True)`. Preferred for startup code where "make sure these exist" is the intent. |
| `create_spec(spec)` | Issue the adapter call for a single `IndexSpec`. |
| `drop_spec(spec)` | Drop the index or constraint described by *spec*. |

::: info
`if_not_exists=False` forces all create calls even for existing indexes.
Most adapters raise an error or log a warning for duplicate creates unless
they support `IF NOT EXISTS` semantics (Neo4j, Memgraph do; FalkorDB does not).
:::

---

## SchemaManager

`SchemaManager` adds validate, diff, and sync operations on top of `IndexManager`.

```python
from runic.migrate import SchemaManager
from runic.migrate.adapters import create_adapter
import logging

log = logging.getLogger(__name__)

adapter = create_adapter("memgraph", host="localhost", database="memgraph")
schema = SchemaManager(adapter)

MODELS = [Person, Trip]

result = schema.validate_schema(MODELS)
if not result.is_valid:
    log.warning("Missing: %s", result.missing_indexes)
    log.warning("Extra:   %s", result.extra_indexes)

schema.sync_schema(MODELS)                   # create missing; leave extras
schema.sync_schema(MODELS, drop_extra=True)  # also drop unrecognised indexes

log.info("%s", schema.get_schema_diff(MODELS))
```

| Method | Description |
| --- | --- |
| `validate_schema(classes)` | Diff declared vs existing. Returns a `ValidationResult` with `is_valid`, `missing_indexes`, `extra_indexes`, and `errors`. |
| `sync_schema(classes, drop_extra=False)` | Create entity types (ArcadeDB) and all missing indexes. When `drop_extra=True` also drops indexes present in the graph but not declared on any model. |
| `get_schema_diff(classes)` | Human-readable diff string. Lines are prefixed `MISSING` or `EXTRA`; returns `"Schema is in sync — no differences found."` when clean. |
| `get_schema_info(classes)` | Full diagnostics — returns a `SchemaInfo` with declared, existing, missing, and extra spec counts and sets. |
| `ensure_entity_types(classes)` | Issues `CREATE VERTEX TYPE` / `CREATE EDGE TYPE` for ArcadeDB. No-op for schemaless backends. |

### ValidationResult fields

| Field | Description |
| --- | --- |
| `is_valid` | `True` when declared and existing sets are identical and no errors occurred. |
| `missing_indexes` | Specs declared on a model but not yet created in the graph. |
| `extra_indexes` | Specs present in the graph but not declared on any model. |
| `errors` | Non-fatal messages collected during introspection (e.g. connection failures). |

---

## When to use IndexManager vs SchemaManager vs migration ops

| Tool | Context | When to reach for it |
| --- | --- | --- |
| `IndexManager` | Application startup or scripts | You want to ensure a single model's indexes exist. Fast, per-class, no diffing overhead. |
| `SchemaManager` | Startup, CI health checks, or ops scripts | You want to diff, validate, or sync the whole schema across multiple models. `get_schema_diff` is useful for CI assertions; `sync_schema` is the one-liner startup idiom. |
| Migration ops (`op.*`) | Production deployments | You need a versioned, replayable audit trail. Every change is tracked in the graph and can be rolled back. Use for production schema changes where history and rollback matter. |

**Rule of thumb:** use `SchemaManager` at startup for development and test
environments; use migration ops for any change you'd want to review in a PR and
be able to roll back in production.

---

## Cross-backend behaviour

| Backend | Pass | Notes |
| --- | --- | --- |
| FalkorDB | `create_adapter("falkordb", ...)` | Full introspection via `CALL db.indexes()` / `CALL db.constraints()`. Validate and diff are precise. Also accepts the raw `FalkorDB.Graph` handle for backward compatibility. |
| Neo4j | `create_adapter("neo4j", ...)` | Introspection via `SHOW INDEXES` / `SHOW CONSTRAINTS`. Validates RANGE, FULLTEXT, and VECTOR indexes and UNIQUENESS constraints. Create calls use `IF NOT EXISTS` — idempotent. |
| Memgraph | `create_adapter("memgraph", ...)` | Introspection via `SHOW INDEX INFO` / `SHOW CONSTRAINT INFO`. Validates RANGE indexes and UNIQUE / MANDATORY constraints only — FULLTEXT and VECTOR indexes are not exposed by these commands. Create calls are idempotent. |
| ArcadeDB | `create_adapter("arcadedb", ...)` | No introspection (HTTP management API required — not implemented). Every declared spec is treated as missing; `sync_schema` calls `ensure_entity_types` first to create vertex/edge collections. |
| Apache AGE | `create_adapter("age", ...)` | No introspection. All DDL calls log a warning and do nothing — AGE does not support Cypher-level DDL. Manage indexes via PostgreSQL DDL. |

::: info
`runic.migrate` manages both schema utilities and versioned migrations.
For a tracked, replayable record of schema changes see [runic.migrate](../migration/index.md).
:::

---

## API reference

### IndexManager

`IndexManager` creates indexes for one model class at a time.

Methods: `create_indexes`, `ensure_indexes`, `create_spec`, `drop_spec`.

### SchemaManager

`SchemaManager` adds validate, diff, and sync operations on top of `IndexManager`.

Methods: `validate_schema`, `sync_schema`, `get_schema_diff`, `get_schema_info`, `ensure_entity_types`.
