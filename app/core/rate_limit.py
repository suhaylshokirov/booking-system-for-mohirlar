"""Login attempt limiting: slow down password guessing.

The limiter counts *failed* logins in a sliding window, per key (the service
uses client IP + email). Once a key has `max_attempts` failures inside the last
`window_seconds`, `retry_after` says how long until the oldest of them slips out
of the window and one more attempt is allowed.

Why the key has both parts: limiting by email alone would let anyone lock a
victim out by failing against their address from anywhere; limiting by IP alone
would let one attacker try every account. Per pair, an attacker can only lock
themselves out of one account.

`LoginAttemptLimiter` is the small interface the service depends on;
`InMemoryLoginLimiter` is the only implementation. Limitations, on purpose:
state lives in one process's memory, so it resets on restart and is not shared
between several app instances (a Redis-backed implementation would drop in
behind the same three methods). Behind a reverse proxy the IP must be the real
client's (uvicorn `--proxy-headers`), or every visitor shares one IP.

No method reads the clock: the caller passes `now` (see `app/core/clock.py`).
"""

import math
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Protocol

Key = tuple[str, str]

# When the store holds more keys than this, expired ones are swept out on the
# next write, so a flood of one-off (ip, email) pairs cannot grow memory forever.
_SWEEP_ABOVE_KEYS = 10_000


class LoginAttemptLimiter(Protocol):
    def retry_after(self, key: Key, now: datetime) -> int | None:
        """Whole seconds until another attempt is allowed, or None if it is now."""
        ...

    def record_failure(self, key: Key, now: datetime) -> None: ...

    def reset(self, key: Key) -> None:
        """Forget the key's failures (called after a successful login)."""
        ...


class InMemoryLoginLimiter:
    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max_attempts = max_attempts
        self._window = timedelta(seconds=window_seconds)
        # Failure times per key, oldest first. Request handlers run in a thread
        # pool, so every access takes the lock.
        self._failures: defaultdict[Key, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _live_failures(self, key: Key, now: datetime) -> deque[datetime]:
        """The key's failures still inside the window (older ones are dropped)."""
        failures = self._failures[key]
        while failures and failures[0] <= now - self._window:
            failures.popleft()
        return failures

    def retry_after(self, key: Key, now: datetime) -> int | None:
        with self._lock:
            if key not in self._failures:
                return None
            failures = self._live_failures(key, now)
            if len(failures) < self._max_attempts:
                if not failures:
                    del self._failures[key]
                return None
            # Blocked until enough of the oldest failures expire to get back
            # under the limit. Rounded up so a client that waits exactly this
            # long is never told to wait again.
            unblocked_at = failures[len(failures) - self._max_attempts] + self._window
            return max(1, math.ceil((unblocked_at - now).total_seconds()))

    def record_failure(self, key: Key, now: datetime) -> None:
        with self._lock:
            if len(self._failures) > _SWEEP_ABOVE_KEYS:
                self._sweep(now)
            self._live_failures(key, now).append(now)

    def reset(self, key: Key) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def _sweep(self, now: datetime) -> None:
        for key in list(self._failures):
            if not self._live_failures(key, now):
                del self._failures[key]
