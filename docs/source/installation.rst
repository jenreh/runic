Installation
============

Requirements
------------

* Python 3.14 or newer
* A running `FalkorDB <https://falkordb.com>`_ instance **or**
  `falkordblite <https://pypi.org/project/falkordblite/>`_ for embedded
  testing without an external server

Install from PyPI
-----------------

.. code-block:: bash

   pip install runic

With **uv** (recommended):

.. code-block:: bash

   uv add runic

Verify the installation:

.. code-block:: bash

   runic --help

You should see the runic help text listing all available commands.

FalkorDB
--------

runic talks to FalkorDB via the official `falkordb <https://pypi.org/project/falkordb/>`_
Python client, which is declared as a direct dependency and installed
automatically.

For a quick local FalkorDB instance with Docker:

.. code-block:: bash

   docker run -p 6379:6379 falkordb/falkordb

For integration testing without an external server, install
`falkordblite <https://pypi.org/project/falkordblite/>`_:

.. code-block:: bash

   uv add --dev falkordblite

See :doc:`migration/testing` for how to use the embedded server in your test suite.

Development install
-------------------

Clone the repository and install all dev dependencies:

.. code-block:: bash

   git clone https://github.com/jenreh/runic
   cd runic
   uv sync --all-groups
