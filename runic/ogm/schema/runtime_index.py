"""Index DDL at runtime, for dimensions a migration cannot know.

Indexes are normally declared on the model and created by a migration, and that
is still the right place for them: a migration is a versioned statement about
the schema every installation shares.

A vector index is the exception.  Its dimension follows whichever embedding
model is configured, and that is a *setting* — a person picks the model, and the
length comes with it.  Re-running one revision with a different constant is not
something a migration chain can express, because the constant is not the same
for every installation.

This is a thin facade over the same :class:`~runic.migrate.adapters.IndexAdapter`
implementations the migration tool uses; nothing new is emitted here, it is only
reachable without writing a revision.

.. code-block:: python

    from runic.ogm.schema.runtime_index import IndexOperations

    ops = IndexOperations.from_driver(driver)

    # Re-index at the dimension the newly chosen model produces
    ops.drop_vector_index(Message, Message.embedding)
    ops.create_vector_index(Message, Message.embedding, dimension=1536)

.. warning::
    A backend will accept a vector of the wrong length, store it as an ordinary
    property, and decline to index it — with no exception and no log line.  A
    job run against a mismatched index therefore reports every row embedded and
    leaves every one of them unfindable.  Read :meth:`IndexOperations.describe`
    before writing vectors, and clear the stored ones whenever the dimension
    changes: a vector kept at the old length is skipped by the very job meant to
    replace it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runic.ogm.core.descriptors import FieldDescriptor
    from runic.ogm.schema.index_manager import IndexSpec

log = logging.getLogger(__name__)

__all__ = ["IndexOperations"]


class IndexOperations:
    """Create, drop and inspect indexes against a live graph.

    Parameters
    ----------
    adapter:
        A :class:`~runic.migrate.adapters.IndexAdapter` — the same object the
        migration tool drives.
    metadata:
        Model metadata, for resolving a class to its label. Defaults to the
        global registry.
    """

    def __init__(self, adapter: Any, metadata: Any = None) -> None:
        from runic.ogm.core.metadata import metadata as _global_metadata

        self._adapter = adapter
        self._meta = metadata or _global_metadata

    @classmethod
    def from_driver(cls, driver: Any, metadata: Any = None) -> IndexOperations:
        """Build from an OGM driver, reusing its open connection.

        Supported where the driver exposes enough to build an adapter — FalkorDB
        does.  For the others, build the adapter with
        :func:`~runic.migrate.adapters.create_adapter` and pass it to the
        constructor, which needs the connection details the driver does not
        carry.

        Raises
        ------
        NotImplementedError
            When the driver cannot yield an adapter on its own.
        """
        connect = getattr(driver, "falkordb_connection", None)
        if connect is not None:
            from runic.migrate.adapters.falkordb import FalkorDBAdapter

            db, graph = connect()
            return cls(FalkorDBAdapter(db, graph), metadata)

        backend = type(driver).__name__
        msg = (
            f"{backend} cannot produce an index adapter on its own. Build one "
            f"with runic.migrate.adapters.create_adapter(...) and pass it to "
            f"IndexOperations(adapter)."
        )
        raise NotImplementedError(msg)

    # ------------------------------------------------------------------
    # Vector indexes
    # ------------------------------------------------------------------

    def create_vector_index(
        self,
        cls: type,
        field: FieldDescriptor,
        *,
        dimension: int,
        similarity: str = "cosine",
    ) -> None:
        """Create a vector index at an explicit dimension.

        *dimension* must be the embedding model's real output length.  The
        schema tooling creates vector indexes with a placeholder dimension
        because it cannot know which model an installation chose; writing a real
        vector against that placeholder fails.
        """
        label, prop = self._resolve(cls, field)
        log.info(
            "creating vector index on %s.%s (dimension=%d, similarity=%s)",
            label,
            prop,
            dimension,
            similarity,
        )
        self._adapter.create_vector_index(label, prop, dimension, similarity)

    def drop_vector_index(self, cls: type, field: FieldDescriptor) -> None:
        """Drop a vector index.

        Paired with :meth:`create_vector_index` and not used alone: a graph left
        without the index answers every semantic search with an opaque driver
        error.
        """
        label, prop = self._resolve(cls, field)
        log.info("dropping vector index on %s.%s", label, prop)
        self._adapter.drop_vector_index(label, prop)

    def resize_vector_index(
        self,
        cls: type,
        field: FieldDescriptor,
        *,
        dimension: int,
        similarity: str = "cosine",
    ) -> None:
        """Rebuild a vector index at a new dimension.

        Drops and recreates in one call, because the pair is not optional: a
        graph between the two answers every search with a driver error.

        Does **not** clear the stored vectors — see the note in
        :meth:`describe`. Clear them separately, or the next embed job will skip
        the messages whose vectors are the wrong length.
        """
        try:
            self.drop_vector_index(cls, field)
        except Exception:  # noqa: BLE001 - absent is the state we want
            log.debug("no existing vector index to drop on %s", cls.__name__)
        self.create_vector_index(cls, field, dimension=dimension, similarity=similarity)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def describe(self) -> set[IndexSpec]:
        """Every index the graph actually has.

        Read this before writing vectors.  A backend accepts a vector of the
        wrong length, stores it as a plain property and never indexes it — with
        no error raised — so a job run against a mismatched index reports total
        success and leaves nothing findable.
        """
        return self._adapter.get_existing_specs()  # type: ignore[no-any-return]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve(self, cls: type, field: FieldDescriptor) -> tuple[str, str]:
        """Resolve a model class and field to ``(label, property)``."""
        meta = self._meta.get_node_meta(cls)
        if meta is None:
            msg = f"Class {cls.__name__!r} is not a registered Node subclass"
            raise ValueError(msg)
        return meta.primary_label, field.field_name
