# GraphOperations (`op`) — Full API Reference

The `op` argument injected into every `upgrade(op)` and `downgrade(op)` function
is a `runic.migrate.operations.GraphOperations` instance. In `--preview` mode it logs
the intended operation instead of executing it.

---

## Index operations

### Range index

```python
op.create_range_index(label: str, prop: str, *, rel: bool = False) -> None
op.drop_range_index(label: str, prop: str, *, rel: bool = False) -> None
```

`rel=True` creates/drops a range index on a relationship type instead of a node label.

```python
op.create_range_index("User", "email")
op.create_range_index("FOLLOWS", "since", rel=True)
op.drop_range_index("User", "email")
op.drop_range_index("FOLLOWS", "since", rel=True)
```

### Full-text index

```python
op.create_fulltext_index(
    label: str,
    *props: str,
    language: str | None = None,
    stopwords: list[str] | None = None,
) -> None
op.drop_fulltext_index(label: str, *props: str) -> None
```

```python
op.create_fulltext_index("Post", "title", "body")
op.create_fulltext_index("Article", "title", language="german",
                          stopwords=["der", "die", "das"])
op.drop_fulltext_index("Post", "title", "body")
```

### Vector index (HNSW)

```python
op.create_vector_index(
    label: str,
    prop: str,
    dimension: int,
    similarity: str,           # "cosine" | "euclidean"
    *,
    m: int = 16,
    ef_construction: int = 200,
    ef_runtime: int = 10,
) -> None
op.drop_vector_index(label: str, prop: str) -> None
```

```python
op.create_vector_index("Product", "embedding", 256, "cosine")
op.create_vector_index("Doc", "vec", 128, "euclidean",
                        m=32, ef_construction=400, ef_runtime=20)
op.drop_vector_index("Product", "embedding")
```

---

## Constraint operations

```python
op.create_constraint(
    kind: str,     # "UNIQUE" | "MANDATORY"
    entity: str,   # "NODE"   | "RELATIONSHIP"
    label: str,
    props: list[str],
) -> None
op.drop_constraint(kind: str, entity: str, label: str, props: list[str]) -> None
```

`create_constraint("UNIQUE", ...)` automatically creates the required backing
range index if it does not exist, then polls `CALL db.constraints()` until
status reaches `OPERATIONAL`. Raises `ConstraintFailedError` on `FAILED`.

```python
op.create_constraint("UNIQUE",    "NODE",         "User",    ["email"])
op.create_constraint("MANDATORY", "NODE",         "User",    ["email"])
op.create_constraint("UNIQUE",    "RELATIONSHIP", "FOLLOWS", ["id"])
op.drop_constraint("UNIQUE",    "NODE",         "User",    ["email"])
op.drop_constraint("MANDATORY", "NODE",         "User",    ["email"])
```

**Ordering rule:** in `downgrade`, always drop constraints *before* the backing
range index, or FalkorDB will refuse the index drop.

---

## Data transformation operations

All data-transform ops are **batched and idempotent** — safe to re-run after a
partial failure.

### rename_property

```python
op.rename_property(label: str, old: str, new: str, batch: int = 10_000) -> None
```

Iterates pages of `MATCH (n:label) WHERE n.old IS NOT NULL AND n.new IS NULL`
until exhausted.

```python
op.rename_property("User", "fname", "first_name")
op.rename_property("Order", "ts", "created_at", batch=5_000)
```

### relabel_nodes

```python
op.relabel_nodes(old: str, new: str, batch: int = 10_000) -> None
```

```python
op.relabel_nodes("Member", "User")
```

### seed

```python
op.seed(merge_query: str, rows: list[dict]) -> None
```

Executes `UNWIND $rows AS row <merge_query>` — idempotent reference data load.

```python
op.seed(
    "MERGE (r:Role {name: row.name}) SET r.system = row.system",
    [{"name": "admin", "system": True}, {"name": "user", "system": False}],
)
```

### run_cypher

```python
op.run_cypher(query: str, params: dict | None = None) -> Any
```

Raw escape hatch for anything not covered by the higher-level ops.

```python
op.run_cypher(
    "MATCH (u:User) WHERE u.active IS NULL SET u.active = true"
)
op.run_cypher(
    "CREATE (c:Config {key: $k, value: $v})",
    {"k": "schema_version", "v": "2"},
)
```

---

## SchemaManifest (for autogenerate / check)

Set `target_manifest` in `env.py`; runic diffs it against the live schema.

```python
from runic.migrate.manifest import (
    SchemaManifest,
    RangeIndex,
    FulltextIndex,
    VectorIndex,
    UniqueConstraint,
    MandatoryConstraint,
)

manifest = SchemaManifest(
    range_indexes=[
        RangeIndex("User", "email"),
        RangeIndex("User", "created_at"),
        RangeIndex("FOLLOWS", "since", rel=True),
    ],
    fulltext_indexes=[
        FulltextIndex("Post", ["title", "body"], language="english"),
    ],
    vector_indexes=[
        VectorIndex("Product", "embedding", dimension=256, similarity="cosine"),
    ],
    constraints=[
        UniqueConstraint("NODE", "User", ["email"]),
        MandatoryConstraint("NODE", "User", ["email"]),
    ],
)
```

**Autogenerate limitations:**
- Covers indexes and constraints only — node/relationship "schema" is implicit.
- Cannot detect renames (generates drop + create). Always review before applying.
- Cannot generate data migrations.
- Generated bodies are marked `# AUTOGENERATED — review before applying`.
