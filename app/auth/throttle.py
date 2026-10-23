"""Slow down password guessing: too many failed sign-ins lock that username and address for a while.

State is kept in memory, so it resets when the server restarts and the app must run as a single process.
"""

import threading
import time
from collections import defaultdict, deque

MAX_FAILURES = 5
WINDOW_SECONDS = 10 * 60
LOCKOUT_SECONDS = 10 * 60


class LoginThrottle:
    """Counts failed sign-ins per key (for example the username and the client address)."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def seconds_locked(self, *keys: str) -> int:
        """Seconds left until the first locked key is allowed again (0 when none is locked)."""
        now = self._clock()
        with self._lock:
            left = max((self._locked_until.get(k, 0.0) - now for k in keys), default=0.0)
        return max(0, int(left) + (1 if left > 0 else 0))

    def record_failure(self, *keys: str) -> None:
        """Count a failed sign-in; the fifth within the window locks the key."""
        now = self._clock()
        with self._lock:
            for key in keys:
                recent = self._failures[key]
                recent.append(now)
                while recent and now - recent[0] > WINDOW_SECONDS:
                    recent.popleft()
                if len(recent) >= MAX_FAILURES:
                    self._locked_until[key] = now + LOCKOUT_SECONDS
                    recent.clear()

    def reset(self, *keys: str) -> None:
        """A successful sign-in clears the counters."""
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
                self._locked_until.pop(key, None)


throttle = LoginThrottle()
