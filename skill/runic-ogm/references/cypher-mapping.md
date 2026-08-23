# Cypher → runic

Look up a Cypher fragment, get the builder call that produces it. Use this when
you know the query you want and need the API for it.

Assume `from runic.ogm import *`-style names throughout — the real import is:

```python
from runic.ogm import (
    avg, coalesce, col, collect, count, encode_rows, fn, left, literal,
    max_, min_, param, row, score, select, sum_, to_lower, to_upper,
    unwind, var, when,
)
```

---

## Matching and filtering

| Cypher | runic |
|---|---|
| `MATCH (n:User)` | `select(User)` |
| `MATCH (u:User)` | `select(User).alias("u")` |
| `WHERE n.name = $p` | `.where(User.name == value)` |
| `WHERE n.age > $p` | `.where(User.age > value)` |
| `WHERE n.name CONTAINS $p` | `.where(User.name.contains(v))` |
| `WHERE n.name STARTS WITH $p` | `.where(User.name.startswith(v))` |
| `WHERE n.name =~ $p` | `.where(User.name.matches(pattern))` |
| `WHERE n.x IS NULL` | `.where(User.x.is_null())` or `== None` |
| `WHERE n.x IS NOT NULL` | `.where(User.x.is_not_null())` |
| `WHERE n.role IN $p` | `.where(User.role.in_([...]))` |
| `WHERE NOT n.role IN $p` | `.where(User.role.not_in_([...]))` |
| `WHERE $v IN n.tags` | `.where(User.tags.any_of(v))` — **list property** |
| `WHERE a AND b` | `.where(a & b)` — parenthesise each operand |
| `WHERE a OR b` | `.where(a \| b)` |
| `WHERE NOT (a)` | `.where(~a)` |
| `WHERE a.id < b.id` | `.where(col("a", A.id) < col("b", A.id))` |
| `WHERE n.x = $named` | `.where(User.x == param("named"))` |

## Returning

| Cypher | runic |
|---|---|
| `RETURN n` | default |
| `RETURN DISTINCT n` | `.distinct()` |
| `RETURN n.name` | `.project(User.name)` |
| `RETURN n.name AS name` | `.project(col(User.name).as_("name"))` |
| `RETURN m.id AS id` | `.project(col("m", M.id).as_("id"))` |
| `RETURN u, m` | `.return_nodes("u", "m")` |
| `RETURN u, r, m` | `.return_nodes("u", "m").return_edge("r")` |
| `RETURN count(*) AS total` | `.aggregate(count("*").as_("total"))` |
| `RETURN count(n.x)` | `.aggregate(count(User.x))` |
| `RETURN count(DISTINCT n.x)` | `.aggregate(count(User.x, distinct=True))` |
| `RETURN avg/sum/min/max(n.x)` | `.aggregate(avg(User.x))` … |
| `RETURN collect(DISTINCT r.id)` | `.aggregate(collect(col("r", A.id), distinct=True))` |
| `RETURN n.city, count(*)` | `.aggregate(count("*").as_("c"), group_by=col(User.city).as_("city"))` |
| grouping on two keys | `group_by=[col("a", A.id).as_("l"), col("b", A.id).as_("r")]` |
| `RETURN count(n) AS removed` (after a write) | `.returning(count("n").as_("removed"))` |

## Ordering and paging

| Cypher | runic |
|---|---|
| `ORDER BY n.name` | `.order_by(User.name)` |
| `ORDER BY n.name DESC` | `.order_by(User.name, desc=True)` |
| `ORDER BY total DESC` | `.order_by("total", desc=True)` |
| `LIMIT 10` | `.limit(10)` |
| `LIMIT $limit` | `.limit(param("limit"))` |
| `SKIP 20` | `.skip(20)` |
| cursor paging | `.where(M.id > param("after")).order_by(M.id).limit(param("limit"))` |

Prefer a cursor to `SKIP`: an offset re-matches and re-sorts every preceding row,
so walking a label in pages costs `O(n²/page)`.

## Expressions

| Cypher | runic |
|---|---|
| `n.prop` | `col(Model.prop)` |
| `m.prop` | `col("m", Model.prop)` or `Model.prop.on("m")` |
| `$name` | `param("name")` |
| a Python value | passed directly; bound as `$pN` |
| `row.key` | `row("key")` |
| `left(n.body, $max)` | `left(col(M.body), param("max"))` |
| `coalesce(a, b)` | `coalesce(col(M.a), col(M.b))` |
| `toLower(n.x)` | `to_lower(col(M.x))` |
| any other function | `fn("name", arg, …)` |
| `CASE WHEN c THEN v END` | `when(condition, v)` |
| `CASE WHEN c THEN v ELSE w END` | `when(condition, v, else_=w)` |
| `count(CASE WHEN c THEN 1 END)` | `count(when(condition, 1))` |
| `expr AS name` | `.as_("name")` on any expression |
| a bare variable (`score`) | `var("score")` |
| a search score | `score()` |

## Traversal

| Cypher | runic |
|---|---|
| `OPTIONAL MATCH (n)-[:R]->(t:T)` | `.traverse(Model.rel).alias("t")` |
| `MATCH (n)-[:R]->(t:T)` (inner join) | `.traverse(Model.rel, optional=False).alias("t")` |
| `(n)-[r:R]->(t)` | `.traverse(Model.rel, edge_alias="r").alias("t")` |
| filter on the edge | `.where(EdgeModel.prop > v, on="r")` + `optional=False` |
| `(m)-[:A]->(x)` and `(m)-[:B]->(y)` | `.traverse(..., from_="m")` for each |
| `(n)-[:A\|B]->(t)` | `.traverse(Model.rel, types=["A", "B"])` |
| `(a)-[r:R]->(b)` on a `BOTH` relation | `.traverse(..., direction="OUTGOING")` |
| `(p)-[:R*1..5]->(x)` | `.repeat(Model.rel, min_hops=1, max_hops=5)` |
| `(p)-[:R*1..]->(x)` | `.repeat(Model.rel, min_hops=1)` |

## `WITH`

| Cypher | runic |
|---|---|
| `WITH n` | `.with_("n")` |
| `WITH DISTINCT n` | `.with_("n", distinct=True)` |
| `WITH n ORDER BY n.id LIMIT $k` | `.with_("n", order_by=M.id, limit=param("k"))` |
| `WITH n, count(r) AS c` | `.with_("n", count("r").as_("c"))` |
| `WITH … WHERE c > $min` (HAVING) | `.with_(..., where=var("c") > param("min"))` |

`with_()` is repeatable; stages interleave with traversals in call order.

## Writes

| Cypher | runic |
|---|---|
| `UNWIND $rows AS row` | `unwind(param("rows"))` |
| `MERGE (n:L {id: row.id})` | `.merge(L, key={L.id: row("id")}, alias="n")` |
| `MATCH (m:L {id: row.k})` | `.match(L, key={L.id: row("k")}, alias="m")` |
| `MERGE (m)-[:R]->(t)` | `.merge_edge("m", "R", "t")` |
| `MERGE (m)-[r:R]->(t)` | `.merge_edge("m", "R", "t", alias="r", edge_model=E)` |
| `MERGE (a)-[r:R]-(b)` (no arrow) | `.merge_edge(..., directed=False)` |
| `SET n.x = row.x` | `.set({L.x: row("x")}, on="n")` |
| `SET n.x = NULL` | `.set({L.x: None})` |
| `DELETE r` | `.delete("r")` |
| `DETACH DELETE n` | `.delete(detach=True)` |

## Procedures and search

| Cypher | runic |
|---|---|
| vector KNN (portable) | `session.vector_search(M, field=M.vec, vector=param("v"), k=param("k"))` |
| fulltext (portable) | `session.fulltext_search(M, query=param("text"))` |
| `CALL proc(a, b) YIELD x, y` | `.call("proc", a, b, yields=["x", "y"])` |
| correlated `CALL` | pass `col("m", M.field)` as an argument |
| `CREATE/DROP VECTOR INDEX` | `IndexOperations` — **not** the builder |
| `CALL DB.INDEXES()` | `IndexOperations.describe()` |

## Execution

| Want | Call |
|---|---|
| entities | `session.scalars(stmt, params)` |
| one entity or `None` | `session.scalar(stmt, params)` |
| a count | `session.count(stmt, params)` |
| rows as dicts (projections, aggregates) | `session.all_rows(stmt, params)` |
| `(node, edge, node)` tuples | `session.all_with_edges(stmt, params)` |
| the generated Cypher | `stmt.build()` → `(cypher, params)` |
| what a statement expects | `stmt.parameter_names()` |

`session.query(Cls)` returns a bound builder with `.all()`, `.one()`, `.count()`,
`.all_rows()`, `.all_with_edges()` on it instead.

---

## Things that look right and are not

**`.in_()` on a list property.** Compiles to `n.tags IN $values` — "is the whole
list an element of the parameter" — which nothing answers true to, so the filter
silently returns nothing. Use `.any_of(value)`.

**A `where()` on an optional traversal.** `OPTIONAL MATCH` + `WHERE` nullifies
non-matching rows instead of dropping them, so you get `None`s rather than a
filtered result. Pass `optional=False` whenever you filter on what you traversed.

**`group_by="u"`.** Groups by the whole node — one row per node. Pass the
property: `group_by=col(User.city).as_("city")`.

**Aliasing an aggregate `"n"`.** Collides with the default node alias and the
decoder treats the integer as a node.

**`detach=True` when deleting an edge.** Takes both endpoints down with it. Use
`.delete("r")`.

**A `datetime` inside a `$rows` payload.** Values there never pass through the
mapper. Run the payload through `encode_rows(Model, rows)` first.

**`k == limit` on a vector search.** A procedure cannot be narrowed before the
fact, so a following filter drops rows already paid for. The page comes back
short and looks like a small database.

**Comparing a vector score with a fulltext score.** Vector is a distance (lower
is closer); fulltext is a relevance (higher is better). Opposite directions.

**Type checkers do not see descriptor methods.** `Model.field` is typed by its
annotation, so `.is_null()`, `.in_()`, `.any_of()` and `&`/`|` between
comparisons need a suppression comment:

```python
.where(M.id.is_not_null() & (M.id != ""))  # ty: ignore[unresolved-attribute, unsupported-operator]
```

Write the code normally and add the comment; do not restructure to avoid it.

## Backend gaps

runic refuses to emit Cypher a backend cannot parse, raising
`NotImplementedError` that names the construct and the backend.

| Construct | FalkorDB | Neo4j | Memgraph | ArcadeDB | AGE |
|---|---|---|---|---|---|
| `[:A\|B]` alternation | ✓ | ✓ | ✓ | ✓ | ✗ |
| Undirected `MERGE` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `CALL … YIELD` | ✓ | ✓ | ✓ | ✗ | ✗ |
| Fulltext search | ✓ | ✓ | ✓ | ✗ | ✗ |
| Vector search | ✓ | ✓ | ✓ | ✓ | ✗ |
