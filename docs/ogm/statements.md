# Statement catalogues

A query layer that something else can reach — an HTTP handler, a background job,
an MCP server answering a model's questions — has a property worth stating
outright: **caller input can change which rows a statement returns, but never
what the statement does.**

That property does not come from the query builder. It comes from how the
statements are organised. This chapter describes the shape, and what runic gives
you for keeping it.

## The shape

A statement is a module-level constant, or it does not exist.

```python
# queries.py
from typing import Final

from runic.ogm import count, param, select

from myapp.models import Message

RECENT_MESSAGES: Final = (
    select(Message)
    .where(Message.id > param("after"))
    .project(Message.id, Message.subject)
    .order_by(Message.id)
    .limit(param("limit"))
)

MESSAGE_COUNT: Final = (
    select(Message)
    .where(Message.id.is_not_null())
    .project(count("*").as_("total"))
)

CATALOG: Final[Mapping[str, QueryBuilder[Any]]] = MappingProxyType({
    "RECENT_MESSAGES": RECENT_MESSAGES,
    "MESSAGE_COUNT": MESSAGE_COUNT,
})
```

Callers name a statement and supply values:

```python
rows = session.all_rows(RECENT_MESSAGES, {"after": cursor, "limit": 500})
```

Three things follow from that, and each is worth having on its own.

### 1. Caller input is a value, never a statement

Every value reaches the graph as a bound parameter. There is no formatting step
where an address or a subject line could become part of the query.

The builder enforces this rather than trusting it. The few places that accept a
raw string — `project()`, `order_by()` — validate it as a
plain property reference, so a payload carrying a second clause is rejected
rather than executed:

```python
select(Message).order_by("n.id DESC WITH n MATCH (x) DETACH DELETE x //")
# ValueError: invalid Cypher order_by term …; expected 'reference' or 'reference ASC|DESC'
```

### 2. Statements are reviewable

A named constant shows up in a diff. Adding one to the catalogue is a visible
line; changing what one does is a visible change. A query assembled from
fragments at request time is none of those things.

Writing `CATALOG` out by hand rather than scraping the module is deliberate for
the same reason: adding a statement without listing it is then something a
reviewer can see.

### 3. Statements are testable as a set

`parameter_names()` reports what a statement expects, read off the compiled
statement rather than maintained beside it, so it cannot drift:

```python
RECENT_MESSAGES.parameter_names()
# ('after', 'limit')
```

Which makes it possible to check the whole catalogue at once — bind every
statement's parameters, run the lot against a real backend:

```python
SAMPLES = {"after": "", "limit": 10}


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_every_statement_runs(name: str, session: Session) -> None:
    """A statement asserted only as a string has never actually been checked."""
    stmt = CATALOG[name]
    bindings = {p: SAMPLES[p] for p in stmt.parameter_names()}
    assert isinstance(session.all_rows(stmt, bindings), list)
```

This is the test that catches the statement nobody ran: the one behind a rarely
used branch, or the one that stopped compiling when a model changed.

## A missing parameter is an error

```python
session.all_rows(RECENT_MESSAGES, {"after": cursor})
# ValueError: statement is missing values for declared parameter(s): limit
```

Deliberately loud. An unsupplied `$parameter` is a null in Cypher: it matches
nothing and returns an empty result, which is indistinguishable from an empty
database. Failing is the only way that distinction survives.

## Statements are reusable

A statement built with `param()` binds none of its own values, so the same
object serves every call. Compiling it twice produces identical Cypher, and
nothing from one execution leaks into the next.

That is what makes a module-level constant safe to share across requests, and
what makes `Final` the right annotation for one.

## Writes belong in the catalogue too

The shape is not only for reads. A bulk upsert or a batched delete is a
statement like any other:

```python
MERGE_GROUPS: Final = (
    unwind(param("rows"))
    .merge(Group, key={Group.id: row("id")}, alias="g")
    .set({Group.size: row("size")}, on="g")
)

DELETE_GROUPS: Final = (
    select(Group)
    .with_("n", limit=param("batch"))
    .delete(detach=True)
    .returning(count("n").as_("removed"))
)
```

Remember `encode_rows()` for anything going into a `$rows` payload: values there
never pass through the mapper.

## What still needs raw Cypher

Index DDL. It is not a query, and it has no builder form — use
[`IndexOperations`](./query-builder#index-ddl-at-runtime) instead.

Beyond that, if you find yourself reaching for `session.execute()` inside a
catalogue, check the [feature coverage
table](./query-builder#cypher-feature-coverage) first: most of what used to need
a string does not any more.

When a statement genuinely does need a backend's own procedure, `call()` keeps
it inside the catalogue — it is still a named constant with bound parameters,
just not a portable one. Note the backend in a comment beside it.

## Serving a catalogue to a model

The catalogue shape is what makes "let a model query the database" a bounded
problem: the model chooses a name and supplies values, and the set of things it
can cause is exactly the set of statements you wrote.

Two things to keep in mind at that boundary:

- **A search string reaches the backend's own query language.** A bound
  parameter cannot inject Cypher, but a fulltext query still reaches a search
  syntax with operators of its own — `|`, a leading `-`, field prefixes, and
  characters that are outright syntax errors. Tokenise before binding.
- **Report what the answer does not cover.** A vector search over a partly
  embedded dataset returns a short, entirely plausible result set that looks
  like a complete search of a small one. Carry a coverage count with it.
