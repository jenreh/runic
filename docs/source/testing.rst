Test your OGM code
==================

runic.ogm is designed to be testable without a running graph database server.
This page covers the recommended testing setup for OGM models, sessions, and
repositories, using embedded FalkorDB.

.. seealso::

   :doc:`migration/testing` — round-trip testing for migration scripts with
   ``runic test``.

----

Embedded FalkorDB
------------------

`redislite <https://pypi.org/project/redislite/>`_ bundles a Redis-compatible
server that FalkorDB can use as an in-process backend.  No Docker, no external
process.

Install the extra:

.. code-block:: bash

   uv add --dev redislite
   # or
   pip install redislite

Create a driver:

.. code-block:: python

   from redislite import FalkorDB
   from runic.ogm.driver.falkordb import FalkorDBDriver

   def make_driver(graph_name: str = "test") -> FalkorDBDriver:
       db = FalkorDB(protocol=2)          # protocol=2 avoids a redis-py 8 issue
       return FalkorDBDriver(db.select_graph(graph_name))

.. warning::

   The embedded backend does not support regex ``=~`` (``Field.matches()``),
   fulltext indexes, or vector KNN.  For those features you need a live
   FalkorDB v4+ server.

----

.. _unique-graph-names:

Unique graph names matter
--------------------------

runic.ogm registers metadata (label maps, field specs) in a global registry
when a ``Node``/``Edge`` class is defined.  If two test modules share the same
graph name on the same embedded backend, leftover nodes from one module can
bleed into the other.

**Always give each test module a unique graph name:**

.. code-block:: python

   # tests/test_users.py
   GRAPH_NAME = "test_users"

   # tests/test_articles.py
   GRAPH_NAME = "test_articles"

Alternatively, derive the name from ``__name__``:

.. code-block:: python

   GRAPH_NAME = __name__.replace(".", "_")

----

pytest fixtures
----------------

A minimal ``conftest.py`` for a single test module:

.. code-block:: python

   # tests/conftest.py
   import pytest
   from redislite import FalkorDB
   from runic.ogm import Session
   from runic.ogm.driver.falkordb import FalkorDBDriver


   @pytest.fixture
   def falkordb_graph():
       db = FalkorDB(protocol=2)
       return db.select_graph("test")


   @pytest.fixture
   def driver(falkordb_graph):
       return FalkorDBDriver(falkordb_graph)


   @pytest.fixture
   def session(driver):
       with Session(driver) as s:
           yield s

Use it in tests:

.. code-block:: python

   def test_create_user(session):
       session.add(User(id="alice", name="Alice", email="alice@example.com"))
       session.commit()

       user = session.get(User, "alice")
       assert user is not None
       assert user.name == "Alice"

----

Testing CRUD
-------------

.. code-block:: python

   from runic.ogm import Repository, Session, select

   def test_update_user(session):
       session.add(User(id="bob", name="Bob", email="bob@example.com"))
       session.commit()

       user = session.get(User, "bob")
       user.name = "Robert"
       session.commit()

       updated = session.get(User, "bob")
       assert updated.name == "Robert"

   def test_delete_user(session):
       session.add(User(id="carol", name="Carol", email="c@example.com"))
       session.commit()

       user = session.get(User, "carol")
       session.delete(user)
       session.commit()

       assert session.get(User, "carol") is None

----

Testing queries
----------------

.. code-block:: python

   def test_query_by_name(session):
       session.add_all([
           User(id="u1", name="Alice", email="a@example.com", active=True),
           User(id="u2", name="Bob",   email="b@example.com", active=False),
       ])
       session.commit()

       active = session.scalars(select(User).where(User.active == True))
       assert len(active) == 1
       assert active[0].name == "Alice"

----

Testing relationships
----------------------

.. code-block:: python

   def test_relate_users(session):
       alice = User(id="alice", name="Alice", email="a@example.com")
       bob   = User(id="bob",   name="Bob",   email="b@example.com")
       session.add_all([alice, bob])
       session.commit()

       session.relate(alice, User.knows, bob)
       session.commit()

       loaded = session.get(User, "alice", fetch=["knows"])
       assert any(u.id == "bob" for u in loaded.knows)

----

Testing with repositories
--------------------------

.. code-block:: python

   from runic.ogm import Repository

   def test_repository_count(session):
       repo = Repository(session, User)
       assert repo.count() == 0

       session.add(User(id="u1", name="Alice", email="a@example.com"))
       session.commit()

       assert repo.count() == 1

   def test_custom_repository(session):
       repo = UserRepository(session)   # subclass of Repository[User]
       session.add_all([
           User(id="u1", name="Alice", email="a@example.com", region="DE"),
           User(id="u2", name="Bob",   email="b@example.com", region="US"),
       ])
       session.commit()

       results = repo.active_in_region("DE")
       assert len(results) == 1

----

Testing polymorphism
---------------------

.. code-block:: python

   def test_polymorphic_query(session):
       session.add_all([
           City(id="BER", title="Berlin", population=3_600_000),
           Country(id="DE", title="Germany", iso_code="DE"),
       ])
       session.commit()

       # Query the base class — returns both City and Country instances
       locations = session.scalars(select(Location))
       assert len(locations) == 2

       # Query subtype — only cities
       cities = session.scalars(select(City))
       assert len(cities) == 1
       assert cities[0].id == "BER"

----

Testing async code
-------------------

Use ``pytest-asyncio`` with an async fixture:

.. code-block:: bash

   uv add --dev pytest-asyncio

.. code-block:: python

   # conftest.py (async variant)
   import pytest_asyncio
   from redislite import FalkorDB
   from runic.ogm import AsyncSession
   from runic.ogm.driver.falkordb import AsyncFalkorDBDriver


   @pytest_asyncio.fixture
   async def async_session():
       db = FalkorDB(protocol=2)
       driver = AsyncFalkorDBDriver(db.select_graph("test_async"))
       async with AsyncSession(driver) as session:
           yield session

.. code-block:: python

   # test_async.py
   import pytest

   @pytest.mark.asyncio
   async def test_async_create(async_session):
       async_session.add(User(id="u1", name="Alice", email="a@example.com"))
       await async_session.commit()

       # Always eager-fetch in async — no lazy loading
       user = await async_session.get(User, "u1")
       assert user is not None

----

Common testing pitfalls
------------------------

**Graph state leaks between tests**
   Use a fresh embedded FalkorDB per test, or run ``MATCH (n) DETACH DELETE n``
   in a ``teardown_function`` / ``autouse`` fixture.  The simplest approach: use
   a function-scoped ``driver`` fixture.

**Metadata label collisions**
   If two test modules use the same graph name on the same embedded backend,
   labels from one module bleed into the other.  Give each module a unique name
   (see :ref:`unique-graph-names`).

**Async + lazy loading**
   Accessing an unloaded relation in an ``AsyncSession`` raises
   :exc:`~runic.ogm.exceptions.LazyLoadError`.  Always ``fetch=[]`` or use
   a traversal query.  See :doc:`async` for details.

**regex / fulltext / vector unsupported in redislite**
   Move tests that require these features to a separate integration test suite
   marked ``@pytest.mark.integration`` and run them against a live FalkorDB
   server.  In CI, use the ``falkordblite`` binary (provided by the
   ``falkordblite`` package) as a lightweight FalkorDB server.

----

See also
---------

* :doc:`async` — async session patterns and testing
* :doc:`migration/testing` — ``runic test`` for migration round-trip tests
* :doc:`drivers` — backend feature matrix (what embedded supports)
