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
       id: str = Field()
       name: str = Field()

   class Person(Node, labels=["Person"]):
       id: str = Field()
       name: str = Field()
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

Lazy loading (default)
----------------------

Relationship fields are **not** loaded when the entity is fetched.
Accessing the attribute triggers a graph query on first read:

.. code-block:: python

   with Session(graph) as session:
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

   with Session(graph) as session:
       # Single entity
       person = session.get(Person, "alice", fetch=["company"])
       company = person.company    # ← no extra query

   with Session(graph) as session:
       repo = Repository(session, Person)
       # Entire collection
       people = repo.find_all(fetch=["company"])

The Mapper builds a single Cypher query with one ``OPTIONAL MATCH`` per
entry in ``fetch``.  Related entities are also registered in the session's
identity map.

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

   with Session(graph) as session:
       repo = Repository(session, Location)
       all_locs = repo.find_all()
       # returns a mix of Country, City, etc. — type-resolved per node
       for loc in all_locs:
           print(type(loc).__name__, loc.title)

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

Read edge properties back with a custom Cypher query in your Repository:

.. code-block:: python

   from runic.orm import Repository

   class UserRepository(Repository[User]):
       def get_invitation(self, user_id: str, trip_id: str) -> dict | None:
           return self.cypher_one(
               """
               MATCH (u:User {id: $uid})-[e:INVITED_TO]->(t:Trip {id: $tid})
               RETURN e.role AS role, e.status AS status,
                      e.invited_at AS invited_at, e.accepted_at AS accepted_at
               """,
               {"uid": user_id, "tid": trip_id},
               returns=dict,
           )

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

   with Session(graph) as session:
       company = Company(id="acme", name="Acme")
       person = Person(id="alice", name="Alice", company=company)
       session.add(person)     # also stages company
       session.commit()
       assert company.id is not None
