"""Quản lý profile Chromium (pha 4, docs/design-v2.md §3).

Không mở Chromium thật ở đây — file này chỉ kiểm phần trạng thái: hàng DB, thư
mục, khoá pid, và việc chọn profile cho một recipe.
"""

import os
from pathlib import Path

import pytest

from chat2api import profiles, store


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        store.shutdown()


@pytest.fixture
def profiles_dir(tmp_path):
    return tmp_path / "data" / "profiles"


def test_ensure_creates_row_and_directory(db, profiles_dir):
    profile = profiles.ensure_profile("main", profiles_dir, max_tabs=3)
    assert profile.name == "main" and profile.max_tabs == 3
    assert (profiles_dir / "main").is_dir()
    assert profile.user_data_dir == str(profiles_dir / "main")


def test_ensure_is_idempotent(db, profiles_dir):
    first = profiles.ensure_profile("main", profiles_dir)
    second = profiles.ensure_profile("main", profiles_dir)
    assert first.id == second.id
    assert db.query("SELECT COUNT(*) AS n FROM profile")[0]["n"] == 1


def test_ensure_fills_user_data_dir_left_empty_by_importer(db, profiles_dir):
    # Importer (pha 2) tạo hàng profile với user_data_dir rỗng vì chưa mở lần nào.
    conn = db.connection()
    with conn:
        conn.execute("INSERT INTO profile(name, user_data_dir, created_at) VALUES (?, '', ?)",
                     ("chat-qwen-ai-codex1", store.now_ms()))
    profile = profiles.ensure_profile("chat-qwen-ai-codex1", profiles_dir)
    assert profile.user_data_dir == str(profiles_dir / "chat-qwen-ai-codex1")
    assert (profiles_dir / "chat-qwen-ai-codex1").is_dir()
    assert db.query("SELECT COUNT(*) AS n FROM profile")[0]["n"] == 1


def test_invalid_name_is_rejected_before_touching_disk(db, tmp_path):
    for bad in ("../escape", "Có Dấu", "", "a" * 65):
        with pytest.raises(ValueError):
            profiles.ensure_profile(bad, tmp_path / "profiles")
    assert not (tmp_path / "profiles").exists()


def test_make_default_moves_the_single_default_flag(db, profiles_dir):
    profiles.ensure_profile("main", profiles_dir, make_default=True)
    profiles.ensure_profile("work", profiles_dir, make_default=True)
    rows = db.query("SELECT name FROM profile WHERE is_default = 1")
    # Partial unique index chỉ cho đúng một default — nếu không clear cái cũ
    # trước thì insert thứ hai sẽ nổ.
    assert [r["name"] for r in rows] == ["work"]


def test_works_without_store(tmp_path):
    store.shutdown()
    assert profiles.ensure_profile("main", tmp_path / "p") is None
    assert profiles.list_profiles() == []
    assert profiles.profile_for_recipe("chat") == "main"


# ------------------------------------------------------------- khoá pid


def test_acquire_lock_records_current_pid(db, profiles_dir):
    profile = profiles.ensure_profile("main", profiles_dir)
    profiles.acquire_lock(profile)
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] == os.getpid()


def test_reacquiring_own_lock_is_allowed(db, profiles_dir):
    profile = profiles.ensure_profile("main", profiles_dir)
    profiles.acquire_lock(profile)
    profiles.acquire_lock(profile)  # cùng tiến trình: không được ném


def test_lock_held_by_live_foreign_process_is_refused(db, profiles_dir, monkeypatch):
    profile = profiles.ensure_profile("main", profiles_dir)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET lock_pid = 999999 WHERE id = ?", (profile.id,))
    monkeypatch.setattr(profiles, "_pid_alive", lambda pid: True)
    with pytest.raises(profiles.ProfileLocked) as err:
        profiles.acquire_lock(profile)
    assert "999999" in str(err.value)


def test_lock_of_dead_process_is_reclaimed(db, profiles_dir, monkeypatch):
    profile = profiles.ensure_profile("main", profiles_dir)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET lock_pid = 999999 WHERE id = ?", (profile.id,))
    monkeypatch.setattr(profiles, "_pid_alive", lambda pid: False)
    profiles.acquire_lock(profile)
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] == os.getpid()


def test_release_only_clears_our_own_lock(db, profiles_dir):
    profile = profiles.ensure_profile("main", profiles_dir)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET lock_pid = 999999 WHERE id = ?", (profile.id,))
    profiles.release_lock(profile.id)
    db.flush(timeout=10)
    # Khoá của tiến trình khác phải còn nguyên.
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] == 999999

    profiles.acquire_lock(profiles.get_profile("main"))
    profiles.release_lock(profile.id)
    db.flush(timeout=10)
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] is None


def test_pid_alive_reports_true_for_this_process():
    assert profiles._pid_alive(os.getpid()) is True
    assert profiles._pid_alive(0) is False


# ----------------------------------------------------------------- seed


def _account(db, profile_id: int, host: str, label: str, state_path):
    conn = db.connection()
    with conn:
        conn.execute("INSERT OR IGNORE INTO domain(host, created_at) VALUES (?, ?)",
                     (host, store.now_ms()))
        domain_id = conn.execute("SELECT id FROM domain WHERE host = ?", (host,)).fetchone()["id"]
        cursor = conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, storage_state_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (profile_id, domain_id, label, str(state_path) if state_path else None, store.now_ms()))
    return int(cursor.lastrowid)


def test_pending_seeds_lists_existing_files_only(db, profiles_dir, tmp_path):
    profile = profiles.ensure_profile("main", profiles_dir)
    good = tmp_path / "codex1.json"
    good.write_text('{"cookies": []}', encoding="utf-8")
    good_id = _account(db, profile.id, "chat.qwen.ai", "codex1", good)
    missing_id = _account(db, profile.id, "chatgpt.com", "work", tmp_path / "không-có.json")

    pending = profiles.pending_seeds(profile.id)
    assert [(aid, p.name) for aid, p in pending] == [(good_id, "codex1.json")]

    # Hàng trỏ vào file đã mất được dọn luôn, để không thử lại mãi mỗi lần mở.
    db.flush(timeout=10)
    row = db.query("SELECT storage_state_path FROM account WHERE id = ?", (missing_id,))[0]
    assert row["storage_state_path"] is None


def test_clear_seed_marks_profile_self_sufficient(db, profiles_dir, tmp_path):
    profile = profiles.ensure_profile("main", profiles_dir)
    state = tmp_path / "codex1.json"
    state.write_text("{}", encoding="utf-8")
    account_id = _account(db, profile.id, "chat.qwen.ai", "codex1", state)

    profiles.clear_seed(account_id)
    db.flush(timeout=10)
    assert profiles.pending_seeds(profile.id) == []
    # File gốc không bị xoá — nó vẫn là bản sao lưu.
    assert state.exists()


# ------------------------------------------------- chọn profile cho recipe


def _recipe(db, slug: str, host: str, profile_id: int | None = None):
    conn = db.connection()
    with conn:
        conn.execute("INSERT OR IGNORE INTO domain(host, created_at) VALUES (?, ?)",
                     (host, store.now_ms()))
        domain_id = conn.execute("SELECT id FROM domain WHERE host = ?", (host,)).fetchone()["id"]
        conn.execute(
            "INSERT INTO recipe(slug, kind, url, domain_id, profile_id, created_at, updated_at) "
            "VALUES (?, 'browser', ?, ?, ?, ?, ?)",
            (slug, f"https://{host}/", domain_id, profile_id, store.now_ms(), store.now_ms()))
    return domain_id


def test_recipe_uses_its_pinned_profile(db, profiles_dir):
    pinned = profiles.ensure_profile("work", profiles_dir)
    profiles.ensure_profile("main", profiles_dir, make_default=True)
    _recipe(db, "chat", "chat.qwen.ai", profile_id=pinned.id)
    assert profiles.profile_for_recipe("chat") == "work"


def test_recipe_follows_the_profile_that_has_the_login(db, profiles_dir):
    profiles.ensure_profile("main", profiles_dir, make_default=True)
    logged_in = profiles.ensure_profile("qwen-box", profiles_dir)
    domain_id = _recipe(db, "chat", "chat.qwen.ai")
    _account(db, logged_in.id, "chat.qwen.ai", "codex1", None)
    # Account nằm trên đúng domain của recipe -> đó là nơi đã đăng nhập.
    assert profiles.profile_for_recipe("chat") == "qwen-box"
    assert domain_id


def test_recipe_without_account_falls_back_to_default(db, profiles_dir):
    profiles.ensure_profile("main", profiles_dir, make_default=True)
    _recipe(db, "chat", "chat.qwen.ai")
    assert profiles.profile_for_recipe("chat") == "main"


def test_disabled_account_does_not_capture_the_recipe(db, profiles_dir):
    profiles.ensure_profile("main", profiles_dir, make_default=True)
    disabled = profiles.ensure_profile("old-box", profiles_dir)
    _recipe(db, "chat", "chat.qwen.ai")
    account_id = _account(db, disabled.id, "chat.qwen.ai", "codex1", None)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE account SET disabled = 1 WHERE id = ?", (account_id,))
    assert profiles.profile_for_recipe("chat") == "main"


def test_list_profiles_reports_domain_count_and_lock(db, profiles_dir, monkeypatch):
    main = profiles.ensure_profile("main", profiles_dir, make_default=True)
    profiles.ensure_profile("work", profiles_dir)
    _account(db, main.id, "chat.qwen.ai", "codex1", None)
    _account(db, main.id, "chatgpt.com", "work", None)
    profiles.acquire_lock(main)

    monkeypatch.setattr(profiles, "_pid_alive", lambda pid: True)
    items = {p["name"]: p for p in profiles.list_profiles()}
    assert items["main"]["domains"] == 2 and items["main"]["locked"] is True
    assert items["work"]["domains"] == 0 and items["work"]["locked"] is False
    # Profile mặc định đứng đầu danh sách.
    assert profiles.list_profiles()[0]["name"] == "main"


# ------------------------------------------------------------ nhân bản

def _seed_dir(profile, *, cache=True):
    """Giả lập một user_data_dir đã dùng: có đăng nhập, có cache, có khoá."""
    root = Path(profile.user_data_dir)
    (root / "Default").mkdir(parents=True, exist_ok=True)
    (root / "Default" / "Cookies").write_text("cookie-thật", encoding="utf-8")
    (root / "Local State").write_text("{}", encoding="utf-8")
    if cache:
        (root / "Default" / "Cache").mkdir(exist_ok=True)
        (root / "Default" / "Cache" / "data_0").write_text("rác", encoding="utf-8")
        (root / "SingletonLock").write_text("máy-cũ", encoding="utf-8")
    return root


def test_clone_copies_logins_but_not_cache_or_lock_files(db, profiles_dir):
    source = profiles.ensure_profile("main", profiles_dir, make_default=True)
    _seed_dir(source)

    copy = profiles.clone(source.id, "main-cloak", profiles_dir, {"engine": "cloak"})

    target = Path(copy["user_data_dir"])
    assert target == profiles_dir / "main-cloak"
    assert (target / "Default" / "Cookies").read_text(encoding="utf-8") == "cookie-thật"
    assert (target / "Local State").is_file()
    # Cache tự dựng lại được; khoá mang theo là Chromium tưởng profile đang bị giữ.
    assert not (target / "Default" / "Cache").exists()
    assert not (target / "SingletonLock").exists()
    # Bản gốc không được đụng tới.
    assert (Path(source.user_data_dir) / "Default" / "Cache" / "data_0").is_file()


def test_clone_inherits_settings_except_the_overridden_ones(db, profiles_dir):
    source = profiles.create("main", profiles_dir,
                             {"engine": "playwright", "max_tabs": 7, "headless": False,
                              "notes": "máy chính", "viewport": "1600x900"})
    copy = profiles.clone(source["id"], "main-cloak", profiles_dir, {"engine": "cloak"})

    assert copy["engine"] == "cloak"
    assert copy["max_tabs"] == 7 and copy["headless"] == 0
    assert copy["viewport"] == "1600x900" and copy["notes"] == "máy chính"
    # Bản sao không cướp cờ mặc định, không mang theo khoá của bản gốc.
    assert copy["is_default"] == 0 and copy["lock_pid"] is None
    assert profiles.get_by_id(source["id"])["engine"] == "playwright"


def test_clone_carries_the_accounts_so_the_router_can_see_it(db, profiles_dir, tmp_path):
    source = profiles.ensure_profile("main", profiles_dir)
    state = tmp_path / "codex1.json"
    state.write_text("{}", encoding="utf-8")
    _account(db, source.id, "chat.qwen.ai", "codex1", state)
    _account(db, source.id, "chatgpt.com", "work", None)

    copy = profiles.clone(source.id, "main-cloak", profiles_dir)

    got = [(a["host"], a["label"]) for a in profiles.accounts_of(copy["id"])]
    assert got == [("chat.qwen.ai", "codex1"), ("chatgpt.com", "work")]
    # Seed còn dở của nguồn theo sang, để bản sao cũng tự nạp cookie lần mở đầu.
    assert [p.name for _, p in profiles.pending_seeds(copy["id"])] == ["codex1.json"]
    # Account của nguồn vẫn nguyên, không bị "chuyển" đi.
    assert len(profiles.accounts_of(source.id)) == 2


def test_clone_of_a_profile_never_opened_still_works(db, profiles_dir):
    """Hàng do importer tạo chưa có thư mục thật — clone không được nổ vì thế."""
    source = profiles.ensure_profile("main", profiles_dir)
    import shutil

    shutil.rmtree(source.user_data_dir)
    copy = profiles.clone(source.id, "main-2", profiles_dir)
    assert (profiles_dir / "main-2").is_dir()
    assert copy["name"] == "main-2"


def test_clone_refuses_duplicate_and_invalid_names(db, profiles_dir):
    source = profiles.ensure_profile("main", profiles_dir)
    profiles.ensure_profile("work", profiles_dir)
    with pytest.raises(ValueError):
        profiles.clone(source.id, "work", profiles_dir)
    with pytest.raises(ValueError):
        profiles.clone(source.id, "Tên Sai", profiles_dir)
    assert len(profiles.list_profiles()) == 2


def test_clone_refuses_while_chromium_still_holds_the_source(db, profiles_dir, monkeypatch):
    source = profiles.ensure_profile("main", profiles_dir)
    _seed_dir(source)
    profiles.acquire_lock(source)
    monkeypatch.setattr(profiles, "_pid_alive", lambda pid: True)

    with pytest.raises(profiles.ProfileLocked):
        profiles.clone(source.id, "main-cloak", profiles_dir)
    # Không để lại thư mục dở dang.
    assert not (profiles_dir / "main-cloak").exists()


def test_clone_of_unknown_profile_returns_none(db, profiles_dir):
    assert profiles.clone(999, "moi", profiles_dir) is None


def test_viewport_size_parsing():
    def make(viewport):
        return profiles.Profile(1, "p", "/tmp/p", True, 4, "playwright", None, None,
                                "en-US", None, viewport)

    assert make("1280x800").viewport_size == {"width": 1280, "height": 800}
    assert make("rác").viewport_size is None
