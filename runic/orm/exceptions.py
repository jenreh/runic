"""ORM-specific exceptions."""


class OrmError(Exception):
    """Base exception for runic ORM errors."""


class EntityNotFoundError(OrmError):
    """Raised when an entity cannot be found by its primary key."""


class DetachedEntityError(OrmError):
    """Raised when an operation is attempted on a detached entity."""


class FieldValidationError(OrmError):
    """Raised when a field value fails validation."""


class MetadataError(OrmError):
    """Raised for metadata registry errors (e.g. duplicate labels)."""
