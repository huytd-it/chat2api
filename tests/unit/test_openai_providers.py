import pytest
import yaml

from chat2api import openai_providers as oap
from chat2api import store
from chat2api.store import importer


@pytest.fixture
def db(tmp_path):
    handle = store.connect(tmp_path / "chat2api.db")
    handle.migrate()
    try:
        yield handle
    finally:
        store.shutdown()


def _payload(slug="up", **over):
    data = {
        "slug": slug,
        "base_url": "https://up.example/v1",
        "api_key": "sk-test",
        "models": [{"id": "m1"}, {"id": "g-img", "capability": "image"}],
        "stream": True,
    }
    data.update(over)
    return data


def test_create_and_get_masks_key(db):
    created = oap.create_provider(_payload())
    assert created["slug"] == "up" and created["has_key"] is True
    assert created["models"] == [
        {"id": "g-img", "capability": "image"},
        {"id": "m1", "capability": "chat"},
    ] or sorted(created["models"], key=lambda m: m["id"]) == [
        {"id": "g-img", "capability": "image"},
        {"id": "m1", "capability": "chat"},
    ]
    cfg = oap.get_config("up")
    assert cfg is not None and cfg["api_key"] == "sk-test"


def test_create_duplicate_slug_raises(db):
    oap.create_provider(_payload("up"))
    with pytest.raises(ValueError, match="đã tồn tại"):
        oap.create_provider(_payload("up"))


def test_create_rejects_bad_slug_and_url(db):
    with pytest.raises(ValueError, match="Slug"):
        oap.create_provider(_payload("OpenAI"))
    with pytest.raises(ValueError, match="base_url"):
        oap.create_provider(_payload("ok", base_url="not-a-url"))
    with pytest.raises(ValueError, match="models"):
        oap.create_provider(_payload("ok", models=[]))


def test_update_keeps_key_on_mask(db):
    oap.create_provider(_payload("up"))
    updated = oap.update_provider("up", {"base_url": "https://up2.example/v1", "api_key": "***"})
    assert updated is not None and updated["base_url"] == "https://up2.example/v1"
    assert oap.get_config("up")["api_key"] == "sk-test"
    oap.update_provider("up", {"api_key": "sk-new"})
    assert oap.get_config("up")["api_key"] == "sk-new"


def test_update_models_replaces(db):
    oap.create_provider(_payload("up"))
    oap.update_provider("up", {"models": [{"id": "m2", "capability": "both"}]})
    assert oap.get_provider("up")["models"] == [{"id": "m2", "capability": "both"}]


def test_delete(db):
    oap.create_provider(_payload("up"))
    assert oap.delete_provider("up") is True
    assert oap.get_provider("up") is None
    assert oap.delete_provider("up") is False


def test_importer_moves_yaml_into_openai_tables_not_recipe(db, tmp_path):
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    odir = recipes / "openai"
    odir.mkdir()
    (odir / "qwen.yaml").write_text(yaml.safe_dump({
        "slug": "qwen", "base_url": "https://qwen.example/v1",
        "api_key": "sk-x", "models": ["qwen-max"],
    }), encoding="utf-8")
    counts = importer.import_all(db, recipes)
    assert counts.get("openai_providers") == 1
    assert counts["recipes"] == 0
    assert db.query("SELECT COUNT(*) AS n FROM recipe WHERE kind = 'openai_passthrough'")[0]["n"] == 0
    row = oap.get_provider("qwen")
    assert row is not None and row["has_key"] is True
    # Idempotent: chạy lại không đè DB bằng file.
    oap.update_provider("qwen", {"base_url": "https://edited.example/v1"})
    importer.import_all(db, recipes)
    assert oap.get_provider("qwen")["base_url"] == "https://edited.example/v1"


def test_router_loads_openai_from_db(db, tmp_path):
    from chat2api.router import Router
    oap.create_provider(_payload("up"))
    r = Router(recipes_dir=tmp_path / "recipes")
    r.reload()
    assert "up" in r.providers
    provider, local = r.resolve("up/m1")
    assert local == "m1"
    assert {m.id for m in provider.models()} == {"up/m1", "up/g-img"}
