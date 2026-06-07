# Plan: Unify Schema Introspection Across All Backends

## Context

`IndexManager` and `SchemaManager` have a special FalkorDB detection path
(`hasattr(adapter_or_graph, "create_node_range_index")`) that wraps raw graph
handles in an internal `FalkorDBIndexAdapter`. This means the canonical usage
for FalkorDB is `IndexManager(graph)` (raw handle), while all other backends
get `IndexManager(adapter)` (migrate adapter). The result:

1. FalkorDB is the *only* backend with working `get_existing_specs()` — the
   method is a stub (`return set()`) on every other adapter.
2. The `FalkorDBAdapter` (the migrate adapter) itself also returns `set()` from
   `get_existing_specs()`, so passing `create_adapter("falkordb", ...)` to
   IndexManager gives no introspection.
3. Docs had to document two patterns and warn that only FalkorDB has real
   validate/diff support.

**Goal:** every adapter that the database supports should implement
`get_existing_specs()`. FalkorDB and the two Bolt backends (Neo4j, Memgraph)
all have working introspection commands. ArcadeDB and AGE are out of scope for
now (see below).

---

## Research findings

### FalkorDB

`FalkorDBAdapter.read_live_schema()` already calls
`introspect.read_live_schema(self._graph)` which issues `CALL db.indexes()` and
`CALL db.constraints()` and parses both into `LiveSchema`. We can implement
`get_existing_specs()` by converting `LiveSchema` → `set[IndexSpec]`.
The backing RANGE index that FalkorDB auto-creates for a UNIQUE constraint must
be excluded (same logic as `parse_existing_specs()` in `index_manager.py`).

### Neo4j

`SHOW INDEXES YIELD type, entityType, labelsOrTypes, properties, state` and
`SHOW CONSTRAINTS YIELD type, entityType, labelsOrTypes, properties` are
available since Neo4j 4.0 via Bolt. Results come back as rows from
`run_ro_query()`.

Key type mappings:

- index type `"RANGE"` / `"FULLTEXT"` / `"VECTOR"` → direct
- constraint type `"UNIQUENESS"` → `"UNIQUE"` (Neo4j name differs)
- Skip `LOOKUP`, `POINT`, `TEXT`, `NODE_KEY`, `EXISTENCE` types

### Memgraph

`SHOW INDEX INFO` returns `indexType, label, property, count`. Map
`"label+property"` → `RANGE`; skip `"label"` (no property) and relationship
types. `SHOW CONSTRAINT INFO` returns `constraintType, label, properties`. Map
`"unique"` → `UNIQUE`; `"exists"` → `MANDATORY`.
Memgraph fulltext and vector indexes are not exposed by `SHOW INDEX INFO` —
they use MAGE module procedures. Leave fulltext/vector as not introspectable for
Memgraph (only RANGE and UNIQUE will show in validate/diff).

### ArcadeDB

The openCypher dialect does not expose `SHOW INDEXES`/`SHOW CONSTRAINTS`.
Schema introspection requires the HTTP management API
(`GET /api/v1/schema/{database}`). Implementing it would need a separate HTTP
request path not used elsewhere in the adapters. **Defer — leave as `set()`.**

### Apache AGE

Intentionally has no Cypher-level DDL. All DDL calls warn and do nothing.
Schema introspection would require querying PostgreSQL's `pg_indexes` and
interpreting AGE's internal table naming conventions — complex and out of scope.
**Leave as `set()`.**

---

## Implementation plan

### 1. `FalkorDBAdapter.get_existing_specs()` — `runic/migrate/adapters/falkordb.py`

Add a method that reuses the already-working `read_live_schema()`:

```python
def get_existing_specs(self) -> set[IndexSpec]:
    from runic.orm.schema.index_manager import IndexSpec

    schema = self.read_live_schema()
    unique_pairs: set[tuple[str, str]] = set()
    specs: set[IndexSpec] = set()
    for con in schema.constraints:
        kind = "UNIQUE" if con.__class__.__name__ == "UniqueConstraint" else "MANDATORY"
        for prop in con.props:
            specs.add(IndexSpec(label=con.label, property=prop, index_type=kind))
            if kind == "UNIQUE":
                unique_pairs.add((con.label, prop))
    for ri in schema.range_indexes:
        if (ri.label, ri.prop) in unique_pairs:
            continue  # exclude FalkorDB auto-backing range index for UNIQUE
        specs.add(IndexSpec(label=ri.label, property=ri.prop, index_type="RANGE"))
    for fi in schema.fulltext_indexes:
        for prop in fi.props:
            specs.add(IndexSpec(label=fi.label, property=prop, index_type="FULLTEXT"))
    for vi in schema.vector_indexes:
        specs.add(IndexSpec(label=vi.label, property=vi.prop, index_type="VECTOR"))
    return specs
```

No changes to `FalkorDBIndexAdapter` — backward compat (raw graph handle path)
is preserved. Over time, update callsites and examples to use `create_adapter()`.

### 2. `Neo4jAdapter.get_existing_specs()` — `runic/migrate/adapters/neo4j.py`

```python
def get_existing_specs(self) -> set[IndexSpec]:
    from runic.orm.schema.index_manager import IndexSpec

    specs: set[IndexSpec] = set()
    try:
        result = self.run_ro_query(
            "SHOW INDEXES YIELD type, entityType, labelsOrTypes, properties, state"
        )
        for row in result.rows:
            idx_type, entity_type, labels, props, state = (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
            )
            if state != "ONLINE" or entity_type != "NODE":
                continue
            if idx_type not in {"RANGE", "FULLTEXT", "VECTOR"}:
                continue
            label = labels[0] if labels else None
            if not label:
                continue
            for prop in props:
                specs.add(IndexSpec(label=label, property=prop, index_type=idx_type))
    except Exception as exc:
        log.warning("Neo4j SHOW INDEXES failed: %s", exc)
    try:
        result = self.run_ro_query(
            "SHOW CONSTRAINTS YIELD type, entityType, labelsOrTypes, properties"
        )
        for row in result.rows:
            con_type, entity_type, labels, props = row[0], row[1], row[2], row[3]
            if entity_type != "NODE" or con_type != "UNIQUENESS":
                continue
            label = labels[0] if labels else None
            if not label:
                continue
            for prop in props:
                specs.add(IndexSpec(label=label, property=prop, index_type="UNIQUE"))
    except Exception as exc:
        log.warning("Neo4j SHOW CONSTRAINTS failed: %s", exc)
    return specs
```

### 3. `MemgraphAdapter.get_existing_specs()` — `runic/migrate/adapters/memgraph.py`

```python
def get_existing_specs(self) -> set[IndexSpec]:
    from runic.orm.schema.index_manager import IndexSpec

    specs: set[IndexSpec] = set()
    try:
        result = self.run_ro_query("SHOW INDEX INFO")
        for row in result.rows:
            idx_type, label, prop = row[0], row[1], row[2]
            if idx_type == "label+property" and prop:
                specs.add(IndexSpec(label=label, property=prop, index_type="RANGE"))
    except Exception as exc:
        log.warning("Memgraph SHOW INDEX INFO failed: %s", exc)
    try:
        result = self.run_ro_query("SHOW CONSTRAINT INFO")
        for row in result.rows:
            con_type, label, props = row[0], row[1], row[2]
            kind = (
                "UNIQUE"
                if con_type == "unique"
                else "MANDATORY"
                if con_type == "exists"
                else None
            )
            if not kind:
                continue
            prop_list = props if isinstance(props, list) else [props]
            for prop in prop_list:
                specs.add(IndexSpec(label=label, property=prop, index_type=kind))
    except Exception as exc:
        log.warning("Memgraph SHOW CONSTRAINT INFO failed: %s", exc)
    return specs
```

Note: Memgraph TEXT/VECTOR indexes are not exposed by `SHOW INDEX INFO`. Only
RANGE and UNIQUE/MANDATORY are introspectable. Log a note in docstring.

### 4. `FalkorDBAdapter` also needs `read_live_schema()` fix

`introspect.read_live_schema()` uses `graph.ro_query()` (raw FalkorDB Python
client method). This already works. No change needed here.

### 5. `IndexManager` / `SchemaManager` — no change needed

Both already accept any `IndexAdapter`-conforming object. Once the adapters
implement `get_existing_specs()`, they work automatically. The FalkorDB raw
handle backward compat path via `FalkorDBIndexAdapter` is unchanged.

---

## Tests

### Unit tests

- `tests/runic/migrate/adapters/test_falkordb_get_existing_specs.py` (new) —
  mock `FalkorDBAdapter.read_live_schema()` with a `LiveSchema` fixture; assert
  correct `set[IndexSpec]` returned, including UNIQUE/MANDATORY constraints and
  exclusion of auto-backing RANGE.
- Extend `tests/runic/migrate/adapters/test_neo4j_dialect.py` (or a new file) —
  mock `run_ro_query()` with rows matching `SHOW INDEXES` / `SHOW CONSTRAINTS`
  format; assert returned `set[IndexSpec]`.
- Extend / add similar for Memgraph.

### Integration tests (marker `@pytest.mark.integration`)

- Extend `tests/runic/orm/integration/test_schema.py` to run against the
  FalkorDB adapter path (`create_adapter("falkordb", ...)`) in addition to the
  raw handle path.
- Add a Neo4j integration test if a Neo4j container is available in CI.
- Add a Memgraph integration test similarly.

---

## Docs

Update `docs/source/schema.rst`:

- Remove the "Two patterns" split (raw handle vs adapter).
- Primary pattern for FalkorDB: `create_adapter("falkordb", ...)` → `SchemaManager(adapter)`.
- Keep the raw-handle variant as "backward-compatible".
- Update the cross-backend table: FalkorDB, Neo4j, Memgraph now have introspection; ArcadeDB and AGE remain create-only.
- Update `docs/source/migration/limitations.rst` to note that `get_existing_specs()` now works for Neo4j and Memgraph (lift the FalkorDB-only claim from the ORM schema validation section, though migrate autogenerate remains FalkorDB-only).

---

## Files to modify

| File | Change |
|------|--------|
| `runic/migrate/adapters/falkordb.py` | Add `get_existing_specs()` |
| `runic/migrate/adapters/neo4j.py` | Add `get_existing_specs()` |
| `runic/migrate/adapters/memgraph.py` | Add `get_existing_specs()` |
| `docs/source/schema.rst` | Update patterns + table |
| `docs/source/migration/limitations.rst` | Update introspection scope note |
| `tests/runic/migrate/adapters/` | New unit tests for each adapter |
| `tests/runic/orm/integration/test_schema.py` | Add FalkorDB-via-adapter path |
| `examples/orm/05_schema_management.py` | Update to show `create_adapter()` path |

---

## Out of scope / not included

- ArcadeDB `get_existing_specs()` — needs HTTP API, defer
- AGE `get_existing_specs()` — needs PostgreSQL introspection, defer
- `read_live_schema()` (migration autogenerate) on non-FalkorDB backends — separate concern
- Removing `FalkorDBIndexAdapter` / backward compat path — leave in place; only add the adapter path
