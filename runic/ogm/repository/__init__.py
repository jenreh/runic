"""runic.ogm.repository — Repository and AsyncRepository."""

from runic.ogm.repository.async_repository import AsyncRepository
from runic.ogm.repository.repository import Repository

__all__ = [
    "AsyncRepository",
    "Repository",
]
