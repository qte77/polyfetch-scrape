"""Live canary for easter_hunt. Opt-in via `pytest -m e2e` / `make test_e2e`.

Hits the real network: regression guard that the wakatime turtle still registers
as a novelty finding through the full fetch -> detector pipeline.
"""

import pytest

from polyfetch_scrape.contrib.easter_hunt import hunt


@pytest.mark.e2e
def test_wakatime_turtle_registers_as_novelty_live() -> None:
    findings = hunt(["https://wakatime.com/"])
    assert any(f.category == "novelty" for f in findings), (
        "expected at least one novelty finding from wakatime.com"
    )
