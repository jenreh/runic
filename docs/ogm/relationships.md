# Relationships

`runic.ogm` models relationships as first-class graph edges.  When you
declare a `Relation()` on a model, the ORM
knows the edge type, direction, and target class — enough to generate
`MATCH`/`OPTIONAL MATCH` traversal patterns without any hand-written
Cypher.

This page covers how to declare relationships, when to load them eagerly or
lazily, how to create and remove edges at runtime, how to carry properties on
edges, and how polymorphic hierarchies interact with relationships.

---

## Declaring a relationship

Use `Relation()` with `relationship`,
`direction`, and `target`.  Property fields use
`Field()` — the two are intentionally separate
so that scalar data and graph topology never mix:

```python
from runic.ogm import Field, Node, Relation

class Company(Node, labels=["Company"]):
    id: str = Field(primary_key=True, generated=True)
    name: str = Field(index=True)

class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True, generated=True)
    name: str = Field(index=True)
    # single outgoing relationship
    company: Company | None = Relation(
        relationship="WORKS_FOR",
        direction="OUTGOING",
        target="Company",
    )
    # collection
    reports: list["Person"] = Relation(
        relationship="MANAGES",
        direction="OUTGOING",
        target="Person",
    )
```

Use a forward-reference string (`"Company"`) when the target class is
defined later in the module or in a separate file.  The registry resolves it
at import time.

::: info See also
[examples/orm/03_relationships_and_edges.py](https://github.com/jenreh/runic/blob/main/examples/orm/03_relationships_and_edges.py)
Full runnable example: declaring relationships, lazy vs eager loading, `relate()` / `unrelate()`, and edge-property queries.
:::

---

## Declaring the same relationship on both sides

When you need to traverse an edge starting from either end, declare the
`Relation` on *both* node classes using opposite directions.  The graph
stores a single directed edge; the two declarations are just different
read-views onto it:

```python
from runic.ogm import Field, Node, Relation

class Team(Node, labels=["Team"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    # INCOMING: the same MEMBER_OF edges seen from the Team side
    members: list["Person"] = Relation(
        relationship="MEMBER_OF",
        direction="INCOMING",
        target="Person",
    )

class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    # OUTGOING: the canonical source of truth for the edge direction
    team: Team | None = Relation(
        relationship="MEMBER_OF",
        direction="OUTGOING",
        target="Team",
    )
```

Both attributes traverse the same `MEMBER_OF` edges in the graph.
`person.team` follows `(person)-[:MEMBER_OF]->(team)`;
`team.members` follows `(team)<-[:MEMBER_OF]-(person)`.
Call `session.relate()` on either side — it always writes the same
physical edge:

```python
with Session(driver) as session:
    alice: Person | None = session.get(Person, "alice")
    eng: Team | None = session.get(Team, "engineering")
    assert alice is not None and eng is not None

    # Write via the Person side (OUTGOING)
    session.relate(alice, Person.team, eng)

with Session(driver) as session:
    eng = session.get(Team, "engineering")
    assert eng is not None
    # Read back via the Team side (INCOMING mirror)
    members: list[Person] = eng.members
    print([m.name for m in members])  # ["Alice"]
```

The key rule: only *one* of the declarations should be used with
`session.relate()` — the direction you used when writing the edge
must be consistent. Using `OUTGOING` from `Person` and
`INCOMING` from `Team` both describe the arrow
`(Person)-[:MEMBER_OF]->(Team)`.

---

## Bidirectional relationships (`direction="BOTH"`)

Use `direction="BOTH"` when the relationship has no inherent orientation —
friendship, co-authorship, contact networks.  The OGM generates an
*undirected* Cypher pattern `(a)-[r:TYPE]-(b)`, so the edge is found
regardless of which node acts as source:

```python
class Person(Node, labels=["Person"]):
    id: str = Field(primary_key=True)
    name: str = Field()
    contacts: list["Person"] = Relation(
        relationship="KNOWS",
        direction="BOTH",
        target="Person",
    )
```

Create the edge once from either side; it is readable from both:

```python
with Session(driver) as session:
    alice: Person | None = session.get(Person, "alice")
    bob: Person | None = session.get(Person, "bob")
    assert alice is not None and bob is not None
    session.relate(alice, Person.contacts, bob)

with Session(driver) as session:
    alice = session.get(Person, "alice")
    bob = session.get(Person, "bob")
    assert alice is not None and bob is not None

    # Both sides see the edge
    print(alice.contacts)  # [bob]
    print(bob.contacts)    # [alice]
```

::: info
`direction="BOTH"` uses `MERGE (a)-[r:TYPE]-(b)` when writing on
backends that support undirected `MERGE` (Neo4j, Memgraph, ArcadeDB,
Apache AGE).

**FalkorDB exception** — FalkorDB rejects undirected `MERGE`.  The ORM
automatically falls back to `MERGE (a)-[r:TYPE]->(b)` (`OUTGOING`) on
FalkorDB, so the edge is stored with a physical direction.
`MATCH (a)-[r:TYPE]-(b)` still finds it from both ends during reads.
You do not need to change your model declaration; the fallback is
transparent.  The behaviour is controlled by
`FalkorDBDialect.supports_undirected_merge = False`.
:::

---

## Lazy loading (default)

Relationship fields are **not** loaded when the entity is fetched.
Accessing the attribute triggers a graph query on first read:

```python
with Session(driver) as session:
    person: Person | None = session.get(Person, "alice")
    assert person is not None
    company: Company | None = person.company     # ← one OPTIONAL MATCH here
```

Lazy loading means a repository `find_all()` that returns 100 people does
not automatically run 100 follow-up queries.  Relationships are fetched only
if you actually access them.

::: info
In an `AsyncSession`, lazy loading
raises `LazyLoadError` because `__get__`
cannot `await`.  Use `fetch=[...]` to load relationships eagerly in
async code.
:::

---

## Eager loading

Pass `fetch=["field_name", ...]` to `session.get()` or any
`Repository` read to load
relationships in a single query.  The mapper adds one `OPTIONAL MATCH`
clause per entry in `fetch`:

```python
with Session(driver) as session:
    # Single entity with relationship pre-loaded
    person: Person | None = session.get(Person, "alice", fetch=["company"])
    assert person is not None
    company: Company | None = person.company    # ← no extra query

with Session(driver) as session:
    repo = Repository(session, Person)
    # Entire collection with relationships pre-loaded
    people: list[Person] = repo.find_all(fetch=["company"])
```

When to use eager loading:

* You know you will access the relationship for every entity in the result.
* You are using an `AsyncSession` (lazy loading is not available).
* You are returning the result to a serialiser that touches every field.

When to use lazy loading (default):

* You only need the relationship for some entities in the result.
* You want to defer the query cost to the point of actual access.

Related entities loaded via `fetch` are also registered in the session's
identity map, so subsequent `session.get()` calls return the same objects.

::: info See also
[examples/orm/02_polymorphic_locations.py](https://github.com/jenreh/runic/blob/main/examples/orm/02_polymorphic_locations.py)
Multi-label hierarchy (`Location → Country, City, Restaurant`) with subtype resolution and repository queries.
:::

---

## Polymorphic hierarchies

Nodes can carry multiple labels and form inheritance chains.  Declare a
`primary_label` on both the parent and each subclass to ensure
`MATCH (n:Location)` matches all subtypes:

```python
class Location(Node, labels=["Location"], primary_label="Location"):
    id: str = Field()
    title: str = Field()

class Country(Location, labels=["Location", "Country"], primary_label="Location"):
    iso_code: str = Field(unique=True)

class City(Location, labels=["Location", "City"], primary_label="Location"):
    population: int | None = Field(default=None)
```

Querying via the parent class returns all subtypes.  The mapper decodes each
node to its most specific registered class based on which labels it carries:

```python
with Session(driver) as session:
    repo = Repository(session, Location)
    all_locs: list[Location] = repo.find_all()
    # returns a mix of Country, City, etc. — each decoded to its concrete type
    for loc in all_locs:
        print(type(loc).__name__, loc.title)
```

Use this pattern when you need to store and query entities that share
common fields but also carry type-specific fields — and when the type is
expressed by a graph label rather than a property value.

---

## Mutating relationships

Use `relate()` and
`unrelate()` to create, update, or
remove relationships without writing Cypher:

```python
with Session(driver) as session:
    alice: Person | None = session.get(Person, "alice")
    company: Company | None = session.get(Company, "acme")
    assert alice is not None and company is not None

    # Create (or update) the relationship — MERGE semantics
    session.relate(alice, Person.company, company)

    # Remove the relationship
    session.unrelate(alice, Person.company, company)
```

`relate()` is idempotent: calling it a second time does not duplicate the
edge.  Under the hood it issues `MERGE (a)-[:WORKS_FOR]->(b)`; if the edge
already exists the `MERGE` matches it without creating a duplicate.

The cached field value on the source entity is invalidated after each
mutation so that the next attribute access re-fetches from the graph.

For async sessions the same methods are available as coroutines:

```python
async with AsyncSession(driver) as session:
    alice = await session.get(Person, "alice")
    company = await session.get(Company, "acme")
    assert alice is not None and company is not None
    await session.relate(alice, Person.company, company)
```

---

## Edge properties

When a relationship carries its own properties, declare an
`Edge` subclass and pass it via
`edge_model`.  The OGM maps the edge properties exactly as it maps node
properties, including dirty tracking and type converters:

```python
from runic.ogm import Edge, Field, Node, Relation

class InvitationEdge(Edge, type="INVITED_TO"):
    role: str = Field()
    status: str = Field()
    invited_at: str = Field()          # ISO-8601
    accepted_at: str | None = Field(default=None)

class User(Node, labels=["User"]):
    id: str = Field()
    invited_trips: list["Trip"] = Relation(
        relationship="INVITED_TO",
        direction="OUTGOING",
        target="Trip",
        edge_model=InvitationEdge,
    )
```

Pass an `Edge` instance to `relate()` to write properties onto the
relationship.  Because `relate()` uses `MERGE`, calling it again with
updated values overwrites the existing properties:

```python
with Session(driver) as session:
    user: User | None = session.get(User, "alice")
    trip: Trip | None = session.get(Trip, "paris-2026")
    assert user is not None and trip is not None

    # Create — or update if the edge already exists
    session.relate(
        user,
        User.invited_trips,
        trip,
        edge=InvitationEdge(
            role="owner",
            status="accepted",
            invited_at="2026-01-01T00:00:00",
        ),
    )
```

Read edge properties back via the query builder's `all_with_edges()`
terminal method, which returns `list[tuple[NodeA, EdgeModel, NodeB]]`.

Using a session-bound repository query (classic pattern):

```python
from runic.ogm import Repository

class UserRepository(Repository[User]):
    def get_invitation(self, user_id: str, trip_id: str) -> InvitationEdge | None:
        rows: list[tuple[User, InvitationEdge, Trip]] = (
            self.query()
            .where(User.id == user_id)
            .alias("u")
            .traverse(User.invited_trips, edge_alias="e", optional=False)
            .alias("t")
            .where(Trip.id == trip_id, on="t")
            .return_nodes("u", "t")
            .return_edge("e")
            .all_with_edges()
        )
        if not rows:
            return None
        _, edge, _ = rows[0]
        return edge
```

Alternatively, use `select()` to build the statement
independently and execute it via `session.all_with_edges(stmt)`:

```python
from runic.ogm import select

stmt = (
    select(User)
    .where(User.id == user_id)
    .alias("u")
    .traverse(User.invited_trips, edge_alias="e", optional=False)
    .alias("t")
    .where(Trip.id == trip_id, on="t")
    .return_nodes("u", "t")
    .return_edge("e")
)
rows: list[tuple[User, InvitationEdge, Trip]] = session.all_with_edges(stmt)
```

::: info See also
[query_builder](./query-builder.md) — traversal, edge aliases, `all_with_edges()`, and filtering on edge properties
:::

---

## Cascade saves

Set `cascade=True` on a `Relation` to automatically stage related
entities when the owning entity is added to the session.  Useful when you
construct an entity graph in memory and want one `session.add()` call to
persist the whole thing:

```python
class Person(Node, labels=["Person"]):
    id: str = Field()
    name: str = Field()
    company: Company | None = Relation(
        relationship="WORKS_FOR",
        direction="OUTGOING",
        target="Company",
        cascade=True,
    )

with Session(driver) as session:
    company = Company(id="acme", name="Acme")
    person = Person(id="alice", name="Alice", company=company)
    session.add(person)     # also stages company via cascade
    session.commit()
    assert company.id is not None
```

Without `cascade=True`, you would need to call `session.add(company)`
explicitly before the commit.  Use cascade when the related entity is always
created alongside the owning entity; omit it for relationships that connect
independently-managed entities.
