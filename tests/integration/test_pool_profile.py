"""Pool khoá theo profile + tab song song (pha 4, docs/design-v2.md §3).

Chromium thật chỉ được mở ở đúng một test cuối file (đánh dấu bằng
`playwright.importorskip`). Phần còn lại dùng fake context để kiểm logic khoá,
eviction và seed mà không tốn vài giây mỗi lần chạy.
"""

import asyncio
import json

import pytest

from chat2api import profiles, store
from chat2api.browserpool import PROFILE_ARGS, BrowserPool


class FakePage:
    def __init__(self, url="about:blank"):
        self.url = url
        self.closed = False
        self.goto_calls = []
        self.evaluated = []

    def is_closed(self):
        return self.closed

    async def close(self):
        self.closed = True

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)

    async def evaluate(self, script, arg=None):
        self.evaluated.append(arg)


class FakePersistentContext:
    def __init__(self, blank_pages=1, **kwargs):
        self.kwargs = kwargs
        self.pages = [FakePage() for _ in range(blank_pages)]
        self.cookies = []
        self.closed = False

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page

    async def add_cookies(self, cookies):
        self.cookies.extend(cookies)

    async def close(self):
        self.closed = True
        for page in self.pages:
            page.closed = True


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        store.shutdown()


@pytest.fixture
def pool(monkeypatch, tmp_path):
    """Pool với launch_persistent_context được thay bằng fake."""
    p = BrowserPool(max_contexts=2, max_profiles=2)
    launched = []

    class FakeChromium:
        async def launch_persistent_context(self, **kwargs):
            launched.append(kwargs)
            return FakePersistentContext(**{})

    class FakePW:
        chromium = FakeChromium()

    p._pw = FakePW()
    p.launched = launched
    return p


def make_profile(db, tmp_path, name="main", max_tabs=4):
    return profiles.ensure_profile(name, tmp_path / "profiles", max_tabs=max_tabs)


# --------------------------------------------------------- mở & tái dùng


async def test_same_profile_is_launched_once_and_reused(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    first = await pool.context_for_profile(profile)
    second = await pool.context_for_profile(profile)
    assert first is second
    assert len(pool.launched) == 1
    assert pool.profile_count == 1


async def test_launch_passes_anti_throttling_flags(pool, db, tmp_path):
    await pool.context_for_profile(make_profile(db, tmp_path))
    args = pool.launched[0]["args"]
    # Thiếu ba cờ này thì tab nền bị Chromium bóp CPU và vòng poll stable_text
    # sẽ timeout — đúng thứ làm chạy song song trở nên vô dụng.
    assert args == PROFILE_ARGS
    assert pool.launched[0]["headless"] is True
    assert pool.launched[0]["viewport"] == {"width": 1280, "height": 800}


async def test_optional_profile_fields_only_passed_when_set(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET proxy = ?, timezone = ? WHERE id = ?",
                     ("http://127.0.0.1:8888", "Asia/Ho_Chi_Minh", profile.id))
    await pool.context_for_profile(profiles.get_profile("main"))
    kwargs = pool.launched[0]
    assert kwargs["proxy"] == {"server": "http://127.0.0.1:8888"}
    assert kwargs["timezone_id"] == "Asia/Ho_Chi_Minh"
    assert "user_agent" not in kwargs   # chưa đặt thì không gửi


# ------------------------------------------------------------ tab song song


async def test_each_recipe_gets_its_own_tab_in_one_profile(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    chat = await pool.page_for(profile, "chat")
    gpt = await pool.page_for(profile, "gpt")
    claude = await pool.page_for(profile, "claude")

    assert len({id(chat), id(gpt), id(claude)}) == 3
    # Ba recipe, một tiến trình Chromium duy nhất.
    assert len(pool.launched) == 1
    assert pool.tab_count("main") == 3


async def test_same_recipe_reuses_its_tab(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    first = await pool.page_for(profile, "chat")
    second = await pool.page_for(profile, "chat")
    assert first is second
    assert pool.tab_count("main") == 1


async def test_first_tab_claims_the_blank_page_instead_of_leaving_it_open(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    ctx = await pool.context_for_profile(profile)
    blank = ctx.pages[0]
    page = await pool.page_for(profile, "chat")
    # Persistent context luôn mở sẵn about:blank; nhận nó thay vì để cửa sổ trống.
    assert page is blank
    assert len(ctx.pages) == 1


async def test_closed_tab_is_reopened(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    first = await pool.page_for(profile, "chat")
    await first.close()
    second = await pool.page_for(profile, "chat")
    assert second is not first and not second.is_closed()


async def test_tabs_evicted_past_max_tabs_but_profile_stays_open(pool, db, tmp_path):
    profile = make_profile(db, tmp_path, max_tabs=2)
    a = await pool.page_for(profile, "a")
    await pool.page_for(profile, "b")
    await pool.page_for(profile, "c")

    assert pool.tab_count("main") == 2
    assert a.is_closed()                 # tab ít dùng nhất bị đóng
    assert pool.profile_count == 1       # browser vẫn sống
    assert len(pool.launched) == 1


# ------------------------------------------------------------- eviction


async def test_profile_evicted_past_max_profiles_and_lock_released(pool, db, tmp_path):
    first = make_profile(db, tmp_path, "main")
    second = make_profile(db, tmp_path, "work")
    third = make_profile(db, tmp_path, "spare")

    ctx1 = await pool.context_for_profile(first)
    await pool.context_for_profile(second)
    await pool.context_for_profile(third)

    assert pool.profile_count == 2
    assert ctx1.closed
    db.flush(timeout=10)
    # Profile bị đóng phải nhả khoá, nếu không lần mở sau sẽ bị chính nó chặn.
    assert db.query("SELECT lock_pid FROM profile WHERE name = 'main'")[0]["lock_pid"] is None


async def test_drop_profile_closes_and_releases(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    ctx = await pool.context_for_profile(profile)
    await pool.page_for(profile, "chat")

    assert await pool.drop_profile("main") is True
    assert ctx.closed and pool.profile_count == 0 and pool.tab_count("main") == 0
    db.flush(timeout=10)
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] is None

    assert await pool.drop_profile("main") is False   # đóng lần hai là no-op


async def test_aclose_closes_profiles_too(pool, db, tmp_path):
    ctx = await pool.context_for_profile(make_profile(db, tmp_path))
    await pool.aclose()
    assert ctx.closed and pool.profile_count == 0


# ----------------------------------------------------------------- khoá


async def test_locked_profile_refuses_to_open(pool, db, tmp_path, monkeypatch):
    profile = make_profile(db, tmp_path)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET lock_pid = 999999 WHERE id = ?", (profile.id,))
    monkeypatch.setattr(profiles, "_pid_alive", lambda pid: True)

    with pytest.raises(profiles.ProfileLocked):
        await pool.context_for_profile(profiles.get_profile("main"))
    assert pool.launched == []           # không được chạm vào user_data_dir


async def test_failed_launch_releases_the_lock(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)

    async def boom(**kwargs):
        raise RuntimeError("Chromium không chạy được")

    pool._pw.chromium.launch_persistent_context = boom
    with pytest.raises(RuntimeError):
        await pool.context_for_profile(profile)
    db.flush(timeout=10)
    # Khoá treo lại sau một lần mở hỏng sẽ khoá chết profile vĩnh viễn.
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] is None


# ------------------------------------------------------------------ seed


async def test_storage_state_is_seeded_once_then_cleared(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    state = tmp_path / "codex1.json"
    state.write_text(json.dumps({
        "cookies": [{"name": "sid", "value": "abc", "domain": ".qwen.ai", "path": "/"}],
        "origins": [{"origin": "https://chat.qwen.ai",
                     "localStorage": [{"name": "token", "value": "xyz"}]}],
    }), encoding="utf-8")
    conn = db.connection()
    with conn:
        conn.execute("INSERT INTO domain(host, created_at) VALUES ('chat.qwen.ai', ?)",
                     (store.now_ms(),))
        domain_id = conn.execute("SELECT id FROM domain").fetchone()["id"]
        conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, storage_state_path, created_at) "
            "VALUES (?, ?, 'codex1', ?, ?)",
            (profile.id, domain_id, str(state), store.now_ms()))

    ctx = await pool.context_for_profile(profile)
    assert [c["name"] for c in ctx.cookies] == ["sid"]
    db.flush(timeout=10)
    assert db.query("SELECT storage_state_path FROM account")[0]["storage_state_path"] is None
    assert state.exists()                # file gốc giữ làm backup

    # Mở lại lần hai: không seed nữa.
    await pool.drop_profile("main")
    ctx2 = await pool.context_for_profile(profiles.get_profile("main"))
    assert ctx2.cookies == []


async def test_broken_state_file_does_not_block_opening(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    state = tmp_path / "hỏng.json"
    state.write_text("{không phải json", encoding="utf-8")
    conn = db.connection()
    with conn:
        conn.execute("INSERT INTO domain(host, created_at) VALUES ('x.test', ?)", (store.now_ms(),))
        domain_id = conn.execute("SELECT id FROM domain").fetchone()["id"]
        conn.execute(
            "INSERT INTO account(profile_id, domain_id, label, storage_state_path, created_at) "
            "VALUES (?, ?, 'a', ?, ?)", (profile.id, domain_id, str(state), store.now_ms()))

    ctx = await pool.context_for_profile(profile)   # không được ném
    assert ctx is not None


# ----------------------------------------- storage_state vẫn là mặc định


async def test_default_mode_never_touches_the_profile_path(pool, db, tmp_path, monkeypatch):
    """Mặc định phải đi đường cũ — đây là ràng buộc đã chốt ở §9."""
    from chat2api.providers.browser_recipe import BrowserRecipe

    monkeypatch.delenv("BROWSER_PROFILE_MODE", raising=False)
    recipe = {
        "slug": "chat", "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m1"}],
    }
    provider = BrowserRecipe(recipe, tmp_path, pool)
    assert provider._profile_mode is False

    calls = []

    async def fake_context_for(key, state=None, headed=False):
        calls.append(key)
        return FakePersistentContext()

    pool.context_for = fake_context_for
    await provider._acquire_page("chat", None, False)
    assert calls == ["chat"]
    assert pool.launched == []           # không profile nào được mở


async def test_profile_mode_routes_through_the_profile(pool, db, tmp_path, monkeypatch):
    from chat2api.providers.browser_recipe import BrowserRecipe

    monkeypatch.setenv("BROWSER_PROFILE_MODE", "profile")
    monkeypatch.setenv("CHAT2API_DATA_DIR", str(tmp_path))
    make_profile(db, tmp_path, "main")
    recipe = {
        "slug": "chat", "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m1"}],
    }
    provider = BrowserRecipe(recipe, tmp_path, pool)
    assert provider._profile_mode is True

    page = await provider._acquire_page("chat", None, False)
    assert page is not None
    assert len(pool.launched) == 1
    assert pool.tab_count("main") == 1


async def test_cloak_engine_stays_on_storage_state(tmp_path, monkeypatch):
    """cloakbrowser không nhận user_data_dir — chế độ profile phải tự tắt."""
    from chat2api.providers.browser_recipe import BrowserRecipe

    monkeypatch.setenv("BROWSER_PROFILE_MODE", "profile")
    monkeypatch.setenv("BROWSER_ENGINE", "cloak")
    recipe = {
        "slug": "chat", "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m1"}],
    }
    assert BrowserRecipe(recipe, tmp_path, None)._profile_mode is False


async def test_headed_request_falls_back_to_the_old_path(pool, db, tmp_path, monkeypatch):
    """Live view cần cửa sổ hiện lên; đường profile chạy headless nên nhường."""
    from chat2api.providers.browser_recipe import BrowserRecipe

    monkeypatch.setenv("BROWSER_PROFILE_MODE", "profile")
    monkeypatch.setenv("CHAT2API_DATA_DIR", str(tmp_path))
    make_profile(db, tmp_path, "main")
    recipe = {
        "slug": "chat", "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m1"}],
    }
    provider = BrowserRecipe(recipe, tmp_path, pool)

    seen = []

    async def fake_context_for(key, state=None, headed=False):
        seen.append(headed)
        return FakePersistentContext()

    pool.context_for = fake_context_for
    await provider._acquire_page("chat", None, True)
    assert seen == [True]
    assert pool.launched == []


async def test_profile_failure_falls_back_instead_of_killing_chat(pool, db, tmp_path,
                                                                  monkeypatch, capsys):
    from chat2api.providers.browser_recipe import BrowserRecipe

    monkeypatch.setenv("BROWSER_PROFILE_MODE", "profile")
    monkeypatch.setenv("CHAT2API_DATA_DIR", str(tmp_path))
    profile = make_profile(db, tmp_path, "main")
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET lock_pid = 999999 WHERE id = ?", (profile.id,))
    monkeypatch.setattr(profiles, "_pid_alive", lambda pid: True)

    recipe = {
        "slug": "chat", "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".m", "done_signal": {"type": "stable_text"}},
        "models": [{"id": "m1"}],
    }
    provider = BrowserRecipe(recipe, tmp_path, pool)
    fallback = []

    async def fake_context_for(key, state=None, headed=False):
        fallback.append(key)
        return FakePersistentContext()

    pool.context_for = fake_context_for
    page = await provider._acquire_page("chat", None, False)
    # Profile bị khoá là chuyện của một tính năng opt-in; chat vẫn phải chạy.
    assert page is not None and fallback == ["chat"]
    # Khoá bị phát hiện lúc mở context, nên đây là nhánh "mở profile thất bại".
    err = capsys.readouterr().err
    assert "dùng storage_state" in err and "999999" in err


# ------------------------------------------------- Chromium thật, 1 lần


async def test_real_chromium_shares_one_process_across_two_tabs(db, tmp_path):
    pytest.importorskip("playwright.async_api")
    from playwright.async_api import async_playwright

    pool = BrowserPool(max_profiles=1)
    pool._pw = await async_playwright().start()
    profile = make_profile(db, tmp_path, "main", max_tabs=4)
    try:
        chat = await pool.page_for(profile, "chat")
        gpt = await pool.page_for(profile, "gpt")
        assert chat is not gpt
        assert pool.tab_count("main") == 2

        # Hai tab thật, cùng một profile: viết localStorage ở tab này phải đọc
        # được ở tab kia — bằng chứng chúng dùng chung một danh tính trình duyệt.
        await chat.goto("data:text/html,<title>a</title>")
        await gpt.goto("data:text/html,<title>b</title>")
        assert await chat.title() == "a" and await gpt.title() == "b"

        db.flush(timeout=10)
        import os
        assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] == os.getpid()
    finally:
        await pool.aclose()
        await pool._pw.stop()
    db.flush(timeout=10)
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] is None
