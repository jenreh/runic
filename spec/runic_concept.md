# FalkorMigrate: A Lightweight, Alembic-Style Migration Framework for FalkorDB — Concept & Phased Implementation Plan

**Bottom line:** An Alembic-style migration framework for FalkorDB is feasible and worth building, but ~70% of Alembic's conceptual model ports cleanly (revision graph, version tracking, CLI verbs, upgrade/downgrade scripts) while the remaining ~30% must be redesigned around three hard graph-database realities: FalkorDB has *no tables and no transactional DDL*, its only atomic unit is the *single Cypher query* (there is no multi-statement BEGIN/COMMIT across the graph), and its "schema" is implicit except for introspectable indexes and constraints. The pragmatic design stores the version pointer in a dedicated metadata node inside the graph itself (mirroring `alembic_version`), treats migrations as ordered Cypher/operation batches, and makes rollback an explicitly-authored `downgrade()` augmented by optional `GRAPH.COPY` snapshots — because Cypher data transformations are frequently irreversible.

## TL;DR

- **Map, don't copy.** Alembic's revision graph, `down_revision` chaining, `head(s)`, `stamp`, and CLI verbs (`init`, `revision`, `upgrade`, `downgrade`, `current`, `history`, `heads`, `show`) all transfer directly. The `alembic_version` *table* becomes a singleton `:_FalkorMigrateVersion` *node* (or a Redis key) per graph; the `op.*` schema API becomes `op.create_index / create_constraint / run_cypher / rename_property`, built on verified FalkorDB syntax (`CREATE INDEX … / DROP INDEX ON :Label(prop)`, `CREATE VECTOR INDEX`, `CALL db.idx.fulltext.createNodeIndex(...)`, `GRAPH.CONSTRAINT CREATE/DROP`).
- **Atomicity is the central gap.** FalkorDB has no cross-statement transaction over the graph and no transactional DDL, so a migration that runs several queries is *not* atomic. The framework must compensate with (a) per-migration version-stamp-after-success, (b) optional `GRAPH.COPY` snapshot-and-restore for risky data migrations, (c) idempotent Cypher (`MERGE`, guarded writes), and (d) explicit `irreversible=True` markers where no clean `downgrade()` exists.
- **Build it in five phases.** Phase 0 = MVP (version node + linear upgrade/downgrade + `revision`/`upgrade`/`downgrade`/`current` CLI). Phase 1 = history graph + `history`/`heads`/`show`/`stamp`. Phase 2 = `op` operations API + dry-run/offline preview. Phase 3 = testing harness on ephemeral Docker/`falkordblite` FalkorDB + snapshot rollback. Phase 4 = limited autogenerate for indexes/constraints (the only introspectable schema) + branching/merge. Keep the core deliberately small — branching, merge, and autogenerate are *nice-to-have*, not essential.

---

# Part 1 — Deep Analysis of Alembic

Alembic (current release **1.18.4**, per the Alembic documentation, accessed May 2026) is described in its own Tutorial as "a lightweight database migration tool for usage with the SQLAlchemy Database Toolkit for Python." Understanding its internal model is the foundation for the FalkorDB design.

### 1.1 Core concepts: revisions, the revision graph, heads, base

A **migration script** ("revision") is a single Python file in `versions/`. Each carries four module-level identifiers defining its place in a directed acyclic graph (DAG):

- `revision` — the script's own id. Alembic generates these as random 12-character hex tokens (partial GUIDs, conceptually like Git commit hashes); for example the Tutorial uses base revision `1975ea83b712` followed by `ae1027a6acf`, and notes you may reference a revision by a unique prefix such as `ae1`.
- `down_revision` — pointer to the parent revision(s). `None` = the **base** (first) revision. A *tuple* of parents = a **merge** revision.
- `branch_labels` — optional name(s) for an independent revision stream.
- `depends_on` — optional cross-stream dependency (see §1.11).

These pointers form the **revision graph**. A **head** is any revision that is not the `down_revision` of any other — a tip of the DAG. A linear project has exactly one head; concurrent development can produce **multiple heads** (a branch). The **base** has `down_revision = None`. Alembic walks the graph to compute the ordered upgrade/downgrade steps between the DB's current revision and the requested target.

### 1.2 Version tracking: the `alembic_version` table

Alembic records the database's position in a dedicated table named **`alembic_version`** (configurable via `version_table`). In offline output it emits exactly:

```sql
CREATE TABLE alembic_version (
  version_num VARCHAR(32) NOT NULL,
  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
```

With multiple heads, the table holds **multiple rows**, one per head. Alembic reads the current `version_num`(s), locates that node in the script graph, computes the path to the target (`head`, a specific revision, `+1`/`-1`, or `base`), and after each step issues `UPDATE alembic_version` (or `INSERT`/`DELETE` for branch changes). The `ensure_version` command — confirmed in the Commands API as "Create the alembic version table if it doesn't exist already" and "Added in version 1.7.6" — creates the table without running migrations.

### 1.3 Migration script structure: `upgrade()` / `downgrade()`

```python
def upgrade():
    op.create_table('account', sa.Column('id', sa.Integer()), …)

def downgrade():
    op.drop_table('account')
```

`upgrade()` moves forward; `downgrade()` reverses. Alembic does not infer `downgrade()` — the developer or autogenerate must author it.

### 1.4 The CLI commands and semantics

- **`init`** — scaffolds the environment (script dir, `alembic.ini`, `env.py`, `script.py.mako`, `versions/`); supports templates (`generic`, `async`, `multidb`).
- **`revision -m "msg"`** — new empty migration linked to current head; `--autogenerate` diffs model metadata vs the live DB; `--head`, `--splice`, `--branch-label`, `--depends-on`, `--version-path`, `--rev-id`, `--sql`.
- **`upgrade <target>`** — runs `upgrade()` to target (`head`, `+1`, `<rev>`); `--sql` produces an offline script.
- **`downgrade <target>`** — runs `downgrade()` toward target (`-1`, `base`, `<rev>`).
- **`current`** — prints the stamped revision(s).
- **`history`** — chronological list; `--verbose`, `-r <range>`, `--indicate-current`.
- **`heads`** — all current heads (key branch detector).
- **`branches`** — branch-point revisions.
- **`merge <r1> <r2>`** — new revision with a `down_revision` tuple, reuniting branches.
- **`stamp <rev>`** — sets `alembic_version` **without running migrations**; baselines an existing DB; supports `base`, `heads`, `--purge`, multiple heads.
- **`show <rev>`** / **`edit <rev>`** — print / open a revision.
- **`check`** — (1.9+) non-zero exit if autogenerate has pending ops (CI gate).

### 1.5 Directory and file layout

```
project/
├── alembic.ini
└── alembic/
    ├── env.py           # runtime entrypoint, run on every command
    ├── script.py.mako   # template for new revision files
    └── versions/
```

`env.py` "is a Python script that is run whenever the alembic migration tool is invoked": it configures the engine, obtains a connection + transaction, wires `target_metadata` for autogenerate, and calls `context.run_migrations()`. It is fully customizable. `script.py.mako` defines generated-file boilerplate.

### 1.6 Configuration system

`alembic.ini` (configparser): key `sqlalchemy.url`; plus `script_location`, `prepend_sys_path`, `version_locations`, `path_separator`, `revision_environment`, `sourceless`, `truncate_slug_length`, `output_encoding`, timezone, and standard Python logging sections consumed by `logging.config.fileConfig()`. Programmatic usage: `Config("alembic.ini")` + `command.upgrade(cfg, "head")`. Multiple lineages via `--name`.

### 1.7 Operations (`op`) interface and contexts

`op` exposes dialect-agnostic directives — `create_table`, `add_column`, `drop_column`, `create_index`, `create_unique_constraint`, `alter_column`, `execute`, `bulk_insert`. The **MigrationContext** "handles the actual work to be performed against a database backend," owning the connection, dialect, and version-table logic. The **EnvironmentContext** is what `env.py` interacts with. Custom ops register via `Operations.register_operation()` / `implementation_for()`.

### 1.8 Autogenerate and its limits

`revision --autogenerate` compares the model `MetaData` (passed via `target_metadata`) against the reflected live schema and emits candidate `op.*` directives. It detects added/removed tables and columns, index/unique-constraint changes, and (with `compare_type=True`/`compare_server_default=True`) types/defaults. Limits: candidates must be reviewed/hand-edited; it cannot detect renames (sees drop+add); weak on some constraint/default comparisons; no data migrations.

### 1.9 Offline (`--sql`) vs online mode

Online connects, reads `alembic_version`, executes. Offline (`--sql`) "generate[s] migrations as SQL scripts, instead of running them against the database" — critical when DDL access is restricted. Offline cannot read `alembic_version`, so it defaults to `base`; a start point uses `start:end` syntax. Emitted scripts include the version updates.

### 1.10 Transactions and rollback per migration

On transactional-DDL backends, the whole run is one transaction by default. `transaction_per_migration=True` wraps **each revision** separately, so "if one fails you want to roll-back that one but not all the previous versions that succeeded." On non-transactional-DDL backends a failure can leave the schema partially applied; some ops (e.g. `CREATE INDEX CONCURRENTLY`) must run outside a transaction. The version update commits only on success.

### 1.11 Branch labels, `depends_on`, multiple streams

Shared parents branch the graph (`heads` reports >1 tip); `merge` reunites them. **Branch labels** name a stream (`networking@head`). **`depends_on`** enforces ordering without making a revision a `down_revision` parent. Fully independent lineages use multiple `version_locations` / `--name` configs.

---

# Part 2 — FalkorDB Framework Concept & Design

### 2.1 Verified FalkorDB capabilities

**Index types (three).** Per the FalkorDB docs: "FalkorDB supports three index types: Range indexes for exact-match and comparison filters, Full-text indexes for text search with stemming and scoring, and Vector indexes for similarity search on embeddings." Verified syntax:

- **Range:** `CREATE INDEX FOR (p:Person) ON (p.age)` / `CREATE INDEX FOR ()-[f:FOLLOW]->() ON (f.created_at)`. Drop: `DROP INDEX ON :Person(age)`. Covers string, numeric, geospatial scalars and scalar-array membership; "Complex types like nested arrays, maps, or vectors are not supported for range indexing."
- **Full-text** (RediSearch, procedure-based): `CALL db.idx.fulltext.createNodeIndex('Movie', 'title')`, map form `CALL db.idx.fulltext.createNodeIndex({label:'Movie', language:'German', stopwords:[…]}, 'title')`, phonetic option supported. Drop: `DROP FULLTEXT INDEX FOR ()-[m:Manager]-() ON (m.name)`.
- **Vector** (HNSW): `CREATE VECTOR INDEX FOR (p:Product) ON (p.description) OPTIONS {dimension:128, similarityFunction:'euclidean'}` (also `cosine`; optional `M` default 16, `efConstruction` default 200, `efRuntime` default 10). Drop: `DROP VECTOR INDEX FOR (p:Product) (p.description)`.

**Constraint types (two).** "FalkorDB supports two types of constraints: Mandatory constraints · Unique constraints." Managed by Redis commands, not Cypher: `GRAPH.CONSTRAINT CREATE key MANDATORY|UNIQUE NODE label | RELATIONSHIP reltype PROPERTIES propCount prop […]` and symmetric `DROP`. Critical rules:
- A unique constraint **requires a pre-existing exact-match (range) index** on the same properties, or it fails synchronously.
- "Trying to delete an index that supports a constraint will fail" — downgrades must drop the constraint *before* the index.
- Constraint creation is **asynchronous**: the command replies `PENDING`; status moves `UNDER CONSTRUCTION → OPERATIONAL`, or `FAILED` if existing data conflicts. (A real-world FalkorDB GitHub issue documented a crash enforcing a unique constraint over dirty data — reinforcing the need to validate before applying.)
- Unique constraints are not enforced on array-valued properties or when any constrained property is null.

**Introspection.** `CALL db.indexes()` (and `falkordb-py`'s `graph.list_indices().result_set`) returns index type (RANGE/FULLTEXT/VECTOR), entity type, labels, properties. Constraints via `graph.ro_query("CALL db.constraints()")` (type, entity type, label/reltype, properties, status). Schema enumeration: `CALL db.labels()`, `CALL db.relationshipTypes()`, `CALL db.propertyKeys()`.

**Python client (`falkordb-py`, package `FalkorDB`, current `1.6.1` on PyPI).** Verified surface: `db = FalkorDB(host, port[, password])` / `FalkorDB.from_url(...)`; `g = db.select_graph(name)`; `g.query(cypher[, params])`, `g.ro_query(...)` returning `.result_set`; `g.copy(new_name)`; `g.delete()`; `g.explain(...)`; client-level `db.create_constraint(graph_key, type, entity, label, [props])` and `db.drop_constraint(...)` (graph key is the first arg); `db.list_graphs()`; `db.config_get/set`. Crucially, **`db.connection` is the raw redis-py client** (`decode_responses=True`) and `db.execute_command(...)` is available — enabling both `GRAPH.CONSTRAINT` commands and ordinary Redis `SET/GET`. There is **no dedicated `create_index` helper**; indexes are created via `g.query("CREATE INDEX …")`, which returns immediately with an "Indices created" count.

**Atomicity reality (the defining constraint).** A single `GRAPH.QUERY` and a single `GRAPH.CONSTRAINT` command are each atomic, but FalkorDB provides **no multi-statement transaction across the graph** comparable to SQL `BEGIN…COMMIT`, and **no transactional DDL** and **no `ALTER`**. FalkorDB's own materials frame the engine as favoring latency over "strict transactional semantics," and the client spec states transactional behavior is left to the client implementer; Redis `MULTI/EXEC` queues commands but gives no graph-level rollback over partial Cypher effects. Other relevant limits: queries target a single graph (no cross-graph queries); eager ops (`CREATE/SET/DELETE/MERGE`) ignore `LIMIT`; indexes are not used for `<>` filters. `GRAPH.COPY` duplicates an entire graph including indexes and constraints, and "while the copy is performed the src graph is fully accessible" — the basis for snapshot rollback.

### 2.2 Concept mapping: Alembic → FalkorMigrate

| Alembic concept | FalkorMigrate equivalent | Notes / gap |
|---|---|---|
| `alembic_version` table | Singleton `(:_FalkorMigrateVersion {revision, applied_at})` node **inside the target graph**; optional Redis-key mode | No tables exist; a node travels with `GRAPH.COPY`/dumps, a Redis key does not — node is default. |
| Revision id (random hex) | Same: 12-char hex token, prefix-referenceable | Identical. |
| `down_revision` / DAG / heads / base | Identical graph stored in file headers | Ports cleanly. |
| `upgrade()` / `downgrade()` | `upgrade()` / `downgrade()` with Cypher + `op.*` | `downgrade` often impossible for data transforms → `irreversible` marker. |
| `op.create_table` / `add_column` | *No equivalent* — graph is schema-optional | Labels/properties materialize on write; nothing to "create." |
| `op.create_index` / `create_unique_constraint` | `op.create_range/fulltext/vector_index`, `op.create_constraint` | Direct, verified syntax. |
| `op.execute(sql)` | `op.run_cypher(query, params)` / `op.run_command(*args)` | Core escape hatch. |
| `op.alter_column` (rename) | `op.rename_property` / `op.relabel_nodes` | Pure data rewrites; expensive, non-atomic. |
| `env.py` / `alembic.ini` | `env.py` / `falkormigrate.ini` (`falkordb.url`) | Same roles. |
| Transaction-per-migration | Stamp-after-success + optional `GRAPH.COPY` snapshot | No native transaction. |
| Offline `--sql` | `--preview` (emit ordered statements, no execution) | Cannot pre-read version. |
| Autogenerate (full schema diff) | Partial: **indexes + constraints only** | Node/relationship "schema" implicit → not diffable. |

### 2.3 Version tracking design

Default singleton metadata node per graph:

```cypher
MERGE (v:_FalkorMigrateVersion {singleton: true})
SET v.revision = $rev, v.applied_at = timestamp()
```

Read with `MATCH (v:_FalkorMigrateVersion) RETURN v.revision`. Multiple heads → a list property `v.revisions`. Rationale for node over Redis key: it lives *inside* the graph, so it is included by `GRAPH.COPY` and dumps/exports, keeping version and data consistent during backup/restore — the same property that makes `alembic_version` live with the data. Autogenerate/data scans must exclude `:_FalkorMigrateVersion`. An optional key-backed mode (`db.connection.set(...)`) exists for read-only-graph scenarios but is non-default because it can desync from `GRAPH.COPY`.

### 2.4 What "migrations" mean for a graph DB

(a) **Index lifecycle** (range/full-text/vector create+drop); (b) **constraint lifecycle** (unique/mandatory, with automatic index-prerequisite handling); (c) **bulk data transformations** — rename property (`MATCH (n:Label) SET n.newName = n.oldName REMOVE n.oldName`), relabel nodes, restructure relationships (e.g. reify a relationship into a node), backfill/compute properties; (d) **reference/seed data** via idempotent `MERGE`. Because eager ops ignore `LIMIT` and large rewrites are non-atomic, data transforms should be **idempotent and batched** (client-side pagination over `WHERE` ranges) so a failed run is safely re-runnable.

### 2.5 Rollback / downgrade strategy (tiered)

1. **Author an explicit `downgrade()`** for reversible structural ops (drop a created index/constraint, rename a property back). Default; mirrors Alembic.
2. **Snapshot-and-restore** for risky data migrations: before `upgrade()`, optionally `GRAPH.COPY <graph> <graph>__premig_<rev>`; restore by copying back on downgrade/failure. True rollback at the cost of memory/time; opt-in per migration (`snapshot=True`).
3. **Irreversible marker:** `irreversible = True` raises a clear error on attempted downgrade, directing the operator to restore from snapshot/backup — the honest equivalent of a one-way data migration, preventing silent data loss.

### 2.6 Making migrations testable

- **Ephemeral instance:** `docker run --rm -p 6379:6379 falkordb/falkordb:latest`, or the embedded `falkordblite` package — which FalkorDB's docs explicitly recommend for CI: "FalkorDBLite is ideal for CI/CD because it requires no external server setup. Install with pip install falkordblite, create a temporary database, run tests, and the process cleans up automatically" (current `falkordblite` 0.10.0). Each test gets a uniquely-named graph.
- **Round-trip test:** apply `upgrade()` then `downgrade()` and assert the graph (entities + `CALL db.indexes()` + `CALL db.constraints()`) returns to its prior state — the same comparison FalkorDB's own `GRAPH.COPY` test performs ("entities, schema, indices, and constraints" match).
- **Idempotency check:** run `upgrade()` twice on a fresh graph; the second must be a no-op (enforced by `MERGE`/guarded Cypher); flag any change in entity/index/constraint counts.
- **Dry-run/preview:** `--preview` prints ordered statements without executing.
- **Fixtures:** seed Cypher loaded before a migration test.

### 2.7 Gaps vs Alembic and workarounds

| Missing in FalkorDB | Impact | Workaround |
|---|---|---|
| Tables / `CREATE TABLE` | No structural object to create | Schema implicit; migrations manage only indexes, constraints, data. |
| `ALTER TABLE` / column rename | No in-place schema change | Property rename = batched, idempotent Cypher `SET`/`REMOVE`. |
| Transactional DDL / multi-statement transactions | Multi-query migration is **not atomic** | Stamp version only after all steps succeed; offer `GRAPH.COPY` snapshot; idempotent re-runnable steps; small single-purpose migrations. |
| Server-side rollback of partial migration | Failure leaves graph half-changed | Snapshot before risky migrations; restore on failure; surface partial state clearly. |
| Full schema reflection | Autogenerate can't diff node/relationship shape | Limit autogenerate to indexes/constraints. |
| Synchronous constraint creation | Constraint may still be building/`FAILED` | Poll `CALL db.constraints()` to `OPERATIONAL`; fail on `FAILED`. |

### 2.8 Revision graph and chaining (adapted)

Structurally identical to Alembic. The framework loads `versions/`, builds the DAG, reads the current revision from `:_FalkorMigrateVersion`, and computes the path. Multiple heads stored as a list. Because FalkorDB is natively multi-graph/multi-tenant (each `select_graph` is isolated), FalkorMigrate supports the "multiple independent bases" case by configuring one version lineage per target graph — a clean fit for per-tenant knowledge graphs.

### 2.9 Is autogenerate feasible?

**Partially — and only for indexes and constraints.** FalkorDB is schema-optional: labels, relationship types, and properties materialize implicitly on write, so there is no declared structure to diff. But indexes/constraints are introspectable (`CALL db.indexes()`, `CALL db.constraints()`). Autogenerate is therefore feasible if the developer supplies a **declarative target-schema manifest** (the `target_metadata` analogue) listing desired indexes/constraints; the framework introspects, diffs, and emits candidate `op.*` directives for review. **Limits:** cannot detect renames (drop+add), cannot infer node/relationship structure, cannot generate data migrations, and must special-case the unique-constraint→index ordering. Strictly a *nice-to-have* Phase 4 feature.

### 2.10 Transaction and atomicity contract

- **Version stamp written only after the final migration step succeeds** (mirroring Alembic committing the version row last); a mid-migration failure leaves the prior revision stamped and reports a partial state.
- **Per-migration boundary, not per-step rollback** (like Alembic's `transaction_per_migration`), but with no automatic reversal — the safety net is the optional snapshot.
- **Snapshot for risky migrations** via `GRAPH.COPY` (source stays fully accessible), restored on failure/downgrade.
- **Idempotency mandatory** for data steps (`MERGE`, guarded `MATCH … WHERE n.x IS NULL SET …`, create-index-if-absent).
- **Constraint async handling:** poll `CALL db.constraints()` to `OPERATIONAL`/`FAILED` before stamping success.

---

# Part 3 — Concrete Artifacts & Phased Implementation Plan

### 3.1 Directory layout & configuration

```
project/
├── falkormigrate.ini            # or [tool.falkormigrate] in pyproject.toml
└── falkormigrate/
    ├── env.py
    ├── script.py.mako
    └── versions/
```

```ini
[falkormigrate]
script_location = falkormigrate
falkordb.url = falkor://localhost:6379
falkordb.graph = social
version_strategy = node          ; node | redis_key
snapshot_on_data_migration = false
prepend_sys_path = .
```

`env.py` (customizable runtime hook):

```python
from falkormigrate import context
from falkordb import FalkorDB

def run_migrations_online():
    cfg = context.config
    db = FalkorDB.from_url(cfg.get("falkordb.url"))
    graph = db.select_graph(cfg.get("falkordb.graph"))
    context.configure(connection=db, graph=graph,
                      version_strategy=cfg.get("version_strategy", "node"))
    context.run_migrations()

if context.is_preview_mode():
    context.configure(url=context.config.get("falkordb.url"),
                      output_buffer=context.preview_stream)
    context.run_migrations()
else:
    run_migrations_online()
```

Programmatic API: `from falkormigrate.config import Config; from falkormigrate import command; command.upgrade(Config("falkormigrate.ini"), "head")`.

### 3.2 Migration template (`script.py.mako`)

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from falkormigrate import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
irreversible = False
snapshot = False        # set True to GRAPH.COPY before upgrade()

def upgrade():
    pass

def downgrade():
    pass
```

Example:

```python
def upgrade():
    op.create_range_index("Person", "email")                       # CREATE INDEX FOR (p:Person) ON (p.email)
    op.create_constraint("UNIQUE", "NODE", "Person", ["email"])    # auto-ensures the index first
    op.rename_property("Person", "fname", "first_name")            # batched, idempotent

def downgrade():
    op.rename_property("Person", "first_name", "fname")
    op.drop_constraint("UNIQUE", "NODE", "Person", ["email"])      # drop constraint BEFORE index
    op.drop_range_index("Person", "email")
```

### 3.3 The `op` operations API

| `op` method | Emits | Notes |
|---|---|---|
| `op.run_cypher(query, params=None)` | `graph.query(...)` | `op.execute` analogue. |
| `op.run_command(*args)` | `db.execute_command(...)` | Raw Redis/`GRAPH.*`. |
| `op.create_range_index(label, prop, rel=False)` | `CREATE INDEX FOR (n:label) ON (n.prop)` | Synchronous. |
| `op.drop_range_index(label, prop, rel=False)` | `DROP INDEX ON :label(prop)` | Fails if a constraint depends on it. |
| `op.create_fulltext_index(label, *props, **opts)` | `CALL db.idx.fulltext.createNodeIndex(...)` | language/stopwords/phonetic. |
| `op.drop_fulltext_index(label, *props)` | `DROP FULLTEXT INDEX FOR …` | |
| `op.create_vector_index(label, prop, dimension, similarity, **opts)` | `CREATE VECTOR INDEX … OPTIONS {…}` | `dimension`+`similarityFunction` required. |
| `op.drop_vector_index(label, prop)` | `DROP VECTOR INDEX FOR (n:label) (n.prop)` | |
| `op.create_constraint(kind, entity, label, props)` | auto-`CREATE INDEX` if UNIQUE, then `GRAPH.CONSTRAINT CREATE`; **polls to `OPERATIONAL`** | Raises on `FAILED`. |
| `op.drop_constraint(kind, entity, label, props)` | `GRAPH.CONSTRAINT DROP` | |
| `op.rename_property(label, old, new, batch=10000)` | batched guarded `SET`/`REMOVE` | Idempotent. |
| `op.relabel_nodes(old, new, batch=10000)` | batched `SET n:new REMOVE n:old` | |
| `op.seed(merge_query, rows)` | `UNWIND $rows AS row MERGE (…)` | Idempotent reference data. |
| `op.snapshot()` / `op.restore_snapshot()` | `GRAPH.COPY` | Used when `snapshot=True`. |

### 3.4 The CLI (`falkormigrate …`)

| Command | Behavior | Phase |
|---|---|---|
| `init <dir>` | Scaffold ini/env/template/versions | 0 |
| `revision -m "msg"` | New revision on current head (`--head`, `--splice`, `--branch-label`, `--depends-on`, `--preview`) | 0 |
| `upgrade <target>` | Apply `upgrade()` to `head`/`+1`/`<rev>`; `--preview` | 0 |
| `downgrade <target>` | Apply `downgrade()` to `-1`/`base`/`<rev>`; refuses to cross `irreversible` without `--force` | 0 |
| `current` | Print version node revision(s) | 0 |
| `history` | Chronological list (`--verbose`, `--indicate-current`) | 1 |
| `heads` | All head revisions (branch detector) | 1 |
| `branches` | Branch-point revisions | 1 |
| `stamp <rev>` | Set version node without running (`base`/`heads`/`--purge`) | 1 |
| `show <rev>` | Revision details | 1 |
| `test <rev>` | Round-trip + idempotency check on ephemeral graph | 3 |
| `merge <r1> <r2> -m` | Merge revision (`down_revision` tuple) | 4 |
| `revision --autogenerate` | Diff manifest vs live indexes/constraints | 4 |
| `check` | Non-zero exit if pending autogen ops (CI gate) | 4 |

### 3.5 Phased plan

**Phase 0 — MVP runner (essential).** *Goal:* version tracking + linear upgrade/downgrade + revision creation + minimal CLI. *Deliverables:* `Config` loader; `env.py`/`script.py.mako`; linear `ScriptDirectory`; `MigrationContext` over `falkordb-py`; `:_FalkorMigrateVersion` read/write; minimal `op` (`run_cypher`, `run_command`, range-index create/drop, constraint create/drop). *CLI:* `init`, `revision`, `upgrade`, `downgrade`, `current`. *Deps:* `falkordb`, `mako`, `typer`/`click`.

**Phase 1 — Revision graph & inspection (essential).** *Goal:* full DAG + baselining. *Deliverables:* DAG builder; path computation (`+N`/`-N`/rev/`base`); multi-head list storage; `stamp`. *CLI:* `history`, `heads`, `branches`, `show`, `stamp`. *Deps:* Phase 0.

**Phase 2 — Operations API & preview (essential→nice-to-have).** *Goal:* complete `op` + review tooling. *Deliverables:* full-text/vector ops; `rename_property`/`relabel_nodes`/`seed` (batched, idempotent); constraint async status polling; `--preview` serialization; `irreversible` enforcement. *CLI:* `--preview`. *Deps:* Phases 0–1.

**Phase 3 — Testing & safe rollback (essential for "testable + rollbackable").** *Goal:* first-class testability + snapshot safety. *Deliverables:* ephemeral fixtures (Docker / `falkordblite`); `test` command (upgrade→downgrade→re-upgrade parity on entities/indexes/constraints); idempotency double-apply; `snapshot=True` wiring `GRAPH.COPY` + auto-restore; pytest plugin. *CLI:* `test`. *Deps:* Phases 0–2 + Docker/`falkordblite`.

**Phase 4 — Autogenerate & branching (nice-to-have).** *Goal:* convenience for larger teams. *Deliverables:* declarative index/constraint manifest; diff engine over `CALL db.indexes()`/`db.constraints()` → candidate `op.*` (rename + ordering caveats); `merge`/branch labels/`depends_on`; `check` CI gate; post-gen hooks (Black). *CLI:* `revision --autogenerate`, `merge`, `check`. *Deps:* Phases 0–3. Optional — framework is fully usable without it.

---

# Recommendations

1. **Ship Phase 0 first and use it in anger before adding anything.** A linear runner with the version node, `upgrade`/`downgrade`/`current`/`revision`, and an `op` limited to `run_cypher` + range-index + constraint covers the majority of real FalkorDB schema work (indexes and constraints). Resist building the DAG, branching, or autogenerate until the linear core has run real migrations against a staging graph.
2. **Make the version pointer a node, not a Redis key, by default.** It is the single most important design decision for correctness: a node travels with `GRAPH.COPY`, dumps, and replication, so version and data never desynchronize. Offer the key-backed mode only as an explicit opt-in.
3. **Treat idempotency and "stamp-after-success" as non-negotiable invariants of the runner**, since FalkorDB cannot roll back a partially-applied multi-query migration. Every data-transform helper (`rename_property`, `relabel_nodes`, `seed`) must be batched and re-runnable, and the version is updated only after the last step returns cleanly.
4. **Wire `GRAPH.COPY` snapshotting into Phase 3, gated per-migration (`snapshot=True`).** This is the only mechanism that delivers true rollback for irreversible data transforms; make it cheap to opt into and document its memory/time cost for large graphs.
5. **Build the constraint helper to poll `CALL db.constraints()` to `OPERATIONAL` and to auto-create the prerequisite range index for unique constraints.** These two FalkorDB-specific behaviors (async creation, mandatory backing index, and "cannot drop an index a constraint depends on") are the most common sources of silent migration failure; encode them in the `op` layer, not in user migrations.
6. **Use `falkordblite` for the test harness and CI**, with Docker as the alternative for integration parity. The embedded library is purpose-built for "no external server setup" CI and auto-cleanup.
7. **Scope autogenerate narrowly or skip it.** Only indexes and constraints are introspectable; promise nothing about node/relationship structure or renames. If team size doesn't justify it, omit Phase 4 entirely — the framework remains "lightweight" and complete without it.

**Thresholds that change the plan:** If migrations routinely involve large data rewrites (>1M nodes), elevate snapshotting and batching from Phase 3 to Phase 0/2 and add progress/resume support. If multiple developers create migrations concurrently, pull branching/`merge` (Phase 4) forward. If the project runs many isolated tenant graphs, prioritize the per-graph lineage configuration (a multi-`--name`/multi-config analogue) early.

# Caveats

- **Version specifics, as of late May 2026:** Alembic 1.18.4; FalkorDB Python client `FalkorDB` 1.6.1; `falkordblite` 0.10.0. FalkorDB itself requires Redis 8.0+ for current releases (earlier docs cited 7.4). API surface (especially `falkordb-py` internal helpers and the exact column names yielded by `db.indexes()`/`db.constraints()`) can shift between minor versions — pin versions and verify introspection output against a live instance before building the autogenerate diff engine.
- **`db.indexes()` / `db.constraints()` field names were not fully verifiable from public documentation** (the docs paraphrase fields and elide example output). The design treats these as introspectable and reads type/entity-type/label/properties/status, but the implementer must confirm exact yielded column names against a running FalkorDB instance.
- **The atomicity model is fundamentally weaker than Alembic's on transactional-DDL databases.** There is no graph-level transaction; the framework's guarantees rest on stamp-after-success, idempotency, and optional snapshots — not on database rollback. Operators must understand a failed multi-step migration can leave a graph in a partial state requiring snapshot restore.
- **Unique constraints over dirty data can fail or, per at least one historical FalkorDB GitHub issue, have triggered server crashes when enforcing over invalid string values.** Validate/clean data (a preceding migration step) before adding constraints, and always test constraint migrations against production-like data on an ephemeral instance.
- **Autogenerate is intentionally partial** and shares Alembic's documented inability to detect renames; all generated output is "candidate" code requiring human review. It can never generate data migrations.
- **Naming/branding ("FalkorMigrate") is illustrative.** The design is the contribution; verify there is no existing official FalkorDB migration tool before publishing under any specific name.
- Some performance/operational characteristics cited (snapshot cost on large graphs, replication semantics) come from FalkorDB marketing/blog and comparison pages rather than formal specs; treat them as directional and benchmark on your own data.