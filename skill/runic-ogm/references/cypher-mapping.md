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
| `MATCH (u:User)` | `select(alias(User, "u"))` |
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
| `WHERE a.id < b.id` | `.where(a.id < b.id)` with handles `a, b = alias(A, "a"), alias(A, "b")` |
| `WHERE n.x = $named` | `.where(User.x == param("named"))` |

## Returning

| Cypher | runic |
|---|---|
| `RETURN n` | default |
| `RETURN DISTINCT n` | `.distinct()` |
| `RETURN n.name AS name` | `.project(User.name)` — bare fields auto-name |
| `RETURN n.name AS other` | `.project(User.name.as_("other"))` — `.as_()` renames |
| `RETURN m.id AS id` | `.project(m.id)` with a handle |
| `RETURN u, m` | `.return_nodes(u, m)` |
| `RETURN u, r, m` | `.return_nodes(u, m).return_edge(r)` |
| `RETURN count(*) AS total` | `.project(count("*").as_("total"))` |
| `RETURN count(n.x)` | `.project(count(User.x))` |
| `RETURN count(DISTINCT n.x)` | `.project(count(User.x, distinct=True))` |
| `RETURN avg/sum/min/max(n.x)` | `.project(avg(User.x))` … |
| `RETURN collect(DISTINCT r.id)` | `.project(collect(r.id, distinct=True))` with a handle |
| `RETURN n.city AS city, count(*)` | `.project(User.city, count("*").as_("c"))` — plain items ARE the group keys |
| grouping on two keys | `.project(a.id.as_("l"), b.id.as_("r"), count("*").as_("c"))` |
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
| `n.prop` | `Model.prop` — a bare field is a value |
| `m.prop` | `m.prop` on a handle (`col("m", Model.prop)` for a one-off pin) |
| `$name` | `param("name")` |
| a Python value | passed directly; bound as `$pN` |
| `row.key` | `row("key")` |
| `left(n.body, $max)` | `left(M.body, param("max"))` |
| `coalesce(a, b)` | `coalesce(M.a, M.b)` |
| `toLower(n.x)` | `to_lower(M.x)` |
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
| `MATCH (n)-[:R]->(t:T)` (inner join) | `.traverse(Model.rel, to="t")` — MATCH is the default |
| `OPTIONAL MATCH (n)-[:R]->(t:T)` | `.traverse(Model.rel, to="t", optional=True)` |
| `(n)-[r:R]->(t)` | `.traverse(Model.rel, to="t", edge=r)` |
| filter on the edge | `.where(r.prop > v)` with an edge handle |
| `(n)-->(f)-->(p)` (a chain) | consecutive `.traverse()` calls — each leaves from the previous target (the cursor) |
| `(m)-[:A]->(x)` and `(m)-[:B]->(y)` | `.traverse(..., from_=m)` for each — `from_` overrides the cursor |
| `(n)-[:A\|B]->(t)` | `.traverse(Model.rel, types=["A", "B"])` |
| `(a)-[r:R]->(b)` on a `BOTH` relation | `.traverse(..., direction="OUTGOING")` |
| `(p)-[:R*1..5]->(x)` | `.traverse(Model.rel, to="x", hops=(1, 5))` |
| `(p)-[:R*1..]->(x)` | `.traverse(Model.rel, to="x", hops=(1, None))` |

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
| `MERGE (n:L {id: row.id})` | `.merge(L, key=L.id, alias="n")` — a bare key reads the same-named row key |
| `MATCH (m:L {id: row.k})` | `.match(L, key={L.id: row("k")}, alias="m")` — mapping form for renamed keys |
| `MERGE (m)-[:R]->(t)` | `.merge_edge("m", "R", "t")` — or pass a Relation field for the type |
| `MERGE (m)-[r:R]->(t)` | `.merge_edge("m", E, "t", alias="r")` — the Edge class carries type + model |
| `MERGE (a)-[r:R]-(b)` (no arrow) | `.merge_edge(..., directed=False)` |
| `SET n.x = row.x` | `.set(L.x, on="n")` — a bare descriptor reads the same-named row key |
| `SET n.x = NULL` | `.set({L.x: None})` |
| `DELETE r` | `.delete("r")` |
| `DETACH DELETE n` | `.delete(detach=True)` |

## Procedures and search

| Cypher | runic |
|---|---|
| vector KNN (portable) | `vector_search(M.vec, vector=param("v"), k=param("k"))` |
| fulltext (portable) | `fulltext_search(M, query=param("text"))` |
| `CALL proc(a, b) YIELD x, y` | `.call("proc", a, b, yields=["x", "y"])` |
| correlated `CALL` | pass `m.field` (a handle property) as an argument |
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

**A second `traverse()` without `from_`.** It leaves from the *previous
traversal's target* (the cursor), not from the root — that is what makes
consecutive calls walk a chain. Fanning out from one node needs `from_=` on
each traversal after the first.

**A `where()` on an *optional* traversal.** `OPTIONAL MATCH` + `WHERE`
nullifies non-matching rows instead of dropping them. `traverse()` emits a
plain `MATCH` by default; add `optional=True` only when missing relationships
are valid data.

**Projecting the whole node as the group key.** `project(u, agg)` groups per
node — one row per node. Project the property to group by its value:
`project(User.city, agg)`.

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

| Construct | FalkorDB | Neo4j | Memgraph | ArcadeDB | AGE | Neptune DB | Neptune Analytics |
|---|---|---|---|---|---|---|---|
| `[:A\|B]` alternation | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Undirected `MERGE` | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `CALL … YIELD` | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✓ |
| Fulltext search | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ |
| Vector search | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✓ |
