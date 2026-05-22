import random

from polyfetch_scrape.utils.http_ua import (
    STABLE_USER_AGENT,
    USER_AGENTS,
    pick_user_agent,
)


def test_user_agents_pool_is_nonempty_tuple() -> None:
    assert isinstance(USER_AGENTS, tuple)
    assert len(USER_AGENTS) >= 3
    assert all(isinstance(ua, str) and ua for ua in USER_AGENTS)


def test_stable_user_agent_is_first_in_pool() -> None:
    assert USER_AGENTS[0] == STABLE_USER_AGENT


def test_pick_user_agent_returns_member_of_pool() -> None:
    for _ in range(20):
        assert pick_user_agent() in USER_AGENTS


def test_pick_user_agent_with_seeded_rng_is_deterministic() -> None:
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    picks_a = [pick_user_agent(rng_a) for _ in range(5)]
    picks_b = [pick_user_agent(rng_b) for _ in range(5)]
    assert picks_a == picks_b


def test_user_agents_look_like_modern_desktop_browsers() -> None:
    for ua in USER_AGENTS:
        assert ua.startswith("Mozilla/5.0")
