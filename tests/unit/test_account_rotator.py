import pytest

from chat2api.providers.browser_recipe import _AccountRotator


def _accounts(*names):
    return [(n, None) for n in names]


async def test_single_account_always_returned():
    r = _AccountRotator(_accounts("only"), "round_robin", 50)
    for _ in range(3):
        assert (await r.next())[0] == "only"


async def test_round_robin_cycles_in_order():
    r = _AccountRotator(_accounts("a", "b", "c"), "round_robin", 50)
    picked = [(await r.next())[0] for _ in range(7)]
    assert picked == ["a", "b", "c", "a", "b", "c", "a"]


async def test_fill_first_exhausts_quota_before_switching():
    r = _AccountRotator(_accounts("a", "b"), "fill_first", 2)
    picked = [(await r.next())[0] for _ in range(5)]
    assert picked == ["a", "a", "b", "b", "a"]


async def test_fill_first_quota_one_behaves_like_round_robin():
    r = _AccountRotator(_accounts("a", "b", "c"), "fill_first", 1)
    picked = [(await r.next())[0] for _ in range(4)]
    assert picked == ["a", "b", "c", "a"]


async def test_concurrent_calls_stay_consistent_with_quota():
    import asyncio

    r = _AccountRotator(_accounts("a", "b"), "fill_first", 10)
    results = await asyncio.gather(*(r.next() for _ in range(20)))
    names = [name for name, _ in results]
    assert names.count("a") == 10
    assert names.count("b") == 10
