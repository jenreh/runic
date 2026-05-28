from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class GraphProtocol(Protocol):
    """Minimal graph operations used by migrations."""


class Migration(ABC):
    version: str
    description: str

    @abstractmethod
    def up(self, graph: GraphProtocol) -> None:
        """Apply migration."""

    def down(self, graph: GraphProtocol) -> None:
        msg = "Rollback not supported for production migrations."
        raise NotImplementedError(msg)
