import asyncio

from chat2api.providers.base import ModelInfo, Provider
from chat2api.router import ModelNotFound, Router


class FakeProvider(Provider):
    slug = "fake"

    def models(self):
        return [ModelInfo(id="fake/m1", slug="fake")]

    async def stream(self, messages, model_id):
        yield "ok"


def test_resolve(tmp_path):
    r = Router(recipes_dir=tmp_path)
    p = FakeProvider()
    r.providers["fake"] = p
    provider, local = r.resolve("fake/m1")
    assert provider is p and local == "m1"


def test_resolve_not_found(tmp_path):
    r = Router(recipes_dir=tmp_path)
    try:
        r.resolve("nope/x")
        assert False
    except ModelNotFound:
        pass


def test_reload_uses_loaders(tmp_path):
    from chat2api import router as router_mod

    def loader(directory, pool):
        if directory.name == "mine":
            return FakeProvider()
        return None

    router_mod.LOADERS.append(loader)
    try:
        (tmp_path / "mine").mkdir()
        (tmp_path / "other").mkdir()
        r = Router(recipes_dir=tmp_path)
        r.reload()
        assert "fake" in r.providers
    finally:
        router_mod.LOADERS.remove(loader)


def test_reload_publishes_provider_registry_atomically(tmp_path):
    from chat2api import router as router_mod

    r = Router(recipes_dir=tmp_path)
    old = FakeProvider()
    r.providers["old"] = old
    observed = []

    def loader(directory, pool):
        observed.append(dict(r.providers))
        return FakeProvider()

    router_mod.LOADERS.append(loader)
    try:
        (tmp_path / "mine").mkdir()
        r.reload()
    finally:
        router_mod.LOADERS.remove(loader)

    assert observed == [{"old": old}]
    assert "old" not in r.providers
    assert r.providers["fake"].slug == "fake"


async def test_router_slot_allows_parallel_requests_up_to_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("API_MAX_CONCURRENT_REQUESTS", "2")
    r = Router(recipes_dir=tmp_path)
    entered = 0
    peak = 0
    release = asyncio.Event()

    async def request():
        nonlocal entered, peak
        async with r.slot():
            entered += 1
            peak = max(peak, entered)
            await release.wait()
            entered -= 1

    tasks = [asyncio.create_task(request()) for _ in range(3)]
    try:
        for _ in range(20):
            if entered == 2:
                break
            await asyncio.sleep(0)
        assert entered == 2
        assert peak == 2
    finally:
        release.set()
        await asyncio.gather(*tasks)


def test_unhealthy_after_three_failures(tmp_path):
    r = Router(recipes_dir=tmp_path)
    for _ in range(3):
        r.mark_failure("fake")
    assert r.is_unhealthy("fake") is True
    r.mark_success("fake")
    assert r.is_unhealthy("fake") is False
