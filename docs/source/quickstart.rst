Quickstart
==========

Install runic, connect to FalkorDB, define a model, and persist it — all
on this page.

Installation
------------

.. code-block:: bash

   uv add runic-py    # or: pip install runic-py

FalkorDB must be running.  The simplest way for local development:

.. code-block:: bash

   docker run -p 6379:6379 falkordb/falkordb

Hello, Node
-----------

.. code-block:: python

   from runic.orm import Field, Node, Repository, Session, create_driver

   # 1. Define a model
   class Language(Node, labels=["Language"]):
       id: str = Field()
       title: str = Field()
       code: str = Field(unique=True)

   # 2. Connect
   driver = create_driver("falkordb", host="localhost", port=6379, graph="myapp")

   # 3. Create
   with Session(driver) as session:
       lang = Language(id="en", title="English", code="en")
       session.add(lang)
       session.commit()
       print(lang.id)   # "en"

   # 4. Read
   with Session(driver) as session:
       repo = Repository(session, Language)
       all_langs = repo.find_all()
       english = session.get(Language, "en")

   # 5. Update
   with Session(driver) as session:
       en = session.get(Language, "en")
       en.title = "English (UK)"      # marks _dirty = True
       session.commit()               # MERGE … SET on flush

   # 6. Delete
   with Session(driver) as session:
       en = session.get(Language, "en")
       session.delete(en)
       session.commit()


.. seealso::

   `examples/orm/01_simple_crud.py <https://github.com/jenreh/runic/blob/main/examples/orm/01_simple_crud.py>`_
      End-to-end runnable example covering create, read, update, delete, and basic query-builder usage.


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
