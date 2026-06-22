"""Concurrency, rate-limiting, budgeting, and caching primitives.

All primitives are thread-safe and have no external dependencies. They back
the ingestion pipeline's parallel extraction/embedding while enforcing the
cost and rate controls from :mod:`runic.rag.config`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, wraps
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar

from runic.rag.exceptions import BudgetExceededError

log = logging.getLogger(__name__)

__all__ = [
    "BudgetGuard",
    "ContentCache",
    "RateLimiter",
    "estimate_tokens",
    "parallel_map",
]

F = TypeVar("F", bound=Callable[..., Any])

# Tuple referenced (not inlined) in except clauses: the ruff formatter in this
# pinned version strips parens from inline multi-exception tuples, producing
# invalid syntax, so we bind the tuple to names instead.
_CACHE_READ_ERRORS = (OSError, json.JSONDecodeError)
_CACHE_WRITE_ERRORS = (OSError, TypeError)


@lru_cache(maxsize=1)
def _token_encoder() -> Any:
    """Return a cached tiktoken encoder, or ``None`` if tiktoken is unavailable."""
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:  # noqa: BLE001 - any tiktoken failure → heuristic fallback
        log.debug("tiktoken unavailable; estimate_tokens uses a char heuristic")
        return None


def estimate_tokens(text: str) -> int:
    """Estimate the token count of *text* for budgeting.

    Uses tiktoken (``cl100k_base``) when available for an accurate count, else a
    ~4-chars-per-token heuristic. This is an *estimate* feeding the cost
    :class:`BudgetGuard` (``max_tokens``), not a provider's exact billed usage.
    """
    if not text:
        return 0
    encoder = _token_encoder()
    if encoder is not None:
        return len(encoder.encode(text))
    return max(1, len(text) // 4)


def parallel_map[T, R](
    fn: Callable[[T], R], items: Iterable[T], *, max_workers: int
) -> list[R]:
    """Apply *fn* to each item concurrently, preserving input order.

    With ``max_workers <= 1`` the work runs sequentially in the calling thread.
    Exceptions raised inside *fn* propagate to the caller.
    """
    materialized = list(items)
    if not materialized:
        return []
    if max_workers <= 1:
        return [fn(item) for item in materialized]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(fn, materialized))


class RateLimiter:
    """Thread-safe token-bucket limiter measured in requests per minute.

    ``requests_per_minute <= 0`` disables limiting. Usable as a callable, a
    context manager, or a decorator; each acquisition consumes one token,
    blocking until one is available.
    """

    def __init__(self, requests_per_minute: int) -> None:
        self._rpm = requests_per_minute
        self._lock = threading.Lock()
        self._interval = 0.0 if requests_per_minute <= 0 else 60.0 / requests_per_minute
        # Allow the very first request to proceed immediately.
        self._next_available = 0.0

    @property
    def unlimited(self) -> bool:
        """True when no rate limit is enforced."""
        return self._rpm <= 0

    def acquire(self) -> None:
        """Block until a token is available, then consume it."""
        if self.unlimited:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                if now >= self._next_available:
                    start = max(now, self._next_available)
                    self._next_available = start + self._interval
                    return
                wait = self._next_available - now
            time.sleep(wait)

    def __call__(self, fn: F | None = None) -> Any:
        """Acquire a token (no arg) or wrap *fn* as a rate-limited decorator."""
        if fn is None:
            self.acquire()
            return None

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.acquire()
            return fn(*args, **kwargs)

        return wrapper

    def __enter__(self) -> RateLimiter:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


class BudgetGuard:
    """Thread-safe counter of LLM calls and tokens against hard limits.

    ``max_llm_calls`` / ``max_tokens`` of ``0`` mean unlimited. Recording usage
    past a limit raises :class:`BudgetExceededError`.
    """

    def __init__(self, *, max_llm_calls: int = 0, max_tokens: int = 0) -> None:
        self._max_calls = max_llm_calls
        self._max_tokens = max_tokens
        self._calls = 0
        self._tokens = 0
        self._lock = threading.Lock()

    @property
    def llm_calls(self) -> int:
        """Number of LLM calls recorded so far."""
        with self._lock:
            return self._calls

    @property
    def tokens(self) -> int:
        """Number of tokens recorded so far."""
        with self._lock:
            return self._tokens

    def check(self) -> None:
        """Raise :class:`BudgetExceededError` if a budget is already exhausted.

        Mutation-free pre-flight: call *before* an LLM/embedding request so an
        already-spent budget fails before the network call. Pair with
        :meth:`record` *after* the call succeeds so failed calls cost nothing.
        """
        with self._lock:
            if self._max_calls and self._calls >= self._max_calls:
                raise BudgetExceededError(
                    f"LLM call budget exhausted: {self._calls}/{self._max_calls}"
                )
            if self._max_tokens and self._tokens >= self._max_tokens:
                raise BudgetExceededError(
                    f"Token budget exhausted: {self._tokens}/{self._max_tokens}"
                )

    def record(self, *, llm_calls: int = 0, tokens: int = 0) -> None:
        """Record usage; raise :class:`BudgetExceededError` past any limit."""
        with self._lock:
            new_calls = self._calls + llm_calls
            new_tokens = self._tokens + tokens
            if self._max_calls and new_calls > self._max_calls:
                raise BudgetExceededError(
                    f"LLM call budget exceeded: {new_calls} > {self._max_calls}"
                )
            if self._max_tokens and new_tokens > self._max_tokens:
                raise BudgetExceededError(
                    f"Token budget exceeded: {new_tokens} > {self._max_tokens}"
                )
            self._calls = new_calls
            self._tokens = new_tokens


class ContentCache:
    """Content-addressed cache keyed by the sha256 of arbitrary content.

    Each entry is stored as one JSON file under ``cache_dir`` named by its key.
    If ``cache_dir`` is ``None`` the cache is a thread-safe no-op (every
    :meth:`get` misses). Stored values must be JSON-serializable.
    """

    def __init__(self, cache_dir: str | Path | None) -> None:
        self._dir: Path | None = Path(cache_dir) if cache_dir is not None else None
        self._lock = threading.Lock()
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def enabled(self) -> bool:
        """True when a backing directory is configured."""
        return self._dir is not None

    @staticmethod
    def key_for(content: str) -> str:
        """Return the sha256 hex digest used as the cache key for *content*."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def get(self, content: str) -> Any | None:
        """Return the cached value for *content*, or None on a miss."""
        if self._dir is None:
            return None
        path = self._path_for(content)
        with self._lock:
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except _CACHE_READ_ERRORS:
                log.warning("Failed to read cache entry: %s", path)
                return None

    def set(self, content: str, value: Any) -> None:
        """Cache *value* under the key derived from *content* (no-op if off)."""
        if self._dir is None:
            return
        path = self._path_for(content)
        with self._lock:
            try:
                # Write to a sibling temp file then atomically replace, so a
                # crash or a second writer never leaves a truncated entry.
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(value), encoding="utf-8")
                tmp.replace(path)
            except _CACHE_WRITE_ERRORS:
                log.warning("Failed to write cache entry: %s", path)

    def _path_for(self, content: str) -> Path:
        assert self._dir is not None  # noqa: S101 - guarded by callers
        return self._dir / f"{self.key_for(content)}.json"
