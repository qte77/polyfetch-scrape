import threading
import time
from urllib.parse import urlsplit


class Throttle:
    """Per-host minimum inter-request spacing — proactive politeness.

    Thread-safe and per-process: share ONE instance across callers (e.g. a bulk
    worker pool) so requests to the same host are spaced by at least
    ``min_interval`` seconds, while different hosts never block each other.
    ``min_interval <= 0`` disables spacing (a no-op).
    """

    def __init__(self, min_interval: float) -> None:
        if min_interval < 0:
            raise ValueError("min_interval must be >= 0")
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}

    def acquire(self, url: str) -> None:
        """Block until this host's next slot is free, spacing same-host requests.

        Reserve the slot under the lock, then sleep outside it so concurrent
        callers to *different* hosts are not serialized behind one another.
        """
        if self.min_interval <= 0:
            return
        host = urlsplit(url).hostname or url
        with self._lock:
            now = time.monotonic()
            next_free = max(now, self._next_allowed.get(host, 0.0))
            self._next_allowed[host] = next_free + self.min_interval
        wait = next_free - now
        if wait > 0.0:
            time.sleep(wait)
