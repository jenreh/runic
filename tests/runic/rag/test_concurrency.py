"""Unit tests for concurrency primitives (no network)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from runic.rag.concurrency import (
    BudgetGuard,
    ContentCache,
    RateLimiter,
    estimate_tokens,
    parallel_map,
)
from runic.rag.exceptions import BudgetExceededError

# ── parallel_map ────────────────────────────────────────────────────────────


def test_parallel_map_preserves_order() -> None:
    result = parallel_map(lambda x: x * 2, [1, 2, 3, 4], max_workers=4)
    assert result == [2, 4, 6, 8]


def test_parallel_map_empty() -> None:
    assert parallel_map(lambda x: x, [], max_workers=4) == []


def test_parallel_map_sequential_when_single_worker() -> None:
    result = parallel_map(lambda x: x + 1, [10, 20], max_workers=1)
    assert result == [11, 21]


def test_parallel_map_propagates_exception() -> None:
    def boom(x: int) -> int:
        if x == 2:
            raise ValueError("boom")
        return x

    with pytest.raises(ValueError, match="boom"):
        parallel_map(boom, [1, 2, 3], max_workers=2)


def test_parallel_map_runs_concurrently() -> None:
    # Compare a measured serial baseline against the parallel run rather than a
    # fixed wall-clock bound, so the test proves concurrency without flaking on
    # a loaded or cold thread pool.
    def slow(x: int) -> int:
        time.sleep(0.05)
        return x

    serial_start = time.monotonic()
    parallel_map(slow, [1, 2, 3, 4], max_workers=1)
    serial = time.monotonic() - serial_start

    par_start = time.monotonic()
    result = parallel_map(slow, [1, 2, 3, 4], max_workers=4)
    parallel = time.monotonic() - par_start

    assert result == [1, 2, 3, 4]
    # Four-way parallelism should beat serial clearly even with pool overhead.
    assert parallel < serial * 0.8


# ── RateLimiter ─────────────────────────────────────────────────────────────


def test_rate_limiter_unlimited_when_zero() -> None:
    limiter = RateLimiter(0)
    assert limiter.unlimited is True
    start = time.monotonic()
    for _ in range(100):
        limiter.acquire()
    assert time.monotonic() - start < 0.1


def test_rate_limiter_enforces_spacing() -> None:
    # 120 rpm → one token every 0.5s. Three acquisitions ≈ 1.0s minimum.
    limiter = RateLimiter(120)
    start = time.monotonic()
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.9


def test_rate_limiter_context_manager() -> None:
    limiter = RateLimiter(0)
    with limiter as acquired:
        assert acquired is limiter


def test_rate_limiter_decorator() -> None:
    limiter = RateLimiter(0)
    calls: list[int] = []

    @limiter
    def fn(x: int) -> int:
        calls.append(x)
        return x * 2

    assert fn(3) == 6
    assert calls == [3]


def test_rate_limiter_callable_no_arg_acquires() -> None:
    limiter = RateLimiter(0)
    assert limiter() is None


def test_rate_limiter_thread_safe() -> None:
    limiter = RateLimiter(600)  # 0.1s spacing
    errors: list[Exception] = []

    def worker() -> None:
        try:
            limiter.acquire()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


# ── BudgetGuard ─────────────────────────────────────────────────────────────


def test_budget_guard_unlimited_by_default() -> None:
    guard = BudgetGuard()
    for _ in range(1000):
        guard.record(llm_calls=1, tokens=1000)
    assert guard.llm_calls == 1000
    assert guard.tokens == 1_000_000


def test_budget_guard_call_limit() -> None:
    guard = BudgetGuard(max_llm_calls=2)
    guard.record(llm_calls=1)
    guard.record(llm_calls=1)
    with pytest.raises(BudgetExceededError, match="call budget"):
        guard.record(llm_calls=1)


def test_budget_guard_token_limit() -> None:
    guard = BudgetGuard(max_tokens=100)
    guard.record(tokens=100)
    with pytest.raises(BudgetExceededError, match="Token budget"):
        guard.record(tokens=1)


def test_budget_guard_rejected_usage_not_counted() -> None:
    guard = BudgetGuard(max_llm_calls=1)
    guard.record(llm_calls=1)
    with pytest.raises(BudgetExceededError):
        guard.record(llm_calls=5)
    # Failed record must not mutate the counter.
    assert guard.llm_calls == 1


def test_budget_guard_thread_safe_counting() -> None:
    guard = BudgetGuard()

    def worker() -> None:
        for _ in range(100):
            guard.record(llm_calls=1, tokens=2)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert guard.llm_calls == 1000
    assert guard.tokens == 2000


def test_budget_guard_check_passes_under_limit() -> None:
    guard = BudgetGuard(max_llm_calls=2, max_tokens=100)
    guard.record(llm_calls=1, tokens=50)
    guard.check()  # 1/2 calls, 50/100 tokens → still room
    assert guard.llm_calls == 1  # check() must not mutate
    assert guard.tokens == 50


def test_budget_guard_check_raises_when_calls_exhausted() -> None:
    guard = BudgetGuard(max_llm_calls=1)
    guard.record(llm_calls=1)
    with pytest.raises(BudgetExceededError, match="call budget exhausted"):
        guard.check()


def test_budget_guard_check_raises_when_tokens_exhausted() -> None:
    guard = BudgetGuard(max_tokens=10)
    guard.record(tokens=10)
    with pytest.raises(BudgetExceededError, match="Token budget exhausted"):
        guard.check()


# ── estimate_tokens ──────────────────────────────────────────────────────────


def test_estimate_tokens_empty_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_positive_and_scales_with_length() -> None:
    short = estimate_tokens("hello world")
    longer = estimate_tokens("hello world " * 50)
    assert short > 0
    assert longer > short


# ── ContentCache ────────────────────────────────────────────────────────────


def test_content_cache_key_is_sha256_stable() -> None:
    assert ContentCache.key_for("abc") == ContentCache.key_for("abc")
    assert ContentCache.key_for("abc") != ContentCache.key_for("abd")
    assert len(ContentCache.key_for("abc")) == 64


def test_content_cache_get_set_roundtrip(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    assert cache.enabled is True
    assert cache.get("hello") is None
    cache.set("hello", {"entities": [1, 2, 3]})
    assert cache.get("hello") == {"entities": [1, 2, 3]}


def test_content_cache_distinct_keys(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2


def test_content_cache_noop_when_dir_none() -> None:
    cache = ContentCache(None)
    assert cache.enabled is False
    cache.set("x", 123)
    assert cache.get("x") is None
