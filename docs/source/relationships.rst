Relationships
=============

``runic.orm`` models relationships as first-class graph edges.  This page
covers lazy loading, eager loading, polymorphic hierarchies, and edge
properties.

Declaring a relationship
------------------------

Use :func:`~runic.orm.core.descriptors.Relation` with ``relationship``,
``direction``, and ``target``.  Property fields use
:func:`~runic.orm.core.descriptors.Field` — the two are intentionally
separate:

.. code-block:: python

   from runic.orm import Field, Node, Relation

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

.. seealso::

   `examples/orm/03_relationships_and_edges.py <https://github.com/jenreh/runic/blob/main/examples/orm/03_relationships_and_edges.py>`_
      Full runnable example: declaring relationships, lazy vs eager loading, ``relate()`` / ``unrelate()``, and edge-property queries.

Lazy loading (default)
----------------------

Relationship fields are **not** loaded when the entity is fetched.
Accessing the attribute triggers a graph query on first read:

.. code-block:: python

   with Session(driver) as session:
       person = session.get(Person, "alice")
       company = person.company     # ← one Cypher query here

.. note::

   In an :class:`~runic.orm.session.async_session.AsyncSession`, lazy loading
   raises :exc:`~runic.orm.exceptions.LazyLoadError` because ``__get__``
   cannot ``await``.  Use ``fetch=[...]`` instead.

Eager loading
-------------

Pass ``fetch=["field_name", ...]`` to ``session.get()`` or any
:class:`~runic.orm.repository.repository.Repository` read:

.. code-block:: python

   with Session(driver) as session:
       # Single entity
       person = session.get(Person, "alice", fetch=["company"])
       company = person.company    # ← no extra query

   with Session(driver) as session:
       repo = Repository(session, Person)
       # Entire collection
       people = repo.find_all(fetch=["company"])

The Mapper builds a single Cypher query with one ``OPTIONAL MATCH`` per
entry in ``fetch``.  Related entities are also registered in the session's
identity map.

.. seealso::

   `examples/orm/02_polymorphic_locations.py <https://github.com/jenreh/runic/blob/main/examples/orm/02_polymorphic_locations.py>`_
      Multi-label hierarchy (``Location → Country, City, Restaurant``) with subtype resolution and repository queries.

Polymorphic hierarchies
-----------------------

Nodes can carry multiple labels and form inheritance chains.  Declare a
``primary_label`` to control which label is used in ``MATCH`` statements:

.. code-block:: python

   class Location(Node, labels=["Location"], primary_label="Location"):
       id: str = Field()
       title: str = Field()

   class Country(Location, labels=["Location", "Country"], primary_label="Location"):
       iso_code: str = Field(unique=True)

   class City(Location, labels=["Location", "City"], primary_label="Location"):
       population: int | None = Field(default=None)

Querying via the parent class returns all subtypes; each node is decoded to
its most specific registered class:

.. code-block:: python

   with Session(driver) as session:
       repo = Repository(session, Location)
       all_locs = repo.find_all()
       # returns a mix of Country, City, etc. — type-resolved per node
       for loc in all_locs:
           print(type(loc).__name__, loc.title)

Mutating relationships
----------------------

Use :meth:`~runic.orm.session.session.Session.relate` and
:meth:`~runic.orm.session.session.Session.unrelate` to create, update, or
remove relationships without writing Cypher:

.. code-block:: python

   with Session(driver) as session:
       alice = session.get(User, "alice")
       company = session.get(Company, "acme")

       # Create (or update) the relationship — MERGE semantics
       session.relate(alice, User.company, company)

       # Remove the relationship
       session.unrelate(alice, User.company, company)

``relate()`` is idempotent: calling it a second time does not duplicate the
edge.  The cached field value on the source entity is invalidated after each
mutation so the next access re-fetches from the graph.

For async sessions the same methods are available as coroutines:

.. code-block:: python

   async with AsyncSession(driver) as session:
       alice = await session.get(User, "alice")
       company = await session.get(Company, "acme")
       await session.relate(alice, User.company, company)

Edge properties
---------------

When a relationship carries its own properties, declare an
:class:`~runic.orm.core.models.Edge` subclass and pass it via
``edge_model``:

.. code-block:: python

   from runic.orm import Edge, Field, Node, Relation

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

Pass an ``Edge`` instance to ``relate()`` to write properties onto the
relationship.  Because ``relate()`` uses ``MERGE``, calling it again with
updated values will overwrite the existing properties:

.. code-block:: python

   with Session(driver) as session:
       user = session.get(User, "alice")
       trip = session.get(Trip, "paris-2026")

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

Read edge properties back via the query builder:

.. code-block:: python

   from runic.orm import Repository

   class UserRepository(Repository[User]):
       def get_invitation(self, user_id: str, trip_id: str) -> InvitationEdge | None:
           rows = (
               self.query()
               .where(User.id == user_id)
               .alias("u")
               .traverse(User.invited_trips, edge_alias="e", optional=False)
               .alias("t")
               .where(Trip.id == trip_id, on="t")
               .return_nodes("u", "t").return_edge("e")
               .all_with_edges()
           )
           if not rows:
               return None
           _, edge, _ = rows[0]
           return edge

Cascade saves
-------------

Set ``cascade=True`` on a ``Relation`` to automatically stage related
entities when the owning entity is added:

.. code-block:: python

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
       session.add(person)     # also stages company
       session.commit()
       assert company.id is not None
