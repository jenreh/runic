"""runic.orm.repository — Repository and AsyncRepository."""

from runic.orm.repository.async_repository import AsyncRepository
from runic.orm.repository.repository import Repository

__all__ = [
    "AsyncRepository",
    "Repository",
]
