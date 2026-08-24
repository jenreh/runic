# Supported Drivers

Runic's OGM is database-agnostic. Every backend is hidden behind the
`GraphDriver` /
`AsyncGraphDriver` Protocol so the rest of the
stack (Session, Repository, QueryBuilder) never talks to the database
directly.

Use `create_driver()` as the recommended
entry-point, or instantiate a driver class directly for advanced cases.

```python
from runic.ogm import create_driver

# FalkorDB
driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
# ArcadeDB (via Bolt)
driver = create_driver(
    "arcadedb", host="localhost", port=7687,
    database="mydb", username="root", password="secret",
)
# Neo4j
driver = create_driver(
    "neo4j", host="localhost", port=7687,
    database="neo4j", username="neo4j", password="secret",
)
# Memgraph
driver = create_driver(
    "memgraph", host="localhost", port=7687,
    database="memgraph", username="", password="",
)
# Apache AGE (PostgreSQL graph extension)
driver = create_driver(
    "age", host="localhost", port=5432,
    database="postgres", graph="my_graph",
    username="postgres", password="secret",
)
# Amazon Neptune Database (Bolt, SigV4 IAM auth)
driver = create_driver(
    "neptune",
    endpoint="my-cluster.cluster-xxxx.eu-central-1.neptune.amazonaws.com",
    use_iam_auth=True, region="eu-central-1",
)
# Amazon Neptune Analytics (HTTPS via boto3)
driver = create_driver(
    "neptune_analytics", graph_id="g-abc123xyz", region="eu-central-1",
)
```

---

## Feature matrix

| Feature | FalkorDB | ArcadeDB | Neo4j | Memgraph | Apache AGE | Neptune Database | Neptune Analytics |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Protocol / client | Redis (falkordb) | Bolt (neo4j) | Bolt (neo4j) | Bolt (neo4j) | SQL (psycopg3) | Bolt (neo4j) + SigV4 (botocore) | HTTPS (boto3 `neptune-graph`) |
| Sync driver | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Async driver | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Vector KNN queries | ✓ — `CALL db.idx.vector.queryNodes` | ✓ — `CALL vector.neighbors` | ✓ — `CALL db.index.vector.queryNodes` | ✓ — `CALL vector_search.search` | ✗ — use pgvector | ✗ — Analytics-only feature | ✓ — `CALL neptune.algo.vectors.topK.byEmbedding` |
| Relationship alternation `[:A\|B]` | ✓ | ✓ | ✓ | ✓ | ✗ — no alternation in AGE's openCypher | ✓ | ✓ |
| Undirected `MERGE` (`merge_edge(directed=False)`) | ✗ — `NotImplementedError`; directed edges only | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `CALL … YIELD` (arbitrary procedures) | ✓ | ✗ | ✓ | ✓ | ✗ | ✗ | ✓ — built-in `neptune.algo.*` only |
| Fulltext search | ✓ — `db.idx.fulltext.queryNodes` | ✗ — not supported by ArcadeDB OGM driver | ✓ — `CALL db.index.fulltext.queryNodes` | ✓ — `CALL text_search.search_all` | ✗ — use PostgreSQL FTS | ✗ — use the OpenSearch integration | ✗ |
| String interning (`intern()`) | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| TypeConverter Cypher wrappers | ✓ — `vecf32()`, `toPoint()` | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| TLS / encrypted connections | ✗ — Redis, no TLS | ✗ — `bolt://` only | ✓ — `bolt+s://` | ✓ — `bolt+s://` | ✓ — via PostgreSQL SSL | ✓ — `bolt+s://` (required) | ✓ — HTTPS always |
| Multiple graphs per connection | ✓ — `select_graph()` | ✗ | ✗ | ✗ | ✓ — one graph per driver | ✗ — one graph per cluster | ✗ — driver bound to one graph id |
| ACID transactions | ✗ — each query is atomic | ✓ — `begin` / `commit` / `rollback` | ✓ — `begin` / `commit` / `rollback` | ✓ — `begin` / `commit` / `rollback` | ✓ — psycopg3 implicit `BEGIN` | ✓ — `begin` / `commit` / `rollback` | ✗ — each `ExecuteQuery` is atomic |
| Migrate adapter (`create_adapter`) | ✓ — `FalkorDBAdapter` | ✓ — `ArcadeDBAdapter` | ✓ — `Neo4jAdapter` | ✓ — `MemgraphAdapter` | ✓ — `AGEAdapter` | ✓ — `NeptuneAdapter` | ✓ — `NeptuneAdapter` |
| IndexManager DDL | ✓ — range / fulltext / vector / unique | ✓ — range / fulltext / unique (vector via HTTP API) | ✓ — range / fulltext / vector / unique (`IF NOT EXISTS`) | ✓ — range / text / vector / unique | ✗ — log.warning only (PostgreSQL-level DDL required) | ✗ — log.warning only (indexes are automatic) | ✗ — log.warning only (vector index fixed at graph creation) |
| Multi-label nodes | ✓ | ✓ | ✓ | ✓ | ✗ — emulated via `_labels` property | ✓ | ✓ |
| GeoLocation in-place update | ✓ — `SET n.geo = toPoint($v)` | ✗ — stored as `{latitude, longitude}` map | ✓ — `SET n.geo = point($v)` | ✓ — `SET n.geo = point($v)` | ✗ — agtype point not supported via psycopg | ✗ — stored as `{latitude, longitude}` map | ✓ — stored as `{latitude, longitude}` map |
| `relate()` on a `direction="BOTH"` relation | ✗ — the `MERGE` is written `OUTGOING` instead | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Required Python package | `falkordb` | `neo4j` | `neo4j` | `neo4j` | `psycopg[binary]` | `neo4j` + `botocore` | `boto3` |

::: tip Unsupported constructs are refused, not emitted
Where a backend cannot parse a construct, runic raises `NotImplementedError`
naming both the construct and the backend, rather than sending Cypher the
backend answers with a syntax error pointing at a character. The check runs when
a statement is compiled for a session — a `select()` statement does not know its
backend until then.
:::

---

## FalkorDB

**Supported**

- Sync (`FalkorDBDriver`) and async (`AsyncFalkorDBDriver`) execution.
- Full fulltext search via `CALL db.idx.fulltext.queryNodes()`.
- Vector KNN via `CALL db.idx.vector.queryNodes('Label', 'field', $k,
  vecf32($vec))` — the index procedure. FalkorDB rejects the `<->` distance
  operator in a `RETURN`, so runic never emits it.
- `Field()` options `interned=True`
  (wraps the value in `intern()` on write) and custom
  `TypeConverter` Cypher functions
  (e.g. `vecf32`, `toPoint`).
- Multiple named graphs on the same server via `graph=` parameter.

**Not supported / limitations**

- No TLS — FalkorDB communicates over Redis, which this driver does not
  encrypt.
- `AsyncFalkorDBDriver` requires an
  *async* FalkorDB graph handle; there is no built-in
  `create_async_falkordb_driver` factory — you must pass the handle
  yourself.

```python
from runic.ogm import create_driver, Session

driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")
with Session(driver) as session:
    ...

# Async — build the handle manually
from falkordb import FalkorDB
from runic.ogm.driver.falkordb import AsyncFalkorDBDriver

async_handle = FalkorDB(host="localhost", port=6379).select_graph("myapp")
async_driver = AsyncFalkorDBDriver(async_handle)
```

---

## ArcadeDB

ArcadeDB is accessed over the **Bolt protocol** using the `neo4j`
Python driver (`encrypted=False`).

**Supported**

- Sync execution via `BoltDriver`.
- Vector KNN via `CALL vector.neighbors('<type>[<field>]', $vec, $k) YIELD node, distance`.
- Standard `MATCH`/`MERGE`/`DELETE` Cypher queries.

**Not supported / limitations**

- **No async driver.**
- **No fulltext search** via the OGM query builder. The migrate adapter
  issues `CREATE FULLTEXT INDEX ON \`{label}\` (prop)` DDL where
  supported; ArcadeDB may accept or reject it depending on configuration.
- **No TypeConverter Cypher wrappers.** Raw Python values stored as-is.
- **Plaintext Bolt only.** `create_arcadedb_driver` forces `bolt://`.
- **No vector index DDL.** `create_vector_index()` logs a warning and
  directs you to the ArcadeDB HTTP management API.
- **No GeoLocation in-place update.** `SET n.geo = point($v)` is not
  supported via ArcadeDB's Bolt interface. `GeoLocation`
  values are stored and returned as a plain map (`{"latitude": …,
  "longitude": …}`). Updating the geo field requires re-saving the whole
  node. Tests marked `requires_geo_update` are automatically skipped for
  this backend (`ArcadeDBDialect.supports_geo_update = False`).

```python
from runic.ogm import create_driver, Session

driver = create_driver(
    "arcadedb",
    host="localhost", port=7687,
    database="mydb", username="root", password="playwithdata",
)
with Session(driver) as session:
    ...
```

---

## Neo4j

Neo4j is accessed over the **Bolt protocol** using the `neo4j` Python
driver.

**Supported**

- Sync execution via `BoltDriver`.
- Fulltext search via `CALL db.index.fulltext.queryNodes()`. The
  query uses an index named after the label (e.g. `Person`).
- Vector KNN via `CALL db.index.vector.queryNodes()`. A vector index
  named `{label}_{prop}` (e.g. `Article_embedding`) must exist.
- TLS via `bolt+s://` (set `encrypted=True`, the default).
- **Migrate adapter** (`create_adapter("neo4j", ...)`) — issues full
  DDL for all index/constraint types via `IF NOT EXISTS` for
  idempotency.
- **IndexManager** — pass a `Neo4jAdapter` to
  `IndexManager` to create indexes from your
  entity definitions:

  ```python
  from runic.migrate.adapters import create_adapter
  from runic.migrate import IndexManager

  adapter = create_adapter("neo4j", database="neo4j", password="secret")
  manager = IndexManager(adapter)
  manager.create_indexes(Person)   # issues CREATE INDEX / CONSTRAINT DDL
  ```

**Index naming convention** (Neo4j 5.x)

```text
fulltext:  CREATE FULLTEXT INDEX {label}  IF NOT EXISTS FOR (n:{label}) ON EACH [n.prop1, n.prop2]
range:     CREATE INDEX {label}_{prop}    IF NOT EXISTS FOR (n:{label}) ON (n.{prop})
vector:    CREATE VECTOR INDEX {label}_{prop}  IF NOT EXISTS FOR (n:{label}) ON (n.{prop})
unique:    CREATE CONSTRAINT {label}_{prop}_unique  IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE
```

**Not supported / limitations**

- **No async driver.**
- **No TypeConverter Cypher wrappers.**
- Vector index dimension is not stored in `Field()` metadata; pass
  `dimension` when calling `create_vector_index()` directly, or
  pre-create vector indexes via Cypher DDL.

```python
from runic.ogm import create_driver, Session

driver = create_driver(
    "neo4j",
    host="localhost", port=7687,
    database="neo4j", username="neo4j", password="secret",
    encrypted=True,
)
with Session(driver) as session:
    ...
```

---

## Memgraph

Memgraph is accessed over the **Bolt protocol** using the `neo4j`
Python driver, with Memgraph-specific `text_search` and
`vector_search` MAGE module procedures.

**Supported**

- Sync execution via `BoltDriver`.
- Fulltext search via `CALL text_search.search_all()`. Uses a
  whole-label text index named after the label (`CREATE TEXT INDEX
  {label} ON :{label}`).
- Vector KNN via `CALL vector_search.search()`. A vector index named
  `{label}_{prop}` must exist.
- TLS available (set `encrypted=True`).
- **Migrate adapter** (`create_adapter("memgraph", ...)`) — issues
  DDL for range, text, vector, and unique constraint creation.
- **IndexManager** — pass a `MemgraphAdapter` to
  `IndexManager`:

  ```python
  from runic.migrate.adapters import create_adapter
  from runic.migrate import IndexManager

  adapter = create_adapter("memgraph", database="memgraph")
  manager = IndexManager(adapter)
  manager.create_indexes(Post)    # issues CREATE INDEX / CONSTRAINT DDL
  ```

**Index naming convention** (Memgraph)

```text
text index: CREATE TEXT INDEX {label} ON :{label}         (whole-label; one per label)
range:      CREATE INDEX ON :{label}({prop})               (idempotent)
vector:     CREATE VECTOR INDEX {label}_{prop} ON :{label}({prop}) WITH CONFIG {...}
unique:     CREATE CONSTRAINT ON (n:{label}) ASSERT n.{prop} IS UNIQUE
```

::: info
Memgraph text indexes cover the **entire label** — a single text index
per label is created regardless of how many `index_type="FULLTEXT"`
fields are declared. Full-text queries search all string properties on
the node. Requires the MAGE `text_search` module.
:::

**Not supported / limitations**

- **No async driver.**
- **No TypeConverter Cypher wrappers.**
- Vector index dimension is not stored in `Field()` metadata; pass
  `dimension` when calling `create_vector_index()` directly, or
  pre-create vector indexes via Cypher DDL.

```python
from runic.ogm import create_driver, Session

driver = create_driver(
    "memgraph",
    host="localhost", port=7687,
    database="memgraph", username="", password="",
)
with Session(driver) as session:
    ...
```

---

## Apache AGE

[Apache AGE](https://age.apache.org/) is a **PostgreSQL extension** that
adds openCypher graph query support to an existing PostgreSQL database.
Cypher queries are executed via the `cypher()` SQL function wrapped in a
`SELECT` statement:

```text
SELECT * FROM cypher('graph_name', $$ CYPHER $$ [, params::agtype])
    AS (col0 agtype, ...);
```

The runic driver uses **psycopg3** (`psycopg[binary]`) for the
PostgreSQL connection and handles the `cypher()` wrapping automatically.
Parameters are serialised as an agtype JSON map and passed as the third
argument to `cypher()`, making them available inside the Cypher query as
`$param_name` — identical to how runic's QueryBuilder emits `$p0`,
`$p1`, etc.

**Supported**

- Sync execution via `AGEDriver`.
- Automatic agtype decoding — vertices and edges are returned as
  `AGENode` /
  `AGEEdge` wrappers.
- Standard `MATCH`/`MERGE`/`DELETE` Cypher queries.
- Automatic graph creation on first connect (if the graph does not exist).
- TLS — supported via PostgreSQL SSL (pass SSL keyword arguments directly
  to `psycopg.connect` by instantiating
  `AGEDriver` manually).

**Not supported / limitations**

- **No async driver.** Async support requires an async psycopg3 connection
  which is not yet wired up.
- **No multi-label nodes.** AGE stores each vertex under exactly one
  PostgreSQL table (one label). The OGM emulates multi-label hierarchies by
  injecting a `_labels` array property on `CREATE` and filtering with
  `WHERE "SubLabel" IN n._labels` on queries. Tests requiring true
  multi-label behaviour (`@pytest.mark.requires_multi_label`) are
  automatically skipped for this backend
  (`AGEDriver.supports_multi_label = False`).
- **No GeoLocation in-place update.** AGE's agtype does not expose a
  `point()` constructor via the psycopg3 interface.
  `GeoLocation` values are stored as a plain
  agtype map (`{"latitude": …, "longitude": …}`) and read back the same
  way. Re-saving the full node is required to update geo coordinates.
- **No fulltext search** in Cypher. Use PostgreSQL `tsvector`/`tsquery`
  full-text search directly on the underlying tables.
- **No vector KNN** in Cypher. Use [pgvector](https://github.com/pgvector/pgvector) on the underlying tables.
- **No TypeConverter Cypher wrappers** (no `vecf32()`, `intern()`).
- **No index DDL** in runic's migration adapter. AGE does not expose
  Cypher-level index creation; create PostgreSQL indexes on the underlying
  `ag_label` tables directly.

```python
from runic.ogm import create_driver, Session

driver = create_driver(
    "age",
    host="localhost",
    port=5432,
    database="postgres",
    graph="my_graph",
    username="postgres",
    password="secret",
)
with Session(driver) as session:
    ...
```

**Prerequisites** — the `age` extension must be installed in PostgreSQL:

```sql
-- run once as superuser
CREATE EXTENSION IF NOT EXISTS age;
```

The runic driver runs `LOAD 'age'` and sets
`search_path = ag_catalog, "$user", public` automatically on every new
connection.

---

## Amazon Neptune Database

[Amazon Neptune Database](https://aws.amazon.com/neptune/) is AWS's managed
graph database. It speaks openCypher over the **Bolt protocol** (cluster
endpoint, default port 8182), so runic reuses `BoltDriver` with a
Neptune-specific dialect.

::: warning Not yet live-verified
Neptune is **VPC-only** and has no local emulator, so this backend is
implemented against AWS's documented behaviour but has not yet been validated
against a live cluster. The endpoint must be reachable from where your code
runs (in-VPC deployment, VPN, or bastion).
:::

**Supported**

- Sync execution via `BoltDriver`, including explicit
  `begin` / `commit` / `rollback` transactions.
- **IAM (SigV4) authentication** — the default. `create_neptune_driver`
  installs a refreshing auth manager that re-signs the token before AWS's
  ~5-minute signature expiry and re-signs again after auth errors (requires
  `botocore` and resolvable AWS credentials). For clusters with IAM database
  authentication disabled, pass `use_iam_auth=False` — Neptune then ignores
  the Bolt auth parameters entirely.
- TLS is always on (`bolt+s://`) — Neptune requires it.
- **String node IDs** — Neptune's `id()` returns strings (UUIDs when
  auto-assigned); the dialect never casts to integer.
- **Migrate adapter** (`create_adapter("neptune", ...)`) — version and
  checksum tracking via plain Cypher.

**Not supported / limitations**

- **No async driver.**
- **No `CALL … YIELD`** for arbitrary procedures.
- **No fulltext search** in Cypher — Neptune integrates with Amazon
  OpenSearch Service instead.
- **No vector search** — vector similarity is a Neptune Analytics feature.
- **No index or constraint DDL.** Neptune manages indexes automatically; the
  migrate adapter logs a warning and continues.
- **No TypeConverter Cypher wrappers.** `GeoLocation` is stored as a
  `{"latitude": …, "longitude": …}` map.
- `shortestPath()` / `allShortestPaths()`, user-defined functions, the `^`
  operator, and non-static `SKIP`/`LIMIT` are rejected by Neptune's
  openCypher implementation.

```python
from runic.ogm import create_driver, Session

driver = create_driver(
    "neptune",
    endpoint="my-cluster.cluster-xxxx.eu-central-1.neptune.amazonaws.com",
    port=8182,
    use_iam_auth=True,
    region="eu-central-1",
)
with Session(driver) as session:
    ...
```

::: info IAM auth connection lifetime
SigV4 signatures expire after about five minutes. runic re-signs on every new
Bolt connection, but a long-pooled connection past the 10-day server limit or
an aborted handshake will surface as an auth error — the auth manager then
invalidates its token and the driver retries with a fresh signature.
:::

---

## Amazon Neptune Analytics

[Amazon Neptune Analytics](https://aws.amazon.com/neptune/) is a separate
product from Neptune Database: an in-memory graph engine with **no Bolt
endpoint**. runic talks to it over HTTPS through the `neptune-graph` AWS API
(`boto3`), which handles SigV4 authentication itself.

::: warning Not yet live-verified
Implemented against AWS's documented behaviour but not yet validated against
a live graph — Neptune Analytics has no local emulator.
:::

**Supported**

- Sync execution via `NeptuneAnalyticsDriver` — each query is one
  `ExecuteQuery` request, individually atomic.
- **Native vector KNN** via
  `CALL neptune.algo.vectors.topK.byEmbedding(...)`, with the node label
  applied as a `vertexFilter`. The yielded `score` is a squared Euclidean
  distance — lower is closer, matching runic's ascending `__score` ordering.
- `CALL … YIELD` for the built-in `neptune.algo.*` procedures.
- **String node IDs**, multi-label nodes, undirected `MERGE`.
- **Migrate adapter** (`create_adapter("neptune_analytics", ...)`) — version
  and checksum tracking via plain Cypher.

**Not supported / limitations**

- **No async driver.**
- **No explicit transactions** — like FalkorDB, every query is atomic on its
  own; `Session.commit()` batches nothing at the database level.
- **No fulltext search** in Cypher.
- **One vector index per graph**, its dimension fixed at graph creation.
  runic's per-field vector model maps onto it loosely: the field name is
  ignored and only the label filter narrows results.
- **`Vector` fields are auto-synced into the vector index.** Embeddings live
  in a dedicated index, not in node properties, so whenever a Session write
  stores a `Vector` field the mapper appends
  `CALL neptune.algo.vectors.upsert(n, $embedding)` to the same statement —
  the property and the index stay in sync with no extra round trip:

  ```python
  from runic.ogm import Session, Vector, create_driver

  driver = create_driver(
      "neptune_analytics", graph_id="g-abc123xyz", region="eu-central-1"
  )
  with Session(driver) as session:
      article = Article(title="Graphs!", embedding=Vector([0.1, 0.2, 0.3]))
      session.add(article)
      session.commit()   # node written AND indexed for vector search
  ```

  Two caveats: the graph must have been created with a
  `vectorSearchConfiguration` whose dimension matches (pass
  `sync_vectors=False` to the driver for graphs without one — writes with
  `Vector` fields would otherwise fail), and writes that bypass the Session's
  entity mapper (raw `session.execute`, the query-builder write pipeline)
  still need a manual `driver.upsert_vector(node_id, embedding)`.
- **No index or constraint DDL** — the vector index is configured when the
  graph is created (`vectorSearchConfiguration`), and everything else is
  automatic.

---

## Generic Bolt (custom backends)

`BoltDriver` can connect to **any
Bolt-compatible graph database** by supplying a custom
`GraphDialect`.

```python
from runic.ogm.driver.bolt import BoltDriver
from myapp.dialects import MyDialect

driver = BoltDriver.from_params(
    host="localhost",
    port=7687,
    database="neo4j",
    username="neo4j",
    password="secret",
    dialect=MyDialect(),
    encrypted=True,          # switches to bolt+s://
)
```

**TLS note** — the `encrypted` flag is a convenience wrapper: it
rewrites `bolt://` → `bolt+s://` (or vice-versa). You can bypass it
by passing a URI directly to the `BoltDriver` constructor.
