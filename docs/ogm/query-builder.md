# Query Builder

The query builder lets you construct Cypher queries from your OGM model
declarations using a fluent Python API — without writing raw Cypher strings for
the common cases. This page explains *how* the builder works, *what Cypher it
emits*, and *when* to use each feature so you can read the result confidently
and know when to reach for something else.

---

## How the query builder works

`select()` returns a `QueryBuilder` that accumulates clauses as you
chain method calls. Nothing is sent to the database until you pass the
statement to a session execution method (`session.scalars()`,
`session.scalar()`, `session.count()`, etc.).

At that point the session:

1. **Generates a Cypher string and a parameter dict** from the accumulated
   clauses.
2. **Sends the query to the driver** via the session's connection.
3. **Decodes each result row** using the OGM mapper — the same code path used
   by `session.get()` and `repo.find_all()`.
4. **Registers returned entities in the session's identity map**, so change
   tracking works on them exactly as if you had loaded them any other way.

Because the builder goes through the same mapper and identity map, you can mix
builder queries and direct `session.get()` calls freely within the same
session.

To see the Cypher the builder *would* emit without executing it, call
`QueryBuilder.build()` — this works on an unbound statement (no session required):

```python
from runic.ogm import select

cypher: str
params: dict[str, Any]
cypher, params = select(User).where(User.active == True).build()
print(cypher)
# MATCH (n:User) WHERE (n.active = $p0) RETURN n
print(params)
# {'p0': True}
```

Use `.build()` freely while learning the builder or debugging unexpected results.

::: info See also
[examples/orm/07_query_builder_basics.py](https://github.com/jenreh/runic/blob/main/examples/orm/07_query_builder_basics.py)
— Covers every foundational feature: comparisons, string predicates, null
checks, membership, boolean composition, ordering, pagination, projection,
and all terminal methods.
:::

---

## Entry points

There are four starting points for a query. All four return a
`QueryBuilder` whose chaining and terminal methods behave identically.

| Call | When to use |
|------|-------------|
| `select(NodeCls)` | **Preferred.** Session-independent statement; execute via `session.scalars(stmt)` etc. Enables dynamic query composition. |
| `session.query(NodeCls)` | Session-bound query; terminal methods (`all()`, `count()`, …) execute immediately. Equivalent to `session.scalars(select(NodeCls)...)`. |
| `repo.query()` | Equivalent to `session.query(T)`; useful when the repository type is already in scope. |
| `session.fulltext_search(Cls, query=...)` | Full-text search queries — wraps a backend-specific `CALL` procedure. See [Full-text search](#full-text-search). |
| `session.vector_search(Cls, field=..., vector=..., k=...)` | Approximate nearest-neighbour vector queries. See [Vector KNN search](#vector-knn-search). |

---

## Composable statements

`select()` creates a `QueryBuilder` that is **not bound to a session**, making it easy to build dynamic queries from
UI filters, request parameters, or any conditional logic — then hand the
finished statement to a session for execution.

```python
from runic.ogm import select

# Build without touching the database
stmt = select(User).where(User.active == True)

if min_age > 0:
    stmt = stmt.where(User.age >= min_age)
if name_filter:
    stmt = stmt.where(User.name.contains(name_filter))

stmt = stmt.order_by(User.name).limit(page_size)

# Execute once you have a session
users: list[User]  = session.scalars(stmt)
user:  User | None = session.scalar(stmt)
n:     int         = session.count(stmt)
rows:  list[dict]  = session.all_rows(stmt)

# Async sessions work with the same stmt
users = await async_session.scalars(stmt)
```

The same `stmt` object is **reusable** — execute it multiple times, against
different sessions if needed. Each call to `session.scalars()` etc. restores
the statement's binding to `None` after execution.

Calling terminal methods directly on an unbound statement raises a clear
`RuntimeError`:

```python
stmt = select(User)
stmt.all()   # RuntimeError: not bound to a session — use session.scalars(stmt)
```

::: tip
`session.query(User).where(...).all()` is still fully supported and
equivalent to `session.scalars(select(User).where(...))`. Prefer
`select()` when you need to compose the query across multiple code paths.
:::

---

## Filtering

Predicates are built by applying Python comparison operators to **class-level
field accesses**. The operator overloads on
`FieldDescriptor` return lightweight
`FilterExpr` objects that the builder
serialises into parameterised Cypher `WHERE` clauses.

Two important points before you start:

* **No Python evaluation happens.** `User.age > 18` does not evaluate to a
  Python boolean; it returns a `FilterExpr`
  object. This means you cannot use it inside a Python `if` statement — only
  inside `.where()`.
* **Parameters are always bound.** The builder never interpolates values
  directly into the Cypher string. Every value becomes a `$pN` parameter,
  which prevents Cypher injection and enables query-plan caching.

### Comparison operators

```python
# Equality / inequality
User.name == "Alice"          # WHERE n.name = $p0
User.status != "banned"       # WHERE n.status <> $p0

# None comparisons map to IS NULL / IS NOT NULL
User.deleted_at == None       # WHERE n.deleted_at IS NULL
User.email != None            # WHERE n.email IS NOT NULL

# Numeric comparison
User.age > 18                 # WHERE n.age > $p0
User.score >= 4.5             # WHERE n.score >= $p0
User.age < 65                 # WHERE n.age < $p0
User.credit <= 0              # WHERE n.credit <= $p0
```

### String predicates

String predicates map directly to Cypher string operators:

```python
User.name.contains("ali")          # WHERE n.name CONTAINS $p0
User.email.startswith("admin@")    # WHERE n.email STARTS WITH $p0
User.url.endswith(".org")          # WHERE n.url ENDS WITH $p0
User.bio.matches(r".*graph.*")     # WHERE n.bio =~ $p0  (regex)
```

::: info
Cypher regular expressions follow the Java `java.util.regex` syntax.
Anchoring (`^`, `$`) and case-insensitive flags (`(?i)`) are
supported; look-aheads are not.
:::

### Null checks

The `== None` / `!= None` shorthand works, but explicit null-check methods
are clearer in code review:

```python
User.deleted_at.is_null()          # WHERE n.deleted_at IS NULL
User.email.is_not_null()           # WHERE n.email IS NOT NULL
```

### List membership

```python
# IN list
User.role.in_(["admin", "mod"])    # WHERE n.role IN $p0

# NOT IN list
Post.tag.not_in_(["spam"])         # WHERE NOT n.tag IN $p0
```

The list is passed as a single bound parameter, not expanded inline.

### Boolean composition

Use the bitwise operators `&` (AND), `|` (OR), and `~` (NOT) to compose
predicates. These are *not* Python `and` / `or` / `not` — those would
short-circuit and discard the filter objects:

```python
# AND — both conditions must match
select(User).where((User.age > 18) & (User.active == True))
# WHERE (n.age > $p0) AND (n.active = $p1)

# OR — either condition can match
select(User).where((User.role == "admin") | (User.role == "mod"))
# WHERE (n.role = $p0) OR (n.role = $p1)

# NOT — negate a predicate
select(User).where(~(User.banned == True))
# WHERE NOT (n.banned = $p0)
```

**Multiple `.where()` calls are always joined by AND.** The following two
statements are equivalent:

```python
select(User).where((User.age > 18) & (User.active == True))

select(User).where(User.age > 18).where(User.active == True)
```

Use chained `.where()` calls when your predicates are produced independently
(e.g. optional filters in a search function) and `&` / `|` when you need
explicit OR or complex nesting.

---

## Ordering, pagination, and DISTINCT

These clauses work exactly as their Cypher counterparts suggest:

```python
stmt = (
    select(User)
    .order_by(User.created_at, desc=True)   # ORDER BY n.created_at DESC
    .skip(40)                                # SKIP 40
    .limit(20)                               # LIMIT 20
)
users: list[User] = session.scalars(stmt)
```

`skip` and `limit` together implement offset-based pagination. For
cursor-based or keyset pagination, filter on an indexed field instead:

```python
stmt = (
    select(User)
    .where(User.created_at < last_seen_ts)
    .order_by(User.created_at, desc=True)
    .limit(20)
)
users: list[User] = session.scalars(stmt)
```

Use `.distinct()` to deduplicate the `RETURN` clause:

```python
# Unique countries across all users — project() + all_rows() for scalar columns
rows: list[dict] = session.all_rows(select(User).distinct().project(User.country))
countries: list[str] = [r["n.country"] for r in rows]
# RETURN DISTINCT n.country
```

---

## Value expressions

Filters compare *values*, `RETURN` projects them, `ORDER BY` sorts on them. One
set of constructors covers every one of those positions, so a reference written
once can be projected, aliased, wrapped in a function, or compared against
another property.

```python
from runic.ogm import col, coalesce, fn, left, literal, param, to_lower, when
```

| Constructor | Emits | For |
|---|---|---|
| `col(Model.field)` | `n.field` | a property, alias resolved by the builder |
| `col("m", Model.field)` | `m.field` | a property on a **named** variable |
| `Model.field.on("m")` | `m.field` | the same, in descriptor form |
| `param("name")` | `$name` | a value the caller binds |
| `literal(v)` | `$p0` | a Python value, bound not inlined |
| `fn("name", …)` | `name(…)` | any scalar function |
| `left(v, n)` · `coalesce(…)` · `to_lower(v)` | `left(…)` … | the common ones |
| `when(cond, then)` | `CASE WHEN … THEN … END` | conditional values |
| `.as_("name")` | `… AS name` | naming the result column |

Every operand is bound as a parameter. A Python value anywhere inside an
expression tree reaches the graph as `$pN` — nothing is spliced into the query
as text.

### Naming result columns

`all_rows()` keys its dicts by the column names the store reports, so an
unaliased projection produces keys like `"n.body_clean"`. `.as_()` fixes that:

```python
rows = session.all_rows(
    select(Message).project(
        col(Message.id).as_("id"),
        col(Message.sent_at).as_("sent_at"),
    )
)
# [{"id": "m1", "sent_at": "2026-01-02T…"}, …]
```

### Computing in the store

`left()` truncates before the value crosses the wire, which matters when the
property is large and the caller only wants a prefix:

```python
select(Message).project(
    col(Message.id).as_("id"),
    left(col(Message.body_clean), param("max_chars")).as_("body"),
)
# RETURN n.id AS id, left(n.body_clean, $max_chars) AS body
```

### Comparing two properties

A parameter cannot express "this property is less than that one", because both
sides are in the graph. Two `col()` references can:

```python
stmt = (
    select(Address).alias("a")
    .traverse(Address.co_addressed, edge_alias="r", optional=False).alias("b")
    .where(col("a", Address.id) < col("b", Address.id))
)
# WHERE a.id < b.id
```

That predicate is what turns an unordered pair into a single row: without it an
undirected pattern matches each pair twice, once from each end.

### Conditional aggregation

`when()` inside an aggregate gives several differently filtered numbers from one
scan — which also guarantees they are counted over the same population:

```python
from runic.ogm import count

session.all_rows(
    select(Message).aggregate(
        count("*").as_("total"),
        count(when(Message.embedding_model == param("model"), 1)).as_("embedded"),
    )
)
# RETURN count(*) AS total, count(CASE WHEN n.embedding_model = $model THEN $p0 END) AS embedded
```

Asking those as two queries lets the populations drift apart between them.

---

## Named parameters

`param()` **declares** a parameter instead of binding a value. The statement
becomes a constant that callers supply values to, rather than a query rebuilt
per call:

```python
from typing import Final
from runic.ogm import param, select

RECENT_MESSAGES: Final = (
    select(Message)
    .where(Message.id > param("after"))
    .order_by(Message.id)
    .limit(param("limit"))
)

rows = session.scalars(RECENT_MESSAGES, {"after": cursor, "limit": 500})
```

Every execution method takes the bindings as a second argument: `scalars()`,
`scalar()`, `all_rows()`, `all_with_edges()`, `count()`, and the bound-builder
equivalents.

`LIMIT` and `SKIP` accept them too, so a page size is a value rather than part
of the statement.

### Knowing what a statement expects

```python
RECENT_MESSAGES.parameter_names()
# ('after', 'limit')
```

Read off the compiled statement, not maintained beside it, so it cannot drift.

### A missing parameter is an error, not an empty result

```python
session.scalars(RECENT_MESSAGES, {"after": cursor})
# ValueError: statement is missing values for declared parameter(s): limit
```

This is deliberate. An unsupplied `$parameter` is a null in Cypher: it matches
nothing and returns an empty result that looks exactly like an empty database.
Failing loudly is the only way that distinction survives.

### Why this shape matters

A statement that binds all its input as named parameters can be a module-level
constant — reviewable in a diff, reusable across calls, and testable by
enumerating the statements, binding each one's parameters, and running the lot.
Caller input can then never change what a statement *does*, only which rows it
returns. That property is what makes it safe to put a query layer behind an
interface you do not control, such as an MCP server answering a model's
questions.

---

## List properties: `any_of()` vs `in_()`

The two ask opposite questions, and on a list-valued property only one of them
is meaningful:

```python
# Message.refs is list[str]

select(Message).where(Message.refs.any_of(param("token")))
# WHERE $token IN n.refs      ← does the stored list contain this element?

select(Message).where(Message.id.in_(["m1", "m2"]))
# WHERE n.id IN $p0           ← is this property one of these values?
```

Calling `in_()` on a list property compiles to `n.refs IN $values` — asking
whether the whole list is an element of the parameter. Nothing answers that
`true`, so the filter silently returns no rows.

---

## Projection — returning scalar values

By default, the query returns fully decoded node instances. Use
`QueryBuilder.project()` when you only need a
subset of properties — this avoids loading full node objects and reduces the
data transferred from the database.

```python
# Single field → flat list via session.all_rows() then extract
rows = session.all_rows(select(User).project(User.email))
emails: list[str] = [r["n.email"] for r in rows]
# RETURN n.email  →  ["alice@example.com", "bob@example.com", ...]

# Multiple fields → list of dicts via session.all_rows()
rows: list[dict[str, Any]] = session.all_rows(select(User).project(User.name, User.age))
# RETURN n.name, n.age  →  [{"n.name": "Alice", "n.age": 30}, ...]
```

When to use projection vs full node loading:

* Use **full node loading** (`all()`, `one()`) when you need tracked objects
  with full change-tracking, relationship loading, or type-converted fields.
* Use **projection** when you are reading a single denormalised view for display
  or export and do not need to mutate or traverse the result.

---

## Aggregation

The query builder ships aggregation helpers that map to Cypher's built-in
aggregate functions. Import them from `runic.ogm.query`:

```python
from runic.ogm.query import count, avg, sum_, min_, max_, collect
```

Use `QueryBuilder.aggregate()` to add one or more
aggregation expressions to the `RETURN` clause. The `.as_("name")` call
sets the Cypher alias for that column, which you use to retrieve the value from
the result dict returned by `.all_rows()`.

### Simple aggregation (no grouping)

When there is no `group_by`, the query collapses to a single row:

```python
# Total number of users
rows = session.all_rows(select(User).aggregate(count().as_("total")))
total: int = rows[0]["total"]
# MATCH (n:User) RETURN count(*) AS total

# Average score
rows = session.all_rows(select(User).aggregate(avg(User.score).as_("avg")))
avg_score: float = rows[0]["avg"]
# MATCH (n:User) RETURN avg(n.score) AS avg

# Convenience shortcut — count via session.count()
n: int = session.count(select(User).where(User.active == True))
# MATCH (n:User) WHERE n.active = $p0 RETURN count(*)
```

### Grouped aggregation

Pass `group_by=` to partition results. The named alias must match an alias
previously set with `.alias()`:

```python
stmt = (
    select(User).alias("u")
    .traverse(User.posts).alias("p")
    .aggregate(count("*").as_("post_count"), group_by="u")
)
rows: list[dict[str, Any]] = session.all_rows(stmt)
# OPTIONAL MATCH (u:User)-[:AUTHORED]->(p:Post)
# RETURN u, count(*) AS post_count

for row in rows:
    user: User = row["u"]
    post_count: int = row["post_count"]
    print(user.name, "has", post_count, "posts")
```

### Collecting values into a list

`collect` maps to Cypher's `collect()` aggregate, which gathers values
across rows into a list:

```python
stmt = (
    select(User).alias("u")
    .traverse(User.tags).alias("t")
    .aggregate(collect("t").as_("tags"), group_by="u")
)
rows: list[dict[str, Any]] = session.all_rows(stmt)
# RETURN u, collect(t) AS tags
```

::: info See also
[examples/orm/10_query_builder_aggregation.py](https://github.com/jenreh/runic/blob/main/examples/orm/10_query_builder_aggregation.py)
— `count`, `avg`, `sum_`, `min_`, `max_`, `collect`; grouped
aggregation with `group_by`; `.scalar()` and `.all_rows()`.
:::

---

## Traversals

The traversal API lets you follow relationship patterns declared on your models
using `Relation` fields — without writing
`MATCH (a)-[:TYPE]->(b)` by hand.

### Understanding OPTIONAL MATCH vs MATCH

By default, `.traverse()` generates an `OPTIONAL MATCH` clause. This is a
**left join**: nodes that have no matching relationship are still returned, with
`None` for the related node.

Pass `optional=False` to get an inner join (`MATCH`), which excludes root
nodes that have no matching relationship:

```text
OPTIONAL MATCH (u)-[:FRIENDS]->(f)    # all users, friends may be None
MATCH (u)-[:WORKS_FOR]->(c)           # only users with a company
```

Choose based on whether missing relationships are valid data or an error.

### Single-hop traversal

`QueryBuilder.traverse()` takes a
`Relation` field reference. Call
`.alias()` on the returned step to name the target node variable and continue
the builder chain:

```python
# Find all friends of a specific user, aged over 25
stmt = (
    select(User).alias("u")
    .where(User.id == user_id)
    .traverse(User.friends).alias("f")
    .where(User.age > 25, on="f")   # predicate scoped to "f", not "u"
    .return_target("f")
)
friends: list[User] = session.scalars(stmt)
# MATCH (u:User) WHERE u.id = $p0
# OPTIONAL MATCH (u)-[:FRIENDS]->(f:User)
# WHERE f.age > $p1
# RETURN f
```

The `on=` argument on `.where()` scopes a predicate to a specific alias.
Without it, predicates are applied to the root node.

### Multi-hop traversal

Chain multiple `.traverse()` calls to follow a path through several
relationships. Each step names a new alias:

```python
stmt = (
    select(User).alias("u")
    .traverse(User.friends).alias("f")
    .traverse(User.authored_posts).alias("p")
    .where(Post.title.contains("graph"), on="p")
    .return_target("p")
)
posts_by_friends: list[Post] = session.scalars(stmt)
# MATCH (u:User)
# OPTIONAL MATCH (u)-[:FRIENDS]->(f:User)
# OPTIONAL MATCH (f)-[:AUTHORED]->(p:Post)
# WHERE p.title CONTAINS $p0
# RETURN p
```

### Variable-length paths

Use `QueryBuilder.repeat()` when you need to
traverse an unknown number of hops — equivalent to Cypher's `*min..max`
quantifier. This is useful for hierarchies (org charts, category trees,
dependency graphs):

```python
# Find all managers in the chain above an employee (1 to 5 hops)
stmt = (
    select(Employee).alias("e")
    .where(Employee.id == emp_id)
    .repeat(Employee.reports_to, min_hops=1, max_hops=5).alias("anc")
)
ancestors: list[Employee] = session.scalars(stmt)
# MATCH (e:Employee) WHERE e.id = $p0
# MATCH (e)-[:REPORTS_TO*1..5]->(anc:Employee)
# RETURN anc

# No upper bound — all reachable nodes
stmt = select(Station).repeat(Station.connected_to, min_hops=1).alias("s2")
all_reachable: list[Station] = session.scalars(stmt)
# MATCH (n:Station)-[:CONNECTED_TO*1..]->(s2:Station) RETURN s2
```

::: warning
Variable-length paths with no upper bound (`*1..`) can be extremely
expensive on dense graphs. Always set `max_hops` unless you are certain
the graph has bounded depth.
:::

::: info See also
[examples/orm/08_query_builder_traversal.py](https://github.com/jenreh/runic/blob/main/examples/orm/08_query_builder_traversal.py)
— Single-hop and multi-hop traversal, `optional=False` inner-join,
`repeat()`, `return_target()`, `with_()`, and alias-scoped
`where(on=)`.
:::

---

## Aliases

Every node variable in a generated Cypher query has a name. The root node
defaults to `n`; traversal targets default to a generated name. Use
`.alias()` to assign readable names — this is important when:

* You need to scope a `.where()` to a specific node (via `on=`).
* You need to reference a node in a `.with_()` clause.
* You read the generated Cypher via `.build()` and want it to be legible.

```python
select(User).alias("u").where(User.name == "Alice", on="u")
# MATCH (u:User) WHERE u.name = $p0 RETURN u
```

---

## Edge properties

By default, relationship patterns are anonymous: `(a)-[:TYPE]->(b)`. This is
sufficient for most traversals. When you need to **filter on edge properties**
or **return edge data alongside the nodes**, pass `edge_alias=` to
`.traverse()` to name the relationship variable:

```python
class Rated(Edge, type="RATED"):
    score: float = Field()

class User(Node, labels=["User"]):
    rated: list[Movie] = Relation(
        relationship="RATED",
        direction="OUTGOING",
        target="Movie",
        edge_model=Rated,
    )

stmt = (
    select(User).alias("u")
    .traverse(User.rated, edge_alias="r").alias("m")
    .where(Rated.score > 4.0, on="r")       # filter on edge property
    .return_nodes("u", "m").return_edge("r")
)
rows: list[tuple[User, Rated, Movie]] = session.all_with_edges(stmt)
# OPTIONAL MATCH (u:User)-[r:RATED]->(m:Movie)
# WHERE r.score > $p0
# RETURN u, r, m

for user, edge, movie in rows:
    user: User
    edge: Rated
    movie: Movie
    print(f"{user.name} rated {movie.title}: {edge.score}/5")
```

Note that `return_nodes()` and `return_edge()` explicitly select which
variables appear in `RETURN`. `all_with_edges()` then unpacks the result
rows into typed tuples.

::: info
The existing lazy/eager loading paths (`session.get(..., fetch=[...])`)
continue to use anonymous relationship patterns. Named edge variables are
only emitted by the query builder when `edge_alias=` is given.
:::

::: info See also
[examples/orm/09_query_builder_edges.py](https://github.com/jenreh/runic/blob/main/examples/orm/09_query_builder_edges.py)
— `traverse(edge_alias=)`, `return_nodes()` + `return_edge()`,
`all_with_edges()`, and filtering on edge properties.
:::

---

## Multi-stage queries: `WITH`

`WITH` is the only place Cypher lets a query order and cut **mid-flight**. Its
`ORDER BY` and `LIMIT` apply to the rows entering the next stage, not to the
final result — which is what makes it possible to take a page *before* paying
for expansions.

```python
(
    select(Message).alias("m")
    .where(Message.id > param("after"))
    .with_("m", order_by=Message.id, limit=param("limit"))
    .traverse(Message.sent_to, from_="m").alias("r")
    .aggregate(collect(col("r", Address.id), distinct=True).as_("addressed"),
               group_by=col("m", Message.id).as_("id"))
)
```

```cypher
MATCH (m:Message)
WHERE m.id > $after
WITH m ORDER BY m.id ASC LIMIT $limit     -- page taken off the index here
OPTIONAL MATCH (m)-[:SENT_TO]->(r:Address)
RETURN m.id AS id, collect(DISTINCT r.id) AS addressed
```

Move the `LIMIT` to the end and the query expands *every* message in the graph
before discarding all but one page. With several optional matches that
cross-multiply — a message with fifty recipients and twenty attachments is a
thousand intermediate rows — that difference is the whole cost of the query.

| `with_()` argument | Effect |
|---|---|
| `*variables` | Cypher variables, or expressions, to carry forward |
| `order_by=` / `desc=` | Sort the rows entering the next stage |
| `limit=` / `skip=` | Bound them; accepts `param()` |
| `where=` | Filter *after* the stage — Cypher's `HAVING` |
| `distinct=` | `WITH DISTINCT` |

`with_()` is repeatable, and stages interleave with traversals in the order you
write them.

::: warning Always order before you limit
Paging without an order is undefined in Cypher. Two runs of the same statement
may return different pages, which silently produces different results from the
same data.
:::

### Filtering on an aggregate

`where=` on a stage is the only way to filter a computed value, because a
`WHERE` before the aggregation cannot see it:

```python
(
    select(Message).alias("m")
    .traverse(Message.sent_to, from_="m").alias("r")
    .with_("m", count("*").as_("fanout"), where=col("fanout") > param("min"))
    .return_target("m")
)
# WITH m, count(*) AS fanout
# WHERE fanout > $min
```

---

## Fanning out from one node

By default each `traverse()` continues from wherever the previous one landed,
which walks a chain. `from_` anchors a traversal to a named variable instead, so
several can leave the same node:

```python
q = select(Message).alias("m")
q = q.traverse(Message.sent_from, from_="m").alias("s")
q = q.traverse(Message.sent_to, from_="m").alias("r")
q = q.traverse(Message.has_attachment, from_="m").alias("f")
```

```cypher
MATCH (m:Message)
OPTIONAL MATCH (m)-[:SENT_FROM]->(s:Address)
OPTIONAL MATCH (m)-[:SENT_TO]->(r:Address)
OPTIONAL MATCH (m)-[:HAS_ATTACHMENT]->(f:Attachment)
```

The alternative — one query per relationship — reads the same node once per edge
type. Fanning out reads it once, at the cost of intermediate rows that
`collect(distinct=True)` folds back:

```python
.aggregate(
    collect(col("s", Address.id), distinct=True).as_("senders"),
    collect(col("f", Attachment.id), distinct=True).as_("attachments"),
    group_by=col("m", Message.id).as_("id"),
)
```

---

## Relationship type alternation

Some relationships are *defined* as the walk over more than one type. `types=`
matches them in a single pattern:

```python
q.traverse(Message.sent_to, from_="m", types=["SENT_TO", "COPIED_TO"]).alias("r")
# OPTIONAL MATCH (m)-[:SENT_TO|COPIED_TO]->(r:Address)
```

Matching the two types as separate patterns is **not** the same query: anything
carrying both is matched twice and counted twice.

::: warning Not available on Apache AGE
AGE's openCypher subset has no alternation. runic refuses to emit it there with
a `NotImplementedError` naming the construct, rather than sending Cypher the
backend answers with a syntax error pointing at a character.
:::

### Direction override

A relation declared `direction="BOTH"` is undirected in *meaning*. When both
endpoints carry the same label, though, a directed pattern still matches every
edge — exactly once, where the undirected form matches it from each end:

```python
# Counting: an arrow avoids counting every edge twice
q.traverse(Address.co_addressed, edge_alias="r", optional=False,
           direction="OUTGOING").alias("b")

# Reading: no arrow, because which way it was stored is an accident of
# who was written to first — pair it with a.id < b.id to keep one row
q.traverse(Address.co_addressed, edge_alias="r", optional=False).alias("b")
```

---

## Backend capability differences

Backends implement different subsets of Cypher, and a statement using an
unsupported construct otherwise fails at the driver with a syntax error naming a
character — which says nothing about which builder call caused it. runic checks
before sending:

```python
NotImplementedError: AGE does not support relationship type alternation
([:A|B]). Express the query without it, or drop to a backend-specific
statement via session.execute().
```

The check happens when the statement is compiled for a session, not when it is
built, because a `select()` statement does not know its backend yet.

| Construct | FalkorDB | Neo4j | Memgraph | ArcadeDB | AGE |
|---|---|---|---|---|---|
| Relationship alternation `[:A\|B]` | ✓ | ✓ | ✓ | ✓ | ✗ |
| Undirected `MERGE` | ✗ | ✓ | ✓ | ✓ | ✓ |
| `CALL … YIELD` | ✓ | ✓ | ✓ | ✗ | ✗ |
| Fulltext search | ✓ | ✓ | ✓ | ✗ | ✗ |
| Vector search | ✓ | ✓ | ✓ | ✓ | ✗ |

---

## Writes: bulk upserts, batched deletes

The session's identity map is the right tool for writing a handful of entities.
It is the wrong one for a job that writes tens of thousands: that is one round
trip per node, and every one of them stays in memory until the session closes.

The write pipeline sends the lot in a single statement instead.

```python
from runic.ogm import count, encode_rows, param, row, select, unwind
```

### `UNWIND` + `MERGE` — upserting nodes

```python
MERGE_GROUPS = (
    unwind(param("rows"))
    .merge(Group, key={Group.id: row("id")}, alias="g")
    .set({Group.size: row("size"), Group.message_count: row("message_count")}, on="g")
)

session.execute_statement(MERGE_GROUPS, {"rows": encode_rows(Group, payload)})
```

```cypher
UNWIND $rows AS row
MERGE (g:Group {id: row.id})
SET g.size = row.size, g.message_count = row.message_count
```

::: tip Only the key goes in the `MERGE` pattern
Everything else belongs in the following `set()`. A property whose value changed
between runs would make `MERGE` fail to find the existing node and create a
second one.
:::

`MERGE` rather than `CREATE` because idempotence is usually the contract. A
derived label carries no unique constraint, so re-running a job that `CREATE`d
its output silently produces a second copy of every node — and every edge written
afterwards is written twice.

### Attaching edges

Match both endpoints, then merge between them:

```python
MERGE_ABOUT = (
    unwind(param("rows"))
    .match(Message, key={Message.id: row("message_id")}, alias="m")
    .match(Topic, key={Topic.id: row("topic_id")}, alias="t")
    .merge_edge("m", "ABOUT", "t", alias="r", edge_model=About)
    .set({About.score: row("score"), About.method: row("method")}, on="r")
)
```

`match()` and not `merge()` on the endpoints: a row naming a node that is not
there is a bug in the caller's ordering, and merging it would paper over that
with an empty node carrying nothing but a key — one no import can ever
reconcile.

Pass `directed=False` when the relationship is symmetric in meaning and the
stored direction is an accident of which end was written first:

```python
.merge_edge("a", "CO_ADDRESSED", "b", alias="r", directed=False)
# MERGE (a)-[r:CO_ADDRESSED]-(b)
```

::: warning FalkorDB rejects an undirected `MERGE`
It supports directed edges only. runic refuses to emit one there. Order the pair
canonically in the caller and merge with an arrow instead — and read it back the
same way.
:::

### `SET` — bulk property assignment

```python
CLEAR_EMBEDDINGS = (
    select(Message)
    .where(Message.embedding.is_not_null())
    .set({Message.embedding: None, Message.embedding_model: None})
    .returning(count("n").as_("cleared"))
)
```

`None` emits the literal `NULL`, which removes the property. Field converters
and the dialect's wrapping functions apply, so a value written here is stored the
way the mapper would store it — `vecf32()` on FalkorDB, raw elsewhere.

### `DELETE` — in batches

```python
DELETE_GROUPS = (
    select(Group)
    .with_("n", limit=param("batch"))
    .delete(detach=True)
    .returning(count("n").as_("removed"))
)
```

Loop until `removed` is zero. Batching through a `WITH` stage keeps one delete
from becoming a single long stall on a store something else is also reading.

::: danger `detach=True` on an edge destroys its endpoints
`DETACH DELETE` removes the incident edges of whatever it deletes. That is
required for a node. On an *edge* it takes both endpoints down with it — and for
a derived edge between two ground-truth nodes, that means destroying real data
to clean up a computed one.

```python
# Nodes: detach, because Cypher will not delete a node that has edges
.with_("n", limit=param("batch")).delete(detach=True)

# Edges: never detach — keep both endpoints
.with_("r", limit=param("batch")).delete("r")
```
:::

### A write returns nothing unless you ask

`returning()` is what makes a write report itself. Without it no `RETURN` is
emitted at all — the default would name the matched variable, which after a
`DELETE` names a node that no longer exists, and after a bulk `SET` would ship
every touched row back to the caller.

### Rows and converters

Values inside `$rows` never pass through the mapper, so a `datetime` there would
reach the driver as an object it has no encoding for. `encode_rows()` applies the
same field converters the mapper would:

```python
rows = encode_rows(Group, [{"id": "g1", "first_seen": some_datetime}])
# [{"id": "g1", "first_seen": "2026-03-04T00:00:00+00:00"}]
```

Keys that are not fields of the class pass through untouched, so an edge row can
carry `message_id` and `topic_id` alongside the edge's own properties.

---

## Terminal methods

Terminal methods execute the query and return results. Calling any of them
closes the builder chain.

| Method | Returns |
|--------|---------|
| `.all()` | `list[T]` — fully decoded, session-tracked node instances |
| `.one()` | `T \| None` — first result (adds `LIMIT 1`); `None` if empty |
| `.all_with_edges()` | `list[tuple]` — `(NodeA, Edge, NodeB)` tuples (requires `return_nodes` + `return_edge`) |
| `.all_rows()` | `list[dict]` — raw column-keyed dicts; used with `project()` and `aggregate()` |
| `.count()` | `int` — adds `count(*)` to `RETURN`; no node decoding |
| `.scalar()` | `Any` — first column of the first row; convenient for single-value aggregates |
| `.scalars()` | `list[Any]` — first column of every row; convenient with `project()` |
| `.build()` | `(str, dict)` — the Cypher string and parameter dict; does **not** execute the query |

**Choosing the right terminal method:**

* Default to `.all()` when you need trackable entities.
* Use `.one()` for lookups where you expect zero or one result.
* Use `.count()` or `.scalar()` for aggregates to avoid decoding overhead.
* Use `.all_rows()` for multi-column projections and aggregations.
* Use `.build()` to inspect, log, or test the generated Cypher.

---

## Full-text search

Full-text search uses a backend-specific `CALL` procedure instead of a
`MATCH` clause. The entry point is
`Session.fulltext_search()`, which returns a
specialised builder that has the same chaining and terminal methods as
`QueryBuilder`.

The backend procedure invoked depends on which driver you are using:

| Backend | Procedure |
|---------|-----------|
| FalkorDB | `CALL db.idx.fulltext.queryNodes('Label', $query) YIELD node AS n` |
| Neo4j | `CALL db.index.fulltext.queryNodes('Label', $query) YIELD node AS n` |
| Memgraph | `CALL text_search.search_all('label', $query) YIELD node` |
| ArcadeDB | Not supported |
| Apache AGE | Not supported; use PostgreSQL `tsvector`/`tsquery` via raw SQL |

A fulltext index on the target label must exist before querying. Create it
declaratively via `SchemaManager` or a
migration `op`:

```python
class Post(Node, labels=["Post"]):
    title: str = Field(index_type="FULLTEXT")
    body: str = Field(index_type="FULLTEXT")

posts: list[Post] = (
    session.fulltext_search(Post, query="graph databases")
    .where(Post.published == True)
    .order_by(Post.created_at, desc=True)
    .limit(20)
    .all()
)
```

The generated Cypher for FalkorDB:

```text
CALL db.idx.fulltext.queryNodes('Post', $__fts_query) YIELD node AS n
WHERE n.published = $p0
RETURN n
ORDER BY n.created_at DESC
LIMIT 20
```

Additional `.where()`, `.order_by()`, and `.limit()` clauses are appended
after the `CALL` block and apply to the nodes yielded by the procedure.

::: info See also
[examples/orm/11_query_builder_search.py](https://github.com/jenreh/runic/blob/main/examples/orm/11_query_builder_search.py)
— Full-text and vector search combined with `where()`, `order_by()`,
`limit()`, index creation via `IndexManager`, and `build()` to
inspect generated Cypher.
:::

---

## Vector KNN search

Vector KNN search finds the `k` nearest nodes to a query vector, using
approximate nearest-neighbour index procedures. Like full-text search, the
underlying procedure is backend-specific:

| Backend | Procedure |
|---------|-----------|
| FalkorDB | `vecf32(n.field) <-> vecf32($vec)` inline distance expression |
| Neo4j | `CALL db.index.vector.queryNodes('label_field', $k, $vec) YIELD node, score` |
| Memgraph | `CALL vector_search.search('label_field', $k, $vec) YIELD node, distance` |
| ArcadeDB | `CALL vector.neighbors('Type[field]', $vec, $k) YIELD node, distance` |
| Apache AGE | Not supported; use `pgvector` via raw SQL |

A vector index on the target field must exist. Runic's
`IndexManager` can create it, or you can
use a migration op.

```python
class Document(Node, labels=["Document"]):
    id: str = Field(primary_key=True)
    embedding: Vector = Field(index_type="VECTOR")

similar: list[Document] = (
    session.vector_search(
        Document,
        field=Document.embedding,
        vector=query_embedding,   # list[float]
        k=10,
    )
    .where(Document.active == True)
    .all()
)
```

The generated Cypher for FalkorDB:

```text
MATCH (n:Document)
WHERE n.active = $p0
RETURN n, vecf32(n.embedding) <-> vecf32($__knn_vec) AS __score
ORDER BY __score ASC
LIMIT 10
```

Results are ordered by ascending distance (closest first). You can override
the ordering with `.order_by()` after the call — but be aware that this
changes the `ORDER BY` clause, which may return non-nearest results.

::: info
Vector index creation requires a `dimension` parameter not stored in
`Field()` metadata. Pass it explicitly when calling
`IndexManager.create_vector_index()`, or pre-create the index via a
migration op or direct DDL.
:::

---

## Procedures: `call()`

Some things a query needs are not patterns — an index search, a graph algorithm.
`call()` invokes a procedure mid-query, and its arguments are ordinary
expressions, so it can be driven by a value from a node already matched:

```python
(
    select(Message).alias("m")
    .where(Message.embedding_model == param("model"))
    .call(
        "db.idx.vector.queryNodes",
        "Message", "embedding", param("k"), col("m", Message.embedding),
        yields=["node", "score"],
    )
    .with_("m", "node", "score")
    .where(var("node").is_not_null() & (var("score") <= param("max_distance")))
)
```

That is every node's nearest neighbours in **one** round trip, rather than one
KNN query per node.

Arguments follow one rule: a plain `str` is emitted as a Cypher string literal —
an index or label name the *model* supplies — and everything else is bound.
`var(name)` references something the query introduced rather than something a
model declares, such as a procedure's yield.

::: warning `call()` names a procedure literally
A statement using it is exactly as portable as that procedure. FalkorDB's vector
procedure is `db.idx.vector.queryNodes`, Neo4j's is `db.index.vector.queryNodes`
with a different argument order, Memgraph's is `vector_search.search`. For a
portable KNN use `session.vector_search()`, which asks the dialect. Reach for
`call()` when you need a specific backend's procedure — as a correlated KNN
does. ArcadeDB and Apache AGE have no `CALL … YIELD` at all.
:::

---

## Search scores

Both search builders expose the score the index produced, via `score()`. It can
be projected, filtered, or sorted on:

```python
from runic.ogm import col, param, score

session.all_rows(
    session.vector_search(
        Message, field=Message.embedding, vector=param("vector"), k=param("k")
    )
    .where(Message.embedding_model == param("model"))
    .project(col(Message.id).as_("id"), score().as_("distance"))
    .limit(param("limit")),
    {"vector": query_vec, "k": 200, "model": model, "limit": 20},
)
```

::: danger The two scores mean opposite things
A **vector** score is a *distance* — lower is closer. A **fulltext** score is a
*relevance* — higher is better. They are not comparable, and merging both into
one ranking without a stated normalisation invents an ordering neither index
produced.

runic normalises across backends so a vector score always means distance
(Neo4j reports a similarity; it is inverted for you). An exact match can come
back marginally negative, so anything converting it to a percentage must clamp.
:::

### Search width is not the row limit

`k` is how far into the index the search reaches. `limit` is how many rows the
caller sees. They are different numbers because **a procedure cannot be narrowed
before the fact**: a `MATCH` above it does not restrict what it searches, so
every row a following `where()` drops has already been paid for by `k`.

Asking for `k == limit` and then filtering returns a short page — which looks
exactly like a small database.

::: tip A missing vector is invisible, not low-ranked
A row with no vector is absent from the index entirely, and nothing in the
result says so. Report coverage alongside any semantic answer, or "the embedding
job is a third done" and "there is nothing here" produce the same output.

```python
select(Message).aggregate(
    count("*").as_("total"),
    count(when(Message.embedding_model == param("model"), 1)).as_("embedded"),
)
```
:::

---

## Index DDL at runtime

Indexes are declared on the model and created by a migration, and that is still
where they belong: a migration is a versioned statement about the schema every
installation shares.

A vector index is the exception. Its dimension follows whichever embedding model
is configured — a *setting*, chosen per installation — and re-running one
revision with a different constant is not something a migration chain can
express.

```python
from runic.ogm.schema.runtime_index import IndexOperations

ops = IndexOperations.from_driver(driver)

ops.create_vector_index(Message, Message.embedding, dimension=1536)
ops.resize_vector_index(Message, Message.embedding, dimension=768)
ops.drop_vector_index(Message, Message.embedding)

for spec in ops.describe():
    print(spec.label, spec.property, spec.index_type)
```

This is the same `IndexAdapter` the migration tool drives — exposure, not new
DDL. `from_driver()` works where the driver carries enough to build an adapter
(FalkorDB); elsewhere build one with `create_adapter(...)` and pass it in.

::: danger A wrong-length vector is accepted and never indexed
Backends store a vector of the wrong dimension as an ordinary property and
decline to index it — no exception, no log line. A job run against a mismatched
index therefore reports every row embedded and leaves every one unfindable.

Read `describe()` before writing vectors. And when the dimension changes, clear
the stored vectors: one kept at the old length is skipped by the very job meant
to replace it, because that job selects on "embedded by a different model", not
"embedded at a different length".
:::

---

## Async usage

`AsyncSession` returns an
`AsyncQueryBuilder` from `.query()`. The
chaining methods (`where`, `order_by`, `traverse`, etc.) are identical;
only the terminal methods are `async` and must be awaited:

```python
from runic.ogm import select

stmt = select(User).where(User.active == True).order_by(User.name).limit(50)
stmt_friends = (
    select(User).alias("u")
    .traverse(User.friends).alias("f")
    .where(User.age > 25, on="f")
)

async with AsyncSession(driver) as session:
    users: list[User] = await session.scalars(stmt)
    friends: list[User] = await session.scalars(stmt_friends)
```

::: info
Lazy relationship loading (accessing a `Relation` field outside a query)
is not supported in async context. Use `fetch=[...]` on
`session.get()` or model the relationship as a `.traverse()` in the
query builder instead.
:::

---

## Understanding and debugging generated Cypher

The `.build()` terminal method returns the query as a `(cypher, params)`
tuple without executing it. Use it to:

* Understand what the builder emits before running a query in production.
* Log slow queries with their actual parameter values.
* Write unit tests that assert on generated Cypher rather than on live data.
* Diagnose unexpected results by reading the exact query sent to the database.

```python
from runic.ogm import select

cypher: str
params: dict[str, Any]
cypher, params = (
    select(User).alias("u")
    .where(User.age > 18)
    .traverse(User.friends).alias("f")
    .where(User.active == True, on="f")
    .return_target("f")
    .build()
)

print(cypher)
# MATCH (u:User) WHERE (u.age > $p0)
# OPTIONAL MATCH (u)-[:FRIENDS]->(f:User)
# WHERE (f.active = $p1)
# RETURN f

print(params)
# {'p0': 18, 'p1': True}
```

Parameters are always positional (`$p0`, `$p1`, …) and listed in the order
they appear in the generated Cypher.

---

## When to use raw Cypher

The query builder covers the most common patterns, but some Cypher features are
not yet supported. For these, use the escape hatches directly:

```python
# Via Repository — result rows decoded to the repo's type
results: list[User] = repo.cypher(
    "MATCH (n:User)-[:FRIEND*2]-(m:User) WHERE n.id = $id RETURN m",
    {"id": user_id},
    returns=User,
)

# Via Session — raw GraphResult
result = session.execute(cypher, params)
```

Use raw Cypher when you need:

* `UNION` / `UNION ALL` across multiple patterns.
* `EXISTS { ... }` subqueries.
* `CALL { ... }` subqueries (correlated or uncorrelated).
* Pattern comprehensions (`[(a)-[:T]->(b) | b.prop]`).

For everything else, prefer the builder — it handles parameter binding,
alias generation, and result decoding automatically.

---

## Cypher feature coverage

| Feature | Support | How to use |
|---------|---------|------------|
| MATCH | ✓ | Root of every `session.query()` call |
| OPTIONAL MATCH | ✓ | Default for `.traverse()` |
| WHERE (comparison) | ✓ | `==`, `!=`, `>`, `>=`, `<`, `<=` |
| WHERE (string) | ✓ | `.contains()`, `.startswith()`, `.endswith()`, `.matches()` |
| WHERE (null) | ✓ | `.is_null()`, `.is_not_null()`, `== None` |
| WHERE (list) | ✓ | `.in_()`, `.not_in_()` |
| WHERE (boolean logic) | ✓ | `&`, `\|`, `~` |
| RETURN | ✓ | Automatic; customised by `return_target()`, `project()` |
| RETURN column aliases (`AS`) | ✓ | `.as_("name")` on any value expression |
| Scalar functions (`left`, `coalesce`, …) | ✓ | `fn()` and the named helpers |
| Property-to-property comparison | ✓ | `col("a", M.f) < col("b", M.f)` |
| Named bound parameters | ✓ | `param("name")`, `parameter_names()` |
| List membership on a list property | ✓ | `.any_of(value)` |
| ORDER BY | ✓ | `.order_by(field, desc=False)` |
| SKIP / LIMIT | ✓ | `.skip(n)`, `.limit(n)`; accepts `param("limit")` |
| DISTINCT | ✓ | `.distinct()` |
| WITH (multi-stage) | ✓ | `.with_(vars, order_by=, limit=, where=)`, repeatable |
| Relationship alternation `[:A\|B]` | ✓ | `.traverse(rel, types=[…])` — not on AGE |
| Fan-out from one node | ✓ | `.traverse(rel, from_="m")` |
| Direction override | ✓ | `.traverse(rel, direction="OUTGOING")` |
| Aggregation (count/avg/sum/…) | ✓ | `.aggregate(...)` + helpers from `runic.ogm.query` |
| UNWIND (bulk rows) | ✓ | `unwind(param("rows"))` |
| MERGE (node upsert) | ✓ | `.merge(Model, key={…})` |
| MERGE (edge upsert) | ✓ | `.merge_edge(src, "TYPE", tgt)` |
| SET (bulk assignment) | ✓ | `.set({Model.field: value})` |
| DELETE / DETACH DELETE | ✓ | `.delete(detach=True)` |
| Edge property filter | ✓ | `traverse(edge_alias=)` + `where(on=)` |
| Relationship traversal (1-hop) | ✓ | `.traverse(Cls.relation)` |
| Multi-hop traversal | ✓ | Chained `.traverse()` calls |
| Variable-length paths (`*n..m`) | ✓ | `.repeat(Cls.relation, min_hops=, max_hops=)` |
| Full-text search | ✓ | `session.fulltext_search()`; score via `score()` |
| Vector KNN (index-backed) | ✓ | `session.vector_search()`; `k` ≠ `limit` |
| Procedure calls (`CALL … YIELD`) | ✓ | `.call(name, *args, yields=[…])` |
| Correlated procedure calls | ✓ | pass `col(...)` as an argument |
| Runtime index DDL | ✓ | `IndexOperations` (not a statement — DDL is not a query) |
| TypeConverter in WHERE | ✓ | Auto-applied for `datetime`, `Enum`, `Vector`, `GeoLocation` |
| UNION / UNION ALL | ✗ | Use `repo.cypher()` |
| CASE expressions | ✓ | `when(cond, value)` — including inside aggregates |
| EXISTS { subpattern } | ✗ | Use `repo.cypher()` |
| CALL { ... } subqueries | ✗ | Use `repo.cypher()` |
| Pattern comprehensions | ✗ | Use `repo.cypher()` |

---

## Common pitfalls

**Use `all_rows()` for projections and aggregations, not `scalars()`**

`project()` and `aggregate()` return dictionaries, not entities.
`scalars()` will try to decode a dict as a node and fail:

```python
from runic.ogm.query import count

# BAD
results = session.scalars(select(User).aggregate(count("*").as_("total")))

# GOOD
results = session.all_rows(select(User).aggregate(count("*").as_("total")))
# [{"total": 42}]
```

**Parenthesise boolean operands**

Python operator precedence means `A.x == 1 & A.y == 2` parses as
`A.x == (1 & A.y) == 2`, which is almost certainly wrong. Always
parenthesise:

```python
# BAD
stmt = select(User).where(User.active == True & User.region == "DE")

# GOOD
stmt = select(User).where((User.active == True) & (User.region == "DE"))
```

**Edge property filters need `optional=False`**

The default `traverse()` emits `OPTIONAL MATCH`. A `WHERE` clause on
an `OPTIONAL MATCH` nullifies unmatched rows rather than dropping them,
causing `None` values in results. Use `optional=False` when you need to
filter on edge properties:

```python
stmt = (
    select(User).alias("u")
    .traverse(User.articles, edge_alias="e", optional=False)
    .alias("a")
    .where(Article.published == True, on="a")
)
```

**Don't alias an aggregation column the same as the node alias**

The default node alias is `n`. Naming an aggregation column `n` collides
with it and causes the decoder to treat the integer as a node:

```python
# BAD — "n" collides with the node alias
stmt = select(User).aggregate(count("*").as_("n"), group_by="n.city")

# GOOD
stmt = select(User).aggregate(count("*").as_("total"), group_by="n.city")
```

**Group by a field path, not the whole node alias**

`group_by="u"` groups by the entire node — one row per node. Pass the
field path to group by a property value:

```python
# BAD — groups per node, not per city
stmt = select(User).alias("u").aggregate(count("*").as_("total"), group_by="u")

# GOOD
stmt = select(User).alias("u").aggregate(count("*").as_("total"), group_by="u.city")
```

**Keep `datetime` values timezone-aware**

The built-in `DatetimeConverter` serialises to ISO-8601 and restores the
offset on read. A naive `datetime` (no `tzinfo`) will lose its timezone
on the round-trip:

```python
from datetime import datetime, UTC

# BAD — naive datetime
article.published_at = datetime(2026, 1, 1)

# GOOD — timezone-aware
article.published_at = datetime(2026, 1, 1, tzinfo=UTC)
```
