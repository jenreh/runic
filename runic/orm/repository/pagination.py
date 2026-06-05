"""Pageable and Page[T] for cursor-style pagination over Repository reads."""

from __future__ import annotations

import math
from collections.abc import Iterator


class Pageable:
    """Describes a page request: zero-based page index, page size, and optional sort.

    Example::

        pageable = Pageable(page=0, size=25, sort_by="name", direction="ASC")
        next_page = pageable.next()
    """

    def __init__(
        self,
        page: int = 0,
        size: int = 20,
        sort_by: str | None = None,
        direction: str = "ASC",
    ) -> None:
        if page < 0:
            raise ValueError("page must be >= 0")
        if size <= 0:
            raise ValueError("size must be > 0")
        self.page = page
        self.size = size
        self.sort_by = sort_by
        self.direction = direction

    @property
    def offset(self) -> int:
        """Zero-based item offset for SKIP in Cypher."""
        return self.page * self.size

    def next(self) -> Pageable:
        """Return a Pageable for the next page."""
        return Pageable(self.page + 1, self.size, self.sort_by, self.direction)

    def previous(self) -> Pageable:
        """Return a Pageable for the previous page (clamped to 0)."""
        return Pageable(max(0, self.page - 1), self.size, self.sort_by, self.direction)

    def first(self) -> Pageable:
        """Return a Pageable for the first page."""
        return Pageable(0, self.size, self.sort_by, self.direction)

    def __repr__(self) -> str:
        return (
            f"Pageable(page={self.page}, size={self.size}, "
            f"sort_by={self.sort_by!r}, direction={self.direction!r})"
        )


class Page[T]:
    """A single page of results from a paginated query.

    Example::

        for entity in page:
            print(entity.name)
        print(f"Page {page.page_number} of {page.total_pages}")
    """

    def __init__(
        self,
        items: list[T],
        page_number: int,
        size: int,
        total_elements: int,
    ) -> None:
        self._items = items
        self.page_number = page_number
        self.size = size
        self.total_elements = total_elements

    @property
    def total_pages(self) -> int:
        """Total number of pages given ``total_elements`` and ``size``."""
        if self.size <= 0:
            return 0
        return math.ceil(self.total_elements / self.size)

    def has_next(self) -> bool:
        """True if there is at least one more page after this one."""
        return self.page_number < self.total_pages - 1

    def has_previous(self) -> bool:
        """True if this is not the first page."""
        return self.page_number > 0

    def __iter__(self) -> Iterator[T]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return (
            f"Page(page={self.page_number}, size={self.size}, "
            f"total_elements={self.total_elements}, items={len(self._items)})"
        )
