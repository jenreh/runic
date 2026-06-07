# Plan: Refactor Test Suite — Multi-Backend, Decoupled, De-duplicated

## Context

The `runic` test suite has grown organically around FalkorDB (via embedded `redislite`). While the ORM and migration layers now support five backends (FalkorDB, Neo4j, Memgraph, ArcadeDB, Apache AGE), only FalkorDB has real integration coverage. Driver-specific concerns leak into generic tests, mock helpers are copy-pasted across files, and eight integration test files each redefine an identical `graph` fixture. This refactor fixes all three problems without changing any public API.

---

## Goals

1. **Decouple** — no FalkorDB imports in tests that aren't testing FalkorDB-specific behavior.
2. **De-duplicate** — shared mock builders and shared adapter base tests extracted once.
3. **Multi-backend integration** — both `runic.migrate` and `runic.orm` integration tests run against every configured backend using Docker Compose, with zero code duplication (only the driver changes).
4. **Driver-specific isolation** — FalkorDB/Bolt/AGE unit tests live in their own modules.
5. **Voyager scenario** — THE canonical integration test exercises all ORM features end-to-end.

---

## Phase 0 — Audit the Current Test Suite (required before any edits)

Run the following analysis before touching any file. Capture findings in a working note or inline reasoning — they drive every subsequent decision.

```bash
# 1. Full test file inventory
find tests -type f -name "*.py" | sort

# 2. FalkorDB coupling: any test importing FalkorDB concrete types
grep -rn "FalkorDBDriver\|falkordb_server\|falkordb_graph\|from runic.orm.driver.falkordb\|from redislite" tests/

# 3. Mock usage: copy-pasted helpers
grep -rn "_empty_result\|_node_result\|_multi_node_result\|_scalar_result\|_row_result" tests/

# 4. Duplicate adapter test classes
grep -rn "class TestParseKvList\|class TestEncodeKvList" tests/

# 5. Local graph fixture boilerplate (the 8-file pattern)
grep -rn "def graph(falkordb_server" tests/

# 6. Integration marker coverage
grep -rn "pytest.mark.integration\|pytestmark.*integration\|importorskip" tests/

# 7. Line counts per test file (flag files > 300 lines as candidates to split)
wc -l tests/**/*.py tests/**/**/*.py | sort -rn | head -30
```

For each coupling found in step 2: classify as (a) truly driver-specific → move to `drivers/`, (b) generic ORM logic using FalkorDB as the concrete driver → replace with `graph_driver` fixture.

Only proceed to Phase 1 once this map is complete and matches the plan's file list below.

---

## Phase 1 — Infrastructure: Docker Compose + Backend Fixtures

### 1a. `docker-compose.test.yml`

New file at repo root. Define services:

| Service | Image | Ports | Env |
|---------|-------|-------|-----|
| `falkordb` | `falkordb/falkordb:latest` | 6379 | — |
| `neo4j` | `neo4j:5` | 7687 | `NEO4J_AUTH=none` |
| `memgraph` | `memgraph/memgraph:latest` | 7687 | (different port: 7688) |
| `arcadedb` | `arcadedb/arcadedb:latest` | 2480 (HTTP), 2424 (Bolt) | `ARCADEDB_SERVER_ROOTPASSWORD=...` |
| `age` | `apache/age:latest` | 5432 | `POSTGRES_PASSWORD=...` |

Each service gets a health check. The `neo4j` default is `bolt://localhost:7687`; memgraph uses port 7688 to avoid conflict.

### 1b. Taskfile targets

In `taskfiles/Taskfile.qa.yml`:

```yaml
test:integration:up:
  desc: Start test backend containers
  cmd: docker compose -f docker-compose.test.yml up -d --wait

test:integration:down:
  desc: Stop test backend containers
  cmd: docker compose -f docker-compose.test.yml down -v

test:integration:
  desc: Run integration tests against all configured backends
  deps: [test:integration:up]
  cmd: uv run pytest -m integration --cov
```

### 1c. Root `conftest.py` — `backend_driver` parametrized fixture

Replace the current `falkordb_server` / `falkordb_graph` import chain with a new fixture architecture:

```
tests/conftest.py
tests/_backends.py      ← backend registry + connection helpers
```

**`tests/_backends.py`** — reads `RUNIC_TEST_BACKENDS` env var (comma-separated, default `falkordb`). For each name, provides:

- `connect(backend_name) -> GraphDriver` — creates a driver using `runic.orm.driver.factory.create_driver`
- `cleanup(driver, graph_name)` — drops the test graph/database

FalkorDB is the only embedded backend (uses `redislite.FalkorDB`). Others connect to Docker Compose services using fixed local connection strings (or env var overrides):

| Backend | Default connection |
|---------|--------------------|
| `falkordb` | embedded via redislite |
| `neo4j` | `bolt://localhost:7687`, no auth |
| `memgraph` | `bolt://localhost:7688`, no auth |
| `arcadedb` | `bolt://localhost:2424`, root/... |
| `age` | `localhost:5432`, db=`postgres`, graph=`test` |

**`tests/conftest.py`** exports a `graph_driver` fixture parametrized over enabled backends:

```python
@pytest.fixture(params=_backends.enabled_backends())
def graph_driver(request) -> Iterator[GraphDriver]:
    backend = request.param
    driver, cleanup = _backends.make_driver(
        backend, graph_name=f"test_{secrets.token_hex(6)}"
    )
    yield driver
    cleanup()
```

The old `falkordb_server`, `falkordb_graph`, and `runic_context` fixtures are kept for existing migrate tests during the transition, then replaced.

---

## Phase 2 — De-duplication: Extract Shared Helpers

### 2a. Adapter base tests — `tests/runic/migrate/test_adapter_base.py`

`TestParseKvList` and `TestEncodeKvList` are defined identically in:

- `tests/runic/migrate/test_neo4j_adapter.py`
- `tests/runic/migrate/test_memgraph_adapter.py`
- `tests/runic/migrate/test_age_adapter.py`

**Action:** Delete from all three; move once to `test_adapter_base.py` importing from `runic.migrate.adapters._base`.

### 2b. Mock result builders — `tests/runic/orm/unit/mock_helpers.py`

`_empty_result()`, `_node_result()`, `_multi_node_result()`, `_scalar_result()`, `_row_result()` are copy-pasted across:

- `test_neo4j_adapter.py`, `test_memgraph_adapter.py` (migrate)
- `test_session.py`, `test_repository.py` (orm/unit)

**Action:** Extract to `tests/runic/orm/unit/mock_helpers.py`. Update all imports.

---

## Phase 3 — Driver-Specific Tests → Own Modules

Create `tests/runic/orm/drivers/` with `__init__.py` and per-driver subdirectories:

```
tests/runic/orm/drivers/
├── __init__.py
├── falkordb/
│   ├── __init__.py
│   ├── test_driver.py          ← from test_driver_factories.py (FalkorDB parts)
│   ├── test_transactions.py    ← from test_driver_transactions.py (FalkorDB parts)
│   └── test_relationship_writer.py  ← moved from unit/
├── bolt/
│   ├── __init__.py
│   ├── test_driver.py          ← BoltDriver factory/transaction tests
│   └── test_neo4j_dialect.py   ← moved from unit/
│   └── test_memgraph_dialect.py ← moved from unit/
│   └── test_arcadedb_dialect.py (new)
└── age/
    ├── __init__.py
    ├── test_driver.py          ← AGE driver tests
    └── test_age_dialect.py     ← moved from unit/
```

`test_driver_factories.py` and `test_driver_transactions.py` in `unit/` are deleted after content is moved.

**`tests/runic/orm/session/test_session.py`** — currently imports `FalkorDBDriver` directly. Replace with a `mock_driver` fixture (plain `MagicMock` satisfying `GraphDriver` Protocol, or a small stub class) so the session identity map / dirty-tracking logic is tested independently of any concrete driver. Keep the FalkorDB-specific session behavior in `drivers/falkordb/`.

---

## Phase 4 — ORM Integration Tests: Decouple + Voyager Canonical Test

### 4a. Consolidate `graph` fixture

Each of the 8 `tests/runic/orm/integration/test_*.py` files defines its own `graph` fixture. All 8 are deleted. The shared `graph_driver` fixture from root `conftest.py` (Phase 1c) replaces them automatically — the parametrization across backends is handled there.

Each integration test file imports nothing from `runic.orm.driver.falkordb`. Tests use `graph_driver: GraphDriver` typed as the Protocol.

### 4b. Voyager canonical integration test

`tests/runic/orm/integration/test_voyager_integration.py` — consolidate the existing `test_voyager_patterns.py` content, expanded to explicitly cover every feature:

| Feature | Test class / function |
|---------|----------------------|
| Session CRUD (add, commit, get, update, delete) | `TestSessionLifecycle` |
| Identity map deduplication | `TestIdentityMap` |
| Repository find_all, find_by_ids, count, exists | `TestRepositoryCrud` |
| Eager & lazy relationship loading | `TestRelationshipLoading` |
| Relationship mutations (create/delete) | `TestRelationshipMutations` |
| Pagination | `TestPagination` |
| Custom types (Vector, GeoLocation, Enum, UUID) | `TestCustomTypes` |
| Polymorphic nodes | `TestPolymorphism` |
| Fulltext + vector search | `TestSearch` |
| Schema sync (IndexManager, SchemaManager) | `TestSchema` |
| DataOperations (run_cypher, seed, rename_property) | `TestDataOperations` |

Use the Voyager domain: `Location`, `Country`, `City`, `User`, `Trip`, `Invitation`, `LOCATED_IN`, `PARTICIPATED_IN`, `INVITED_TO`.

Domain setup via a `voyager_graph` fixture that populates the graph before the class runs.

The existing `test_voyager_patterns.py` is **deleted** — its content is absorbed and extended here.

### 4c. Other integration test files

`test_session_integration.py`, `test_repository_crud.py`, `test_relationships.py`, `test_relationship_mutations.py`, `test_pagination_integration.py`, `test_new_types.py`, `test_cypher_helpers.py` remain but:

- Remove local `graph` fixture definition (uses root `graph_driver` instead)
- Remove all `from runic.orm.driver.falkordb import FalkorDBDriver` imports
- Remove `try/except redislite` import guard (handled centrally in `_backends.py`)

---

## Phase 5 — Migrate Integration Tests: Multi-Backend

Currently `tests/runic/migrate/test_integration.py`, `test_cli_phase3.py`, `test_validate.py` hardcode FalkorDB.

**Approach:** Introduce a `migrate_context` fixture in `tests/conftest.py` (parametrized over backends) that creates a `RunicContext` via `create_driver(backend)`. Individual migrate integration tests use `migrate_context` instead of `runic_context`.

The `runic_context` fixture (`runic.migrate.testing`) stays for backward-compat until all callers are updated.

For backends that don't support all DDL (e.g., AGE has no vector DDL), individual tests use `pytest.skip` or `pytest.xfail` conditioned on `request.param`.

---

## Critical Files

**New files:**

- `docker-compose.test.yml`
- `tests/_backends.py`
- `tests/runic/migrate/test_adapter_base.py`
- `tests/runic/orm/unit/mock_helpers.py`
- `tests/runic/orm/drivers/` (tree above)
- `tests/runic/orm/integration/test_voyager_integration.py`

**Modified files:**

- `tests/conftest.py` — new `graph_driver`, `migrate_context` parametrized fixtures
- `tests/runic/orm/integration/test_*.py` (7 files) — remove local `graph` fixture + FalkorDB imports
- `tests/runic/migrate/test_neo4j_adapter.py`, `test_memgraph_adapter.py`, `test_age_adapter.py` — remove duplicate test classes
- `tests/runic/orm/unit/test_session.py`, `test_repository.py` — import mock helpers from `mock_helpers.py`; decouple from FalkorDB
- `tests/runic/orm/unit/test_driver_factories.py`, `test_driver_transactions.py` — deleted after split
- `tests/runic/orm/unit/test_relationship_writer.py`, `test_relationships.py` — moved to `drivers/falkordb/`
- `taskfiles/Taskfile.qa.yml` — new `test:integration` task group
- `pyproject.toml` — add pytest markers: `integration`, per-backend markers if needed

**Deleted files:**

- `tests/runic/orm/integration/test_voyager_patterns.py` (absorbed)
- `tests/runic/orm/unit/test_driver_factories.py` (split out)
- `tests/runic/orm/unit/test_driver_transactions.py` (split out)

---

## Reusable Utilities

- `runic.orm.driver.factory.create_driver(backend, **kwargs)` — `tests/_backends.py` uses this
- `runic.migrate.testing.falkordb_server` — kept as FalkorDB-only fixture, still re-exported for migrate-layer tests
- `runic.migrate.adapters._base._parse_kv_list` / `_encode_kv_list` — `test_adapter_base.py` imports from here

---

## Verification

```bash
# 1. Start all test backend containers
task test:integration:up

# 2. Run full suite (unit + integration, all configured backends)
task test:integration

# 3. Run unit tests only (no docker needed)
uv run pytest -m "not integration"

# 4. Run integration for a single backend
RUNIC_TEST_BACKENDS=neo4j uv run pytest -m integration

# 5. Quality gates
task lint && task format && task typecheck

# 6. Coverage must stay ≥ 80% on non-Reflex sources
uv run pytest --cov --cov-report=term-missing
```

Integration tests must:

- Pass against FalkorDB (embedded/server), Neo4j 5.x, Memgraph, ArcadeDB
- Skip gracefully (not fail) when a backend container is not available
- Leave no orphan graphs (cleanup in fixture teardown)
- Report which backends ran in the pytest header

---

## Out of Scope

- Changing any ORM or migration public API
- Adding new ORM features
- Refactoring the Cypher query builder
- ArcadeDB fulltext/vector (not supported; existing xfail/skip markers stay)
- AGE vector/fulltext (same)
