"""ORM-specific exceptions."""


class OrmError(Exception):
    """Base exception for runic OGM errors."""


class EntityNotFoundError(OrmError):
    """Raised when an entity cannot be found by its primary key."""


class DetachedEntityError(OrmError):
    """Raised when an operation is attempted on a detached entity."""


class FieldValidationError(OrmError):
    """Raised when a field value fails validation."""


class MetadataError(OrmError):
    """Raised for metadata registry errors (e.g. duplicate labels)."""


class LazyLoadError(OrmError):
    """Raised when lazy relationship loading cannot be performed.

    Occurs when accessing a lazy field on an entity in an async session
    (where ``__get__`` cannot await) or when the session is unavailable.
    Use ``fetch=[field_name]`` on ``session.get()`` for eager loading instead.
    """
