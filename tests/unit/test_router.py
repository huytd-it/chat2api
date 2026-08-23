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


def test_unhealthy_after_three_failures(tmp_path):
    r = Router(recipes_dir=tmp_path)
    for _ in range(3):
        r.mark_failure("fake")
    assert r.is_unhealthy("fake") is True
    r.mark_success("fake")
    assert r.is_unhealthy("fake") is False
