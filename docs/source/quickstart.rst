Quickstart
==========

Install runic, connect to FalkorDB, define a model, and persist it — all
on this page.

Installation
------------

.. code-block:: bash

   pip install runic-migrate    # or: uv add runic-migrate

FalkorDB must be running.  The simplest way for local development:

.. code-block:: bash

   docker run -p 6379:6379 falkordb/falkordb

Hello, Node
-----------

.. code-block:: python

   from falkordb import FalkorDB

   from runic.orm import Field, Node, Repository, Session

   # 1. Define a model
   class Language(Node, labels=["Language"]):
       id: str = Field()
       title: str = Field()
       code: str = Field(unique=True)

   # 2. Connect
   db = FalkorDB(host="localhost", port=6379)
   graph = db.select_graph("myapp")

   # 3. Create
   with Session(graph) as session:
       lang = Language(id="en", title="English", code="en")
       session.add(lang)
       session.commit()
       print(lang.id)   # "en"

   # 4. Read
   with Session(graph) as session:
       repo = Repository(session, Language)
       all_langs = repo.find_all()
       english = session.get(Language, "en")

   # 5. Update
   with Session(graph) as session:
       en = session.get(Language, "en")
       en.title = "English (UK)"      # marks _dirty = True
       session.commit()               # MERGE … SET on flush

   # 6. Delete
   with Session(graph) as session:
       en = session.get(Language, "en")
       session.delete(en)
       session.commit()

Key takeaways
-------------

* Models inherit from :class:`~runic.orm.core.models.Node` and declare
  fields with :func:`~runic.orm.core.descriptors.Field`.
* The :class:`~runic.orm.session.session.Session` is the unit of work.
  All mutations (``add``, ``delete``) go through it.
* :class:`~runic.orm.repository.repository.Repository` handles reads.
* ``session.commit()`` = ``flush()`` + clear pending/deleted sets.

.. seealso::

   :doc:`concepts` — object states, dirty tracking, identity map

   :doc:`../api` — full API reference
