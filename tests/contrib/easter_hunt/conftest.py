import pytest


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real retry sleeps so respx-backed hunt() tests stay fast.

    Mirrors the fixture in tests/test_client.py; needed because hunt() drives
    the real fetch() chain in its integration test, which retries on 5xx.
    """
    monkeypatch.setattr("polyfetch_scrape._backends.httpx_backend.time.sleep", lambda _s: None)
