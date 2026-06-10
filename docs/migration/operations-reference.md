# Operations Reference

The `op` object passed to every `upgrade(op)` and `downgrade(op)`
function is an instance of `GraphOperations`.
It wraps the active `GraphAdapter` and exposes
a safe, preview-aware API for all supported schema operations.

In preview mode (`runic upgrade --preview`) none of the methods below
touch the database; instead each operation is recorded as a string in
`op.preview_log` and printed to the console.

::: info
FalkorDB, Neo4j, and Memgraph support most DDL natively via Cypher.
ArcadeDB supports most DDL except vector indexes (which require the HTTP
management API). Apache AGE does not support Cypher-level DDL: all
`op.*` calls on an AGE adapter log a warning and do nothing — manage
indexes and constraints via PostgreSQL DDL directly. Backend-specific
differences are noted per section. The `MANDATORY` constraint kind and
automatic constraint-ready polling are FalkorDB-only.
:::

---

## Range indexes

Range indexes support equality and range queries on node or relationship
properties (`WHERE n.prop = $x`, `WHERE n.prop > $x`).

### op.create_range_index(label, prop, *, rel=False)

Create a range index on `label.prop`.

| Parameter | Description |
|-----------|-------------|
| `label` | Node label (or relationship type when `rel=True`). |
| `prop` | Property name. |
| `rel` | `True` to index a relationship property instead of a node property. |

```python
def upgrade(op) -> None:
    op.create_range_index("Person", "email")
    op.create_range_index("KNOWS", "since", rel=True)
```

The generated Cypher is:

```text
CREATE INDEX FOR (n:Person) ON (n.email)
CREATE INDEX FOR ()-[r:KNOWS]->() ON (r.since)
```

### op.drop_range_index(label, prop, *, rel=False)

Drop a range index.

| Parameter | Description |
|-----------|-------------|
| `label` | Node label or relationship type. |
| `prop` | Property name. |
| `rel` | `True` for a relationship index. |

```python
def downgrade(op) -> None:
    op.drop_range_index("Person", "email")
```

---

## Fulltext indexes

Fulltext indexes enable substring and token search via
`CALL db.idx.fulltext.queryNodes()`.

### op.create_fulltext_index(label, *props, language=None, stopwords=None)

Create a fulltext index on one or more properties of a node label.

| Parameter | Description |
|-----------|-------------|
| `label` | Node label. |
| `props` | One or more property names. |
| `language` | Optional language for the text analyzer (e.g. `"english"`, `"german"`). Defaults to `"english"` when omitted. |
| `stopwords` | Optional list of stopword strings. |

```python
def upgrade(op) -> None:
    op.create_fulltext_index("Article", "title", "body")
    op.create_fulltext_index(
        "Review",
        "text",
        language="german",
        stopwords=["und", "oder"],
    )
```

### op.drop_fulltext_index(label, *props)

Drop a fulltext index.

| Parameter | Description |
|-----------|-------------|
| `label` | Node label. |
| `props` | Property names (one per call internally). |

```python
def downgrade(op) -> None:
    op.drop_fulltext_index("Article", "title", "body")
```

---

## Vector indexes

Vector indexes enable approximate nearest-neighbour search (ANN) via HNSW.
Used for semantic similarity queries.

::: info
ArcadeDB vector indexes must be created via the ArcadeDB HTTP management
API. Calling `op.create_vector_index` on an ArcadeDB adapter logs a
warning and does nothing; configure vector indexes outside runic for that
backend.
:::

### op.create_vector_index(label, prop, dimension, similarity, *, m=16, ef_construction=200, ef_runtime=10)

Create a vector index.

| Parameter | Description |
|-----------|-------------|
| `label` | Node label. |
| `prop` | Property name that stores the vector (list of floats). |
| `dimension` | Vector dimensionality (e.g. `1536` for OpenAI `text-embedding-3-small`). |
| `similarity` | Distance function — `"cosine"` or `"euclidean"`. |
| `m` | HNSW `M` parameter (max neighbours per layer). Default 16. |
| `ef_construction` | HNSW `efConstruction` (build-time search width). Default 200. |
| `ef_runtime` | HNSW `efRuntime` (query-time search width). Default 10. |

```python
def upgrade(op) -> None:
    op.create_vector_index(
        "Document",
        "embedding",
        dimension=1536,
        similarity="cosine",
    )
```

### op.drop_vector_index(label, prop)

Drop a vector index.

```python
def downgrade(op) -> None:
    op.drop_vector_index("Document", "embedding")
```

---

## Constraints

`UNIQUE` constraints ensure no two nodes of the same label share the same
property value. `MANDATORY` constraints (FalkorDB only) ensure the property
is always present.

| Kind | FalkorDB | ArcadeDB | Neo4j | Memgraph | Apache AGE |
|------|----------|----------|-------|----------|------------|
| `UNIQUE` | ✓ | ✓ (single-prop, NODE only) | ✓ (single-prop, NODE only) | ✓ (single-prop, NODE only) | ✗ |
| `MANDATORY` | ✓ | ✗ | ✗ | ✗ | ✗ |

### op.create_constraint(kind, entity, label, props)

Create a constraint.

| Parameter | Description |
|-----------|-------------|
| `kind` | `"UNIQUE"` or `"MANDATORY"`. |
| `entity` | `"NODE"` or `"RELATIONSHIP"`. |
| `label` | Node label or relationship type. |
| `props` | List of property names. |

::: info
**FalkorDB:** runic automatically calls `create_range_index` on each
property before creating the constraint and polls `CALL db.constraints()`
until the status is `OPERATIONAL` (30 retries × 0.5 s). You do not
need to call `create_range_index` separately in `upgrade` for this case.
:::

```python
def upgrade(op) -> None:
    op.create_constraint("UNIQUE", "NODE", "Person", ["email"])
    op.create_constraint("MANDATORY", "NODE", "Person", ["name"])  # FalkorDB only
```

For FalkorDB, runic polls `CALL db.constraints()` and raises
`ConstraintFailedError` if the status
becomes `FAILED`, or `ConstraintTimeoutError`
if it does not become `OPERATIONAL` within 15 seconds.

### op.drop_constraint(kind, entity, label, props)

Drop a constraint.

| Parameter | Description |
|-----------|-------------|
| `kind` | `"UNIQUE"` or `"MANDATORY"`. |
| `entity` | `"NODE"` or `"RELATIONSHIP"`. |
| `label` | Node label or relationship type. |
| `props` | List of property names. |

```python
def downgrade(op) -> None:
    op.drop_constraint("UNIQUE", "NODE", "Person", ["email"])
    op.drop_range_index("Person", "email")
```

---

## Data transformation

These helpers perform batched Cypher queries for common data-level changes.
They are safe to run on large graphs because they operate in configurable
batch sizes.

### op.rename_property(label, old, new, batch=10_000)

Rename a property on all nodes of a given label. Runs in a loop until
no more nodes are affected.

| Parameter | Description |
|-----------|-------------|
| `label` | Node label. |
| `old` | Current property name. |
| `new` | New property name. |
| `batch` | Number of nodes processed per query. Default 10 000. |

```python
def upgrade(op) -> None:
    op.rename_property("User", "email_address", "email")
```

::: warning
Property renames are **not** detected by autogenerate. You must write
them manually in both `upgrade` and `downgrade`.
:::

### op.relabel_nodes(old, new, batch=10_000)

Rename a node label across the entire graph. Adds the new label and
removes the old one for each matching node in batches.

| Parameter | Description |
|-----------|-------------|
| `old` | Current label. |
| `new` | New label. |
| `batch` | Nodes per batch. |

```python
def upgrade(op) -> None:
    op.relabel_nodes("User", "Person")
```

### op.seed(merge_query, rows)

Insert or merge reference data. Wraps each row with
`UNWIND $rows AS row <merge_query>`.

| Parameter | Description |
|-----------|-------------|
| `merge_query` | Cypher fragment starting after the `UNWIND ... AS row` clause (e.g. `"MERGE (c:Country {code: row.code}) SET c.name = row.name"`). |
| `rows` | List of parameter dicts, one per row. |

```python
_COUNTRIES = [
    {"code": "DE", "name": "Germany"},
    {"code": "FR", "name": "France"},
]

def upgrade(op) -> None:
    op.seed(
        "MERGE (c:Country {code: row.code}) SET c.name = row.name",
        _COUNTRIES,
    )

def downgrade(op) -> None:
    op.run_cypher(
        "MATCH (c:Country) WHERE c.code IN $codes DETACH DELETE c",
        {"codes": [r["code"] for r in _COUNTRIES]},
    )
```

---

## Raw Cypher

For anything not covered by the helpers above:

### op.run_cypher(query, params=None)

Execute an arbitrary Cypher query against the graph.

| Parameter | Description |
|-----------|-------------|
| `query` | Cypher string. |
| `params` | Optional parameter dict. |
| **Returns** | The raw adapter result object (or `None` in preview mode). |

```python
def upgrade(op) -> None:
    op.run_cypher(
        "MATCH (n:Person) SET n.active = true"
    )
    op.run_cypher(
        "MATCH (n:Person) WHERE n.score < $threshold DELETE n",
        {"threshold": 0},
    )
```

---

## Error classes

These exceptions are raised by `op.create_constraint()` during constraint
polling. They live in `runic.migrate.exceptions` and are exported from the
top-level `runic` package.

### ConstraintFailedError

Raised when FalkorDB reports a constraint status of `FAILED` during polling.

### ConstraintTimeoutError

Raised when a FalkorDB constraint does not reach `OPERATIONAL` status within
15 seconds (30 retries × 0.5 s).
