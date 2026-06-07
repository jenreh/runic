# Plan: Multi-driver IndexManager + SchemaManager + all Bolt adapter DDL

## Context

Four gaps exist in the current multi-database adapter architecture:

1. **IndexManager is FalkorDB-only.** It calls raw FalkorDB SDK methods and cannot work with any other driver.

2. **SchemaManager is also FalkorDB-only.** It calls `parse_existing_specs(self._graph)` directly and passes the raw graph to `IndexManager`.

3. **`create_adapter()` supports only `falkordb`, `arcadedb`, and `age`.** Neo4j and Memgraph have no migrate adapter.

4. **ArcadeDB and AGE adapters are architecturally inconsistent** — mixing `NotImplementedError` and `log.warning`. Also, ArcadeDB requires `CREATE VERTEX TYPE` / `CREATE EDGE TYPE` DDL before inserting data **and** before creating indexes on a type. Indexes fail if the type does not yet exist, even on empty collections.

---

## Design Decisions

### Local `IndexAdapter` Protocol (no circular imports)

`orm.schema` must NOT import `migrate.adapters`. Define a local `IndexAdapter` Protocol in `orm.schema.index_manager` whose shape is satisfied structurally by all migrate adapters.

**Auto-detection for backward compat:** `IndexManager.__init__` and `SchemaManager.__init__` check `hasattr(_, 'create_node_range_index')` (FalkorDB SDK). If present → wrap in `FalkorDBIndexAdapter`. Otherwise treat as `IndexAdapter`. No construction site changes needed.

### Entity type creation (prerequisite for ArcadeDB indexes)

ArcadeDB requires explicit type declarations before indexes can be created on empty collections:

- Node subclass → `CREATE VERTEX TYPE {_primary_label} IF NOT EXISTS`
- Edge subclass → `CREATE EDGE TYPE {_edge_type} IF NOT EXISTS`

Neo4j, Memgraph, FalkorDB, and AGE are schemaless — no-op.

**The `IndexAdapter` protocol gains two new methods: `create_vertex_type(label)` and `create_edge_type(type_name)`.**

**`IndexManager.create_indexes(entity_class)` calls type creation first** — before any index DDL — using `issubclass(entity_class, Node)` / `issubclass(entity_class, Edge)`. This ensures standalone `IndexManager` use also works on empty ArcadeDB collections.

`SchemaManager.sync_schema()` calls `ensure_entity_types(entity_classes)` at the top, then delegates to `IndexManager.create_indexes()` per class. Type creation is therefore idempotent across both paths.

### SchemaManager with all adapters

Replace `parse_existing_specs(self._graph)` with `self._adapter.get_existing_specs()`. For non-FalkorDB adapters this returns an empty set — `validate_schema` will show all declared specs as "missing"; `sync_schema` still creates them correctly.

### Fulltext collision (critical correctness)

On Neo4j/Memgraph, one fulltext index per label covers all properties. `create_indexes()` must **collapse FULLTEXT specs by label** and call `adapter.create_fulltext_index(label, *all_props)` once per label. FalkorDB's API also accepts multi-prop calls, so batching works for all backends.

### Idempotency

| Backend | Strategy |
|---|---|
| FalkorDB | `parse_existing_specs()` pre-check |
| Neo4j | `IF NOT EXISTS` in DDL Cypher |
| Memgraph | try/except + log.warning |
| ArcadeDB | `IF NOT EXISTS` for type DDL; try/except + log.warning for indexes |
| AGE | log.warning (DDL is PostgreSQL-level) |

### Vector index naming (must match dialect)

`vector_knn_start` uses name `f"{type_name}_{field_name}"`. DDL Cypher must use the same name.

---

## Files to Change

### 1. `runic/orm/schema/index_manager.py`

Add `IndexAdapter` Protocol with:

- DDL methods (range, fulltext, vector, constraint, drop variants)
- `create_vertex_type(label) -> None`
- `create_edge_type(type_name) -> None`
- `get_existing_specs() -> set[IndexSpec]`

Add `FalkorDBIndexAdapter` (no-op type creation; `get_existing_specs` delegates to `parse_existing_specs`).

Modify `IndexManager`:

- `__init__`: auto-wrap FalkorDB graph via `hasattr`
- `create_indexes(entity_class)`: **call `create_vertex_type` / `create_edge_type` first** (detected via `issubclass`); then collapse FULLTEXT specs by label; use `get_existing_specs()` for dedup
- `create_spec()` / `drop_spec()`: delegate to `self._adapter`

### 2. `runic/orm/schema/schema_manager.py`

- `__init__`: accept FalkorDB graph (auto-wrap) or `IndexAdapter`; store as `self._adapter`
- Replace `parse_existing_specs(self._graph)` → `self._adapter.get_existing_specs()`
- Add `ensure_entity_types(entity_classes: list[type]) -> None`
- `sync_schema()`: call `ensure_entity_types(entity_classes)` first, then delegate to `IndexManager.create_indexes()` per class
- Construct `IndexManager(self._adapter)` instead of `IndexManager(self._graph)`
- Update docstrings

### 3. `runic/migrate/adapters/neo4j.py` (new)

`Neo4jAdapter` using `BoltDriver` + `_NEO4J_DIALECT`:

- **Range:** `CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})`
- **Fulltext:** `CREATE FULLTEXT INDEX {label} IF NOT EXISTS FOR (n:{label}) ON EACH [{prop_list}]`
- **Vector:** `CREATE VECTOR INDEX {label}_{prop} IF NOT EXISTS FOR (n:{label}) ON (n.{prop}) OPTIONS {{indexConfig: {{vector.dimensions: {dim}, vector.similarity_function: '{sim}'}}}}`
- **Unique:** `CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE`
- **create_vertex_type / create_edge_type:** no-op (schemaless)
- **read_live_schema / get_existing_specs:** empty LiveSchema / empty set
- **Snapshots:** `NotImplementedError`

### 4. `runic/migrate/adapters/memgraph.py` (new)

`MemgraphAdapter` using `BoltDriver` + `_MEMGRAPH_DIALECT`:

- **Range:** `CREATE INDEX ON :{label}({prop})` — try/except + log.warning
- **Fulltext:** `CREATE TEXT INDEX {label} ON :{label}` (whole-label; name = `{label}`)
- **Vector:** `CREATE VECTOR INDEX {label}_{prop} ON :{label}({prop}) WITH CONFIG {{"dimension": {dim}, "capacity": 1000}}`
- **Unique:** `CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE`
- **create_vertex_type / create_edge_type:** no-op (schemaless)
- **read_live_schema / get_existing_specs:** empty LiveSchema / empty set
- **Snapshots:** `NotImplementedError`

### 5. `runic/migrate/adapters/arcadedb.py` — DDL + entity type creation

- **create_vertex_type:** `CREATE VERTEX TYPE {label} IF NOT EXISTS` (real DDL — executed before index DDL)
- **create_edge_type:** `CREATE EDGE TYPE {type_name} IF NOT EXISTS` (real DDL)
- **Fulltext:** `CREATE FULLTEXT INDEX ON \`{label}\` ({props_csv})` — try/except + log.warning
- **Vector:** log.warning (created via HTTP API, not openCypher)
- **Unique constraint:** `CREATE INDEX ON \`{label}\` ({prop}) UNIQUE` — try/except + log.warning
- **drop_*:** try/except + log.warning
- **get_existing_specs:** empty set
- Remove all `NotImplementedError` except snapshots

### 6. `runic/migrate/adapters/age.py` — consistent pattern

- **create_vertex_type / create_edge_type:** no-op (AGE creates labels implicitly)
- Change all DDL `NotImplementedError` → `log.warning` with PostgreSQL guidance
- Keep `NotImplementedError` for snapshots
- Add `get_existing_specs()` → empty set

### 7. `runic/migrate/adapters/__init__.py`

- Add `neo4j` and `memgraph` branches to `create_adapter()`
- Update Supported list in error message

### 8. Tests

**`tests/runic/migrate/test_neo4j_adapter.py`** (new): unit tests with mocked `BoltDriver`; verify DDL Cypher index names match dialect naming contracts; version/checksum tracking

**`tests/runic/migrate/test_memgraph_adapter.py`** (new): same pattern

**`tests/runic/orm/schema/test_index_manager.py`** — add:

- `IndexManager` with mock `IndexAdapter` (non-FalkorDB path)
- `create_indexes(NodeClass)` calls `create_vertex_type` before index DDL
- Fulltext batching: two FULLTEXT fields on same label → one `create_fulltext_index(label, prop1, prop2)` call

**`tests/runic/orm/schema/test_schema_manager.py`** — add:

- `SchemaManager` with mock `IndexAdapter`
- `sync_schema([PersonNode])` calls `create_vertex_type` before index creation
- `ensure_entity_types` dispatches Node → `create_vertex_type`, Edge → `create_edge_type`

### 9. Docs

- Update `docs/source/drivers.rst` feature matrix
- Update docstrings in ORM driver files (`neo4j.py`, `memgraph.py`)

---

## Key Constraints

- `parse_existing_specs(graph)` unchanged — used inside `FalkorDBIndexAdapter`
- Existing `IndexManager(graph)` / `SchemaManager(graph)` call sites unchanged
- Files ≤ 1000 lines

---

## Verification

```bash
task format && task lint && task typecheck
task test
```

Confirm:

- `IndexManager(arcadedb_adapter).create_indexes(PersonNode)` runs `CREATE VERTEX TYPE Person IF NOT EXISTS` before any index DDL, even with zero Person nodes in the DB
- `SchemaManager(arcadedb_adapter).sync_schema([PersonNode, KnowsEdge])` creates vertex type, edge type, then indexes
- `SchemaManager(neo4j_adapter).sync_schema([PersonNode])` creates indexes only (no-op type creation)
- Fulltext batching: one `create_fulltext_index(label, prop1, prop2)` call when two FULLTEXT fields share a label
