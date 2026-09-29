"""The login attempt limiter, with time under the test's control (P2.5)."""

import threading
from datetime import UTC, datetime, timedelta

from app.core.rate_limit import InMemoryLoginLimiter

T0 = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
KEY = ("203.0.113.5", "aziza@example.com")


def _limiter(attempts=3, window=300) -> InMemoryLoginLimiter:
    return InMemoryLoginLimiter(max_attempts=attempts, window_seconds=window)


def _fail(limiter, times, key=KEY):
    for moment in times:
        limiter.record_failure(key, moment)


def test_a_fresh_key_is_not_limited():
    assert _limiter().retry_after(KEY, T0) is None


def test_failures_below_the_limit_do_not_block():
    limiter = _limiter(attempts=3)
    _fail(limiter, [T0, T0])
    assert limiter.retry_after(KEY, T0) is None


def test_reaching_the_limit_blocks_and_says_how_long():
    limiter = _limiter(attempts=3, window=300)
    _fail(limiter, [T0, T0 + timedelta(seconds=10), T0 + timedelta(seconds=20)])

    # The first failure leaves the window at T0+300, so at T0+30 that is 270 s away.
    assert limiter.retry_after(KEY, T0 + timedelta(seconds=30)) == 270


def test_access_returns_exactly_when_the_oldest_failure_leaves_the_window():
    limiter = _limiter(attempts=3, window=300)
    _fail(limiter, [T0, T0 + timedelta(seconds=10), T0 + timedelta(seconds=20)])

    assert limiter.retry_after(KEY, T0 + timedelta(seconds=299)) == 1
    assert limiter.retry_after(KEY, T0 + timedelta(seconds=300)) is None


def test_the_window_slides_rather_than_resetting_all_at_once():
    limiter = _limiter(attempts=3, window=300)
    _fail(limiter, [T0, T0 + timedelta(seconds=100), T0 + timedelta(seconds=200)])
    assert limiter.retry_after(KEY, T0 + timedelta(seconds=250)) == 50

    # The first failure expired, one slot is free; using it blocks again until
    # the *second* failure expires, not until everything has.
    now = T0 + timedelta(seconds=300)
    assert limiter.retry_after(KEY, now) is None
    limiter.record_failure(KEY, now)
    assert limiter.retry_after(KEY, now) == 100


def test_retry_after_is_at_least_one_second():
    limiter = _limiter(attempts=1, window=300)
    limiter.record_failure(KEY, T0)
    assert limiter.retry_after(KEY, T0 + timedelta(seconds=299, milliseconds=900)) == 1


def test_reset_forgets_the_failures():
    limiter = _limiter(attempts=2)
    _fail(limiter, [T0, T0])
    assert limiter.retry_after(KEY, T0) is not None

    limiter.reset(KEY)

    assert limiter.retry_after(KEY, T0) is None
    limiter.reset(KEY)  # resetting an unknown key is harmless


def test_keys_are_independent():
    limiter = _limiter(attempts=2)
    _fail(limiter, [T0, T0])

    assert limiter.retry_after(KEY, T0) is not None
    assert limiter.retry_after(("198.51.100.9", KEY[1]), T0) is None  # another IP
    assert limiter.retry_after((KEY[0], "other@example.com"), T0) is None  # another email


def test_checking_does_not_count_as_a_failure():
    limiter = _limiter(attempts=2)
    for _ in range(10):
        limiter.retry_after(KEY, T0)
    _fail(limiter, [T0])
    assert limiter.retry_after(KEY, T0) is None


def test_expired_keys_are_swept_when_the_store_grows(monkeypatch):
    monkeypatch.setattr("app.core.rate_limit._SWEEP_ABOVE_KEYS", 5)
    limiter = _limiter(window=300)
    for n in range(10):
        limiter.record_failure(("ip", f"user{n}@example.com"), T0)

    limiter.record_failure(("ip", "late@example.com"), T0 + timedelta(seconds=301))

    assert len(limiter._failures) == 1  # only the fresh key survived


def test_concurrent_failures_are_all_counted():
    limiter = _limiter(attempts=1000, window=300)

    def hammer():
        for _ in range(100):
            limiter.record_failure(KEY, T0)

    threads = [threading.Thread(target=hammer) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(limiter._failures[KEY]) == 1000
