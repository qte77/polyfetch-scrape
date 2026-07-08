import threading

import pytest

from polyfetch_scrape.throttle import Throttle


class _FakeClock:
    """Deterministic monotonic + sleep: sleeping advances the clock and is recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []
        monkeypatch.setattr("polyfetch_scrape.throttle.time.monotonic", lambda: self.now)

        def _sleep(duration: float) -> None:
            self.sleeps.append(duration)
            self.now += duration

        monkeypatch.setattr("polyfetch_scrape.throttle.time.sleep", _sleep)


def test_same_host_spaces_the_second_request(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock(monkeypatch)
    throttle = Throttle(min_interval=0.5)

    throttle.acquire("https://a.test/1")  # first call to the host — no wait
    throttle.acquire("https://a.test/2")  # second — must wait one interval

    assert clock.sleeps == [0.5]


def test_different_hosts_do_not_block_each_other(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock(monkeypatch)
    throttle = Throttle(min_interval=0.5)

    throttle.acquire("https://a.test/")
    throttle.acquire("https://b.test/")  # different host — its own first request, no wait

    assert clock.sleeps == []


def test_zero_interval_never_sleeps(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock(monkeypatch)
    throttle = Throttle(min_interval=0.0)

    throttle.acquire("https://a.test/1")
    throttle.acquire("https://a.test/2")

    assert clock.sleeps == []


def test_negative_interval_raises() -> None:
    with pytest.raises(ValueError, match="min_interval"):
        Throttle(min_interval=-1.0)


def test_concurrent_same_host_reserves_distinct_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real monotonic, but sleep is a no-op recorder: the lock must still hand each of the N
    # racing callers a distinct, increasing slot (1x, 2x, ... the interval) - never double-book.
    interval = 0.05
    n = 5
    recorded: list[float] = []
    rec_lock = threading.Lock()

    def _record_sleep(duration: float) -> None:
        with rec_lock:
            recorded.append(duration)

    monkeypatch.setattr("polyfetch_scrape.throttle.time.sleep", _record_sleep)

    throttle = Throttle(min_interval=interval)
    start = threading.Barrier(n)

    def worker() -> None:
        start.wait()  # maximize the race
        throttle.acquire("https://a.test/")

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    waits = [w for w in recorded if w > 0.0]
    # One caller went first (wait 0, not recorded); the rest queued into distinct slots.
    slots = sorted(round(w / interval) for w in waits)
    assert slots == list(range(1, n))
