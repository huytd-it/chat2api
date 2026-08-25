import json

import pytest
import yaml

from chat2api import store
from chat2api.store import importer

BROWSER_RECIPE = {
    "url": "https://chat.qwen.ai/",
    "slug": "chat",
    "prompt": {"input_selector": "textarea"},
    "response": {"last_message_selector": ".msg", "done_signal": {"type": "stable_text"}},
    "models": [{"id": "qwen-web"}],
    "login": {"strategy": "fill_first", "quota": 7, "anon_trial_limit": 5},
    "keep_context": False,
}


def write_recipe(recipes_dir, slug, data):
    d = recipes_dir / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "recipe.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                                   encoding="utf-8")
    return d / "recipe.yaml"


def write_account(recipes_dir, domain, name):
    d = recipes_dir / ".accounts" / domain
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.json"
    path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    return path


@pytest.fixture
def db(tmp_path):
    s = store.Store(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def recipes(tmp_path):
    d = tmp_path / "recipes"
    d.mkdir()
    return d


# ------------------------------------------------------------------ quét đĩa


def test_scan_reads_all_three_provider_kinds(recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    (recipes / "gemini").mkdir()
    (recipes / "gemini" / "config.yaml").write_text(
        yaml.safe_dump({"slug": "gemini", "models": [{"id": "gemini-flash", "model_id": 1}]}),
        encoding="utf-8")
    (recipes / "openai").mkdir()
    (recipes / "openai" / "qwen.yaml").write_text(
        yaml.safe_dump({"slug": "qwen", "base_url": "https://qwen.aikit.club/v1",
                        "models": ["qwen-max", "qwen-plus"]}),
        encoding="utf-8")

    found = {r.slug: r for r in importer.scan_recipes(recipes)}
    assert set(found) == {"chat", "gemini", "qwen"}
    assert found["chat"].kind == "browser"
    assert found["chat"].domain == "chat.qwen.ai"
    assert found["chat"].models == ["qwen-web"]
    assert found["gemini"].kind == "gemini_native"
    assert found["qwen"].kind == "openai_passthrough"
    assert found["qwen"].models == ["qwen-max", "qwen-plus"]


def test_scan_reads_login_policy_and_keep_context(recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    item = importer.scan_recipes(recipes)[0]
    assert (item.rotation, item.rotation_quota) == ("fill_first", 7)
    assert item.anon_trial_limit == 5
    assert item.keep_context is False


def test_scan_skips_broken_yaml_instead_of_raising(recipes):
    # Không có khoá `slug` -> lấy theo tên thư mục, giống _recipe_loader của router.
    write_recipe(recipes, "good", {k: v for k, v in BROWSER_RECIPE.items() if k != "slug"})
    (recipes / "bad").mkdir()
    (recipes / "bad" / "recipe.yaml").write_text("url: [chưa đóng ngoặc", encoding="utf-8")
    # Một recipe hỏng cú pháp không được chặn server khởi động — router cũng bỏ qua.
    assert [r.slug for r in importer.scan_recipes(recipes)] == ["good"]


def test_scan_ignores_dot_dirs_and_dirs_without_recipe(recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    (recipes / ".login").mkdir()
    (recipes / "secrets").mkdir()
    assert [r.slug for r in importer.scan_recipes(recipes)] == ["chat"]


def test_scan_accounts_finds_shared_store(recipes):
    write_account(recipes, "chat.qwen.ai", "codex1")
    write_account(recipes, "chat.qwen.ai", "codex2")
    write_account(recipes, "chatgpt.com", "work")
    found = importer.scan_accounts(recipes)
    assert sorted((a.domain, a.label) for a in found) == [
        ("chat.qwen.ai", "codex1"), ("chat.qwen.ai", "codex2"), ("chatgpt.com", "work")]


def test_scan_missing_dir_is_empty(tmp_path):
    assert importer.scan_recipes(tmp_path / "không-có") == []


# ------------------------------------------------------------------- import


def test_import_writes_recipe_model_and_domain(db, recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    counts = importer.import_all(db, recipes)
    assert counts["recipes"] == 1 and counts["models"] == 1 and counts["versions"] == 1

    row = db.query("SELECT * FROM recipe WHERE slug = 'chat'")[0]
    assert (row["kind"], row["url"], row["source"]) == ("browser", "https://chat.qwen.ai/", "import")
    assert (row["rotation"], row["rotation_quota"], row["anon_trial_limit"]) == ("fill_first", 7, 5)
    assert row["keep_context"] == 0
    assert json.loads(row["config"])["slug"] == "chat"
    assert db.query("SELECT host FROM domain WHERE id = ?",
                    (row["domain_id"],))[0]["host"] == "chat.qwen.ai"
    assert db.query("SELECT public_id FROM model")[0]["public_id"] == "chat/qwen-web"


def test_import_is_idempotent(db, recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    write_account(recipes, "chat.qwen.ai", "codex1")
    first = importer.import_all(db, recipes)
    second = importer.import_all(db, recipes)

    assert first["versions"] == 1
    assert second["versions"] == 0        # YAML không đổi -> không sinh bản mới
    for table in ("recipe", "model", "domain", "profile", "account", "recipe_version"):
        assert db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] == 1, table


def test_changed_yaml_creates_new_version(db, recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    importer.import_all(db, recipes)
    changed = {**BROWSER_RECIPE, "url": "https://chat.qwen.ai/new"}
    write_recipe(recipes, "chat", changed)
    assert importer.import_all(db, recipes)["versions"] == 1

    versions = db.query("SELECT version, note, yaml FROM recipe_version ORDER BY version")
    assert [v["version"] for v in versions] == [1, 2]
    assert "chat.qwen.ai/new" in versions[1]["yaml"]
    assert "chat.qwen.ai/new" not in versions[0]["yaml"]   # bản cũ còn nguyên để rollback
    assert db.query("SELECT version, url FROM recipe")[0]["version"] == 2


def test_removed_model_disappears(db, recipes):
    write_recipe(recipes, "chat", {**BROWSER_RECIPE,
                                   "models": [{"id": "a"}, {"id": "b"}]})
    importer.import_all(db, recipes)
    assert db.query("SELECT COUNT(*) AS n FROM model")[0]["n"] == 2

    write_recipe(recipes, "chat", {**BROWSER_RECIPE, "models": [{"id": "b"}]})
    importer.import_all(db, recipes)
    assert [r["local_id"] for r in db.query("SELECT local_id FROM model")] == ["b"]


def test_recipe_with_no_models_clears_them(db, recipes):
    write_recipe(recipes, "chat", {**BROWSER_RECIPE, "models": [{"id": "a"}]})
    importer.import_all(db, recipes)
    write_recipe(recipes, "chat", {**BROWSER_RECIPE, "models": []})
    importer.import_all(db, recipes)
    # `NOT IN (NULL)` không xoá gì — trường hợp rỗng phải được xử lý riêng.
    assert db.query("SELECT COUNT(*) AS n FROM model")[0]["n"] == 0


def test_import_accounts_makes_one_profile_per_state_file(db, recipes):
    p1 = write_account(recipes, "chat.qwen.ai", "codex1")
    write_account(recipes, "chat.qwen.ai", "codex2")
    write_account(recipes, "chatgpt.com", "codex1")
    counts = importer.import_all(db, recipes)
    assert counts == {**counts, "profiles": 3, "accounts": 3}

    rows = db.query(
        "SELECT p.name, d.host, a.label, a.storage_state_path FROM account a"
        " JOIN profile p ON p.id = a.profile_id JOIN domain d ON d.id = a.domain_id"
        " ORDER BY p.name")
    assert [(r["name"], r["host"], r["label"]) for r in rows] == [
        ("chat-qwen-ai-codex1", "chat.qwen.ai", "codex1"),
        ("chat-qwen-ai-codex2", "chat.qwen.ai", "codex2"),
        ("chatgpt-com-codex1", "chatgpt.com", "codex1"),
    ]
    assert rows[0]["storage_state_path"] == str(p1)
    # Chưa mở lần nào -> chưa có user_data_dir; pha 4 mới cấp thư mục thật.
    assert db.query("SELECT DISTINCT user_data_dir FROM profile")[0]["user_data_dir"] == ""


def test_same_label_on_two_domains_stays_two_profiles(db, recipes):
    """'codex1' ở hai domain là hai lần đăng nhập khác nhau, không được gộp."""
    write_account(recipes, "chat.qwen.ai", "codex1")
    write_account(recipes, "chatgpt.com", "codex1")
    importer.import_all(db, recipes)
    assert db.query("SELECT COUNT(*) AS n FROM profile")[0]["n"] == 2


def test_import_shares_domain_row_between_recipe_and_account(db, recipes):
    write_recipe(recipes, "chat", BROWSER_RECIPE)
    write_account(recipes, "chat.qwen.ai", "codex1")
    importer.import_all(db, recipes)
    assert db.query("SELECT COUNT(*) AS n FROM domain")[0]["n"] == 1
    linked = db.query(
        "SELECT r.slug FROM recipe r JOIN account a ON a.domain_id = r.domain_id")
    assert [r["slug"] for r in linked] == ["chat"]


def test_import_never_writes_back_to_disk(db, recipes):
    path = write_recipe(recipes, "chat", BROWSER_RECIPE)
    before = path.read_bytes()
    importer.import_all(db, recipes)
    assert path.read_bytes() == before
