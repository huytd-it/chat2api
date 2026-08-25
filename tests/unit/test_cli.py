import yaml
import pytest

from chat2api.__main__ import add_storage_state, resolve_recipe_path, set_login_policy


def test_resolve_ok(tmp_path):
    d = tmp_path / "copilot"
    d.mkdir()
    assert resolve_recipe_path(tmp_path, "copilot") == d


@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", ".", "", "C:"])
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


def test_add_storage_state_first_named_account_migrates_scalar(tmp_path):
    rp = tmp_path / "copilot" / "recipe.yaml"
    rp.parent.mkdir()
    rp.write_text("slug: copilot\nurl: https://x\nlogin:\n  storage_state: auth/state.json\n",
                  encoding="utf-8")
    add_storage_state(rp, "acc2", "auth/acc2/state.json")
    data = yaml.safe_load(rp.read_text(encoding="utf-8"))
    accounts = data["login"]["accounts"]
    assert {"name": "default", "storage_state": "auth/state.json"} in accounts
    assert {"name": "acc2", "storage_state": "auth/acc2/state.json"} in accounts
    assert "storage_state" not in data["login"]


def test_add_storage_state_named_account_reruns_idempotently(tmp_path):
    rp = tmp_path / "copilot" / "recipe.yaml"
    rp.parent.mkdir()
    rp.write_text("slug: copilot\nurl: https://x\n", encoding="utf-8")
    add_storage_state(rp, "acc1", "auth/acc1/state.json")
    add_storage_state(rp, "acc1", "auth/acc1/state.json")
    data = yaml.safe_load(rp.read_text(encoding="utf-8"))
    assert data["login"]["accounts"] == [{"name": "acc1", "storage_state": "auth/acc1/state.json"}]


def test_set_login_policy(tmp_path):
    rp = tmp_path / "recipe.yaml"
    rp.write_text("slug: copilot\nurl: https://x\n", encoding="utf-8")
    set_login_policy(rp, "fill_first", 20)
    data = yaml.safe_load(rp.read_text(encoding="utf-8"))
    assert data["login"] == {"strategy": "fill_first", "quota": 20}


def test_set_login_policy_noop_when_unset(tmp_path):
    rp = tmp_path / "recipe.yaml"
    rp.write_text("slug: copilot\nurl: https://x\n", encoding="utf-8")
    set_login_policy(rp, None, None)
    assert yaml.safe_load(rp.read_text(encoding="utf-8")).get("login") is None
