import yaml

from chat2api import accounts


def test_domain_of_strips_www_and_port():
    assert accounts.domain_of("https://www.Chat.Qwen.ai/c/123") == "chat.qwen.ai"
    assert accounts.domain_of("https://site.example:8443/chat") == "site.example"
    assert accounts.domain_of("") == ""


def test_invalid_domain_blocks_path_traversal():
    assert not accounts.valid_domain("../../etc")
    assert not accounts.valid_domain("a/b")
    assert accounts.valid_domain("chat.qwen.ai")


def test_invalid_account_names():
    assert accounts.valid_name("codex-1")
    assert not accounts.valid_name("Bad Name")
    assert not accounts.valid_name("-lead")
    assert not accounts.valid_name("")


def test_list_accounts_and_domains(tmp_path):
    path = accounts.account_path(tmp_path, "chat.qwen.ai", "codex1")
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    assert accounts.list_domains(tmp_path) == ["chat.qwen.ai"]
    assert [n for n, _ in accounts.list_accounts(tmp_path, "chat.qwen.ai")] == ["codex1"]
    assert accounts.list_accounts(tmp_path, "other.example") == []


def test_delete_account(tmp_path):
    path = accounts.account_path(tmp_path, "site.example", "a1")
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    assert accounts.delete_account(tmp_path, "site.example", "a1") is True
    assert accounts.delete_account(tmp_path, "site.example", "a1") is False
    assert not path.exists()


def _legacy_recipe(recipes_dir, slug, url, names):
    directory = recipes_dir / slug
    (directory / "auth").mkdir(parents=True)
    for name in names:
        (directory / "auth" / f"{name}.json").write_text('{"cookies": []}', encoding="utf-8")
    recipe = {"slug": slug, "url": url,
              "login": {"accounts": [{"name": n, "storage_state": f"auth/{n}.json"}
                                     for n in names]}}
    (directory / "recipe.yaml").write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return directory


def test_migrate_legacy_copies_into_domain_store(tmp_path):
    directory = _legacy_recipe(tmp_path, "chat", "https://chat.qwen.ai/", ["codex1", "codex2"])

    moved = accounts.migrate_legacy(tmp_path)

    assert sorted(moved) == ["chat.qwen.ai/codex1", "chat.qwen.ai/codex2"]
    assert accounts.account_path(tmp_path, "chat.qwen.ai", "codex1").exists()
    # Chép chứ không di chuyển: file gốc còn nguyên cho bản cũ.
    assert (directory / "auth" / "codex1.json").exists()


def test_migrate_legacy_picks_up_undeclared_auth_files(tmp_path):
    """Account có file nhưng recipe.yaml quên khai báo vẫn phải được gom."""
    directory = _legacy_recipe(tmp_path, "chat", "https://chat.qwen.ai/", ["codex1"])
    (directory / "auth" / "codex2.json").write_text('{"cookies": []}', encoding="utf-8")
    (directory / "auth" / "state.json").write_text('{"cookies": []}', encoding="utf-8")

    moved = accounts.migrate_legacy(tmp_path)

    assert sorted(moved) == ["chat.qwen.ai/codex1", "chat.qwen.ai/codex2",
                             "chat.qwen.ai/default"]
    names = [n for n, _ in accounts.list_accounts(tmp_path, "chat.qwen.ai")]
    assert names == ["codex1", "codex2", "default"]


def test_migrate_legacy_does_not_duplicate_declared_file_under_stem(tmp_path):
    _legacy_recipe(tmp_path, "chat", "https://chat.qwen.ai/", ["codex1"])

    accounts.migrate_legacy(tmp_path)

    assert [n for n, _ in accounts.list_accounts(tmp_path, "chat.qwen.ai")] == ["codex1"]


def test_migrate_legacy_is_idempotent_and_keeps_newer_state(tmp_path):
    _legacy_recipe(tmp_path, "chat", "https://chat.qwen.ai/", ["codex1"])
    accounts.migrate_legacy(tmp_path)
    target = accounts.account_path(tmp_path, "chat.qwen.ai", "codex1")
    target.write_text('{"cookies": ["fresher"]}', encoding="utf-8")

    assert accounts.migrate_legacy(tmp_path) == []
    assert "fresher" in target.read_text(encoding="utf-8")
