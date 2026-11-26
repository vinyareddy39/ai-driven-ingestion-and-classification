"""Token bucket rate limiter to guarantee bulk reprocessing never starves live ingestion."""

import time
import threading


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter."""

    def __init__(self, rate_per_second: float = 50.0, burst: float = 100.0):
        self.rate = rate_per_second
        self.burst = burst
        self.tokens = burst
        self.last_update = time.time()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> bool:
        """Attempt to acquire tokens without blocking."""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_and_acquire(self, tokens: float = 1.0) -> None:
        """Block until tokens become available."""
        while not self.acquire(tokens):
            time.sleep(1.0 / max(1.0, self.rate))
