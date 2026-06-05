from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from runic.migrate.exceptions import MultipleHeadsError

if TYPE_CHECKING:
    from runic.migrate.adapters import GraphAdapter

log = logging.getLogger(__name__)


class VersionNode:
    def __init__(self, adapter: GraphAdapter) -> None:
        self._adapter = adapter

    def get(self) -> list[str]:
        return self._adapter.get_version()

    def get_single(self) -> str | None:
        revisions = self.get()
        if not revisions:
            return None
        if len(revisions) > 1:
            raise MultipleHeadsError(
                f"multiple revision heads: {revisions!r} — use get() to retrieve all"
            )
        return revisions[0]

    def set(self, revision: str) -> None:
        self.set_multiple([revision])

    def set_multiple(self, revisions: list[str]) -> None:
        self._adapter.set_version(revisions)

    def clear(self) -> None:
        self._adapter.set_version([])
