import pytest

from chat2api.__main__ import add_storage_state, resolve_recipe_path


def test_resolve_ok(tmp_path):
    d = tmp_path / "copilot"
    d.mkdir()
    assert resolve_recipe_path(tmp_path, "copilot") == d


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", ".", ""])
def test_resolve_rejects_traversal(tmp_path, bad):
    with pytest.raises(ValueError):
        resolve_recipe_path(tmp_path, bad)


def test_add_storage_state(tmp_path):
    rp = tmp_path / "copilot"
    rp.mkdir()
    (rp / "recipe.yaml").write_text("slug: copilot\nurl: https://x\n", encoding="utf-8")
    add_storage_state(rp / "recipe.yaml")
    text = (rp / "recipe.yaml").read_text(encoding="utf-8")
    assert "storage_state" in text and "auth/state.json" in text
