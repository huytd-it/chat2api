"""Ma trận profile × domain × account của bàn test Sessions.

Điểm mấu chốt: danh sách phải ghép account với recipe Ở SERVER. Desktop từng
tự đoán bằng cách so `account.host` với domain của model đang chọn — nên chỉ
thấy được một domain một lúc, và lệch ngay khi host có tiền tố 'www.'.
"""

from pathlib import Path

import pytest


@pytest.fixture
def targets_app(app_client, tmp_path):
    """app_client + kho SQLite + hai recipe browser khác domain."""
    from chat2api import profiles, store
    from chat2api.providers.browser_recipe import BrowserRecipe

    db = store.connect(tmp_path / "targets.db")
    db.migrate()

    def make_recipe(slug: str, url: str, models: list[str]) -> BrowserRecipe:
        return BrowserRecipe(
            {"slug": slug, "url": url, "models": [{"id": m} for m in models]},
            Path("."), None)

    app = app_client._transport.app
    app.state.router.providers["alpha"] = make_recipe(
        "alpha", "https://alpha.test/chat", ["fast", "deep"])
    app.state.router.providers["beta"] = make_recipe(
        "beta", "https://beta.test/chat", ["one"])
    try:
        yield app_client, db, profiles
    finally:
        store.shutdown()


def add(profiles_mod, tmp_path, profile_name: str, host: str, label: str):
    profile = profiles_mod.ensure_profile(profile_name, tmp_path / "profiles")
    return profile, profiles_mod.add_account(profile.id, host, label)


async def test_list_pairs_every_account_with_the_recipes_of_its_domain(targets_app, tmp_path):
    client, _, profiles_mod = targets_app
    add(profiles_mod, tmp_path, "work", "alpha.test", "acc1")
    add(profiles_mod, tmp_path, "work", "beta.test", "acc2")
    add(profiles_mod, tmp_path, "spare", "alpha.test", "acc3")

    body = (await client.get("/admin/test-targets")).json()
    rows = {(t["profile_name"], t["host"], t["label"]): t for t in body["targets"]}

    assert len(rows) == 3
    # Hai domain khác nhau cùng xuất hiện: đây chính là thứ trước đây không có.
    assert rows[("work", "alpha.test", "acc1")]["models"] == ["alpha/fast", "alpha/deep"]
    assert rows[("work", "beta.test", "acc2")]["models"] == ["beta/one"]
    assert rows[("spare", "alpha.test", "acc3")]["recipes"] == ["alpha"]
    assert all(t["ready"] for t in body["targets"])


async def test_www_prefix_still_matches_the_recipe_domain(targets_app, tmp_path):
    client, _, profiles_mod = targets_app
    add(profiles_mod, tmp_path, "work", "www.alpha.test", "acc1")

    target = (await client.get("/admin/test-targets")).json()["targets"][0]
    assert target["host"] == "www.alpha.test" and target["domain"] == "alpha.test"
    assert target["models"] == ["alpha/fast", "alpha/deep"] and target["ready"] is True


async def test_account_without_recipe_is_listed_but_not_ready(targets_app, tmp_path):
    client, _, profiles_mod = targets_app
    add(profiles_mod, tmp_path, "work", "gamma.test", "acc1")

    target = (await client.get("/admin/test-targets")).json()["targets"][0]
    # Vẫn liệt kê để người dùng thấy vì sao nó không chọn được, thay vì giấu đi.
    assert target["models"] == [] and target["ready"] is False


async def test_disabled_account_is_hidden(targets_app, tmp_path):
    client, db, profiles_mod = targets_app
    _, account = add(profiles_mod, tmp_path, "work", "alpha.test", "acc1")
    conn = db.connection()
    with conn:
        conn.execute("UPDATE account SET disabled = 1 WHERE id = ?", (account["id"],))

    assert (await client.get("/admin/test-targets")).json()["targets"] == []


async def test_list_reports_the_pool_caps_so_ui_can_warn(targets_app, tmp_path):
    client, _, profiles_mod = targets_app
    add(profiles_mod, tmp_path, "work", "alpha.test", "acc1")

    body = (await client.get("/admin/test-targets")).json()
    # Chọn nhiều profile hơn trần thì Chromium sẽ đóng bớt — UI cần con số này
    # để cảnh báo trước, không để tab tự biến mất giữa chừng.
    assert body["max_profiles"] >= 1 and body["max_tabs"] >= 1
    assert body["persisted"] is True


async def test_open_without_model_picks_the_recipe_serving_that_domain(targets_app, tmp_path):
    client, _, profiles_mod = targets_app
    _, account = add(profiles_mod, tmp_path, "work", "beta.test", "acc1")
    opened = []

    class FakePage:
        url = "https://beta.test/chat"

    async def open_target(account_id):
        opened.append(account_id)
        return {"profile_name": "work", "label": "acc1", "host": "beta.test"}, FakePage()

    app = client._transport.app
    app.state.router.providers["beta"].open_target = open_target

    response = await client.post("/admin/test-targets/open",
                                 json={"account_id": account["id"]})
    assert response.status_code == 200
    body = response.json()
    assert opened == [account["id"]]
    assert body["recipe"] == "beta" and body["profile"] == "work"
    assert body["url"] == "https://beta.test/chat"


async def test_open_rejects_an_account_no_recipe_serves(targets_app, tmp_path):
    client, _, profiles_mod = targets_app
    _, account = add(profiles_mod, tmp_path, "work", "gamma.test", "acc1")

    response = await client.post("/admin/test-targets/open",
                                 json={"account_id": account["id"]})
    assert response.status_code == 400
    assert "gamma.test" in response.json()["error"]["message"]
