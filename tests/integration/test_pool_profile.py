"""Pool khoá theo profile + tab song song (pha 4, docs/design-v2.md §3).

Chromium thật chỉ được mở ở đúng một test cuối file. Phần còn lại thay session
Scrapling bằng fake để kiểm logic khoá, eviction và seed mà không tốn vài giây
mỗi lần chạy.
"""

import asyncio
import json

import pytest

from chat2api import profiles, store
from chat2api import browserpool
from chat2api.browserpool import PROFILE_ARGS, BrowserModeError, BrowserPool


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


def install_fake_scrapling(monkeypatch):
    """Thay `scrapling.fetchers` bằng fake; trả về danh sách session đã mở.

    Mỗi session nhớ `mode` (lớp nào được chọn) và `kwargs` (thứ pool gửi xuống
    Scrapling) — đó là toàn bộ bề mặt mà pool chạm vào thư viện thật.
    """
    import sys
    import types

    sessions = []

    class FakeSession:
        mode = ""

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.context = FakePersistentContext()
            self.closed = False
            sessions.append(self)

        async def start(self):
            return None

        async def close(self):
            self.closed = True
            await self.context.close()

    class FakeStealthySession(FakeSession):
        mode = "stealthy"

    class FakeDynamicSession(FakeSession):
        mode = "dynamic"

    package = types.ModuleType("scrapling")
    package.__path__ = []
    fetchers = types.ModuleType("scrapling.fetchers")
    fetchers.AsyncStealthySession = FakeStealthySession
    fetchers.AsyncDynamicSession = FakeDynamicSession
    fetchers.FetcherSession = object
    package.fetchers = fetchers
    monkeypatch.setitem(sys.modules, "scrapling", package)
    monkeypatch.setitem(sys.modules, "scrapling.fetchers", fetchers)
    return sessions


@pytest.fixture
def pool(monkeypatch):
    """Pool với session Scrapling được thay bằng fake (`pool.sessions`)."""
    p = BrowserPool(max_contexts=2, max_profiles=2)
    p.sessions = install_fake_scrapling(monkeypatch)
    return p


def launched(pool):
    """kwargs của từng lần mở browser, theo thứ tự."""
    return [session.kwargs for session in pool.sessions]


def make_profile(db, tmp_path, name="main", max_tabs=4):
    return profiles.ensure_profile(name, tmp_path / "profiles", max_tabs=max_tabs)


# --------------------------------------------------------- mở & tái dùng


async def test_same_profile_is_launched_once_and_reused(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    first = await pool.context_for_profile(profile)
    second = await pool.context_for_profile(profile)
    assert first is second
    assert len(pool.sessions) == 1
    assert pool.profile_count == 1


async def test_launch_passes_anti_throttling_flags(pool, db, tmp_path):
    await pool.context_for_profile(make_profile(db, tmp_path))
    kwargs = launched(pool)[0]
    # Thiếu ba cờ này thì tab nền bị Chromium bóp CPU và vòng poll stable_text
    # sẽ timeout — đúng thứ làm chạy song song trở nên vô dụng.
    assert kwargs["extra_flags"] == PROFILE_ARGS
    assert kwargs["headless"] is True
    assert kwargs["additional_args"] == {"viewport": {"width": 1280, "height": 800}}
    assert kwargs["user_data_dir"] == str(tmp_path / "profiles" / "main")


async def test_optional_profile_fields_only_passed_when_set(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET proxy = ?, timezone = ? WHERE id = ?",
                     ("http://127.0.0.1:8888", "Asia/Ho_Chi_Minh", profile.id))
    await pool.context_for_profile(profiles.get_profile("main"))
    kwargs = launched(pool)[0]
    assert kwargs["proxy"] == "http://127.0.0.1:8888"
    assert kwargs["timezone_id"] == "Asia/Ho_Chi_Minh"
    assert "useragent" not in kwargs   # chưa đặt thì không gửi


# ------------------------------------------------------- chế độ Scrapling


def set_mode(db, profile_id, mode):
    conn = db.connection()
    with conn:
        conn.execute("UPDATE profile SET scrapling_mode = ? WHERE id = ?", (mode, profile_id))


async def test_new_profile_defaults_to_the_dynamic_session(pool, db, tmp_path):
    await pool.context_for_profile(make_profile(db, tmp_path))

    session = pool.sessions[0]
    assert session.mode == "dynamic"
    # Cờ vân tay là của StealthySession; DynamicSession từ chối tham số lạ.
    assert "hide_canvas" not in session.kwargs and "block_webrtc" not in session.kwargs


async def test_stealthy_profile_uses_stealth_session(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    conn = db.connection()
    with conn:
        conn.execute(
            "UPDATE profile SET scrapling_mode = 'stealthy', proxy = ?, user_agent = ?, "
            "locale = ?, timezone = ?, viewport = ? WHERE id = ?",
            ("http://127.0.0.1:8888", "agent", "vi-VN", "Asia/Ho_Chi_Minh",
             "1440x900", profile.id),
        )

    ctx = await pool.context_for_profile(profiles.get_profile("main"))

    assert pool.sessions[0].mode == "stealthy"
    kwargs = pool.sessions[0].kwargs
    assert kwargs["user_data_dir"] == str(tmp_path / "profiles" / "main")
    assert kwargs["headless"] is True
    assert kwargs["max_pages"] == profile.max_tabs
    assert kwargs["extra_flags"] == PROFILE_ARGS
    assert kwargs["hide_canvas"] is True and kwargs["block_webrtc"] is True
    assert kwargs["proxy"] == "http://127.0.0.1:8888"
    assert kwargs["useragent"] == "agent"
    assert kwargs["locale"] == "vi-VN"
    assert kwargs["timezone_id"] == "Asia/Ho_Chi_Minh"
    assert kwargs["additional_args"] == {"viewport": {"width": 1440, "height": 900}}

    await pool.drop_profile("main")
    assert pool.sessions[0].closed and ctx.closed


async def test_profile_mode_beats_the_pool_mode(pool, db, tmp_path):
    """Pool chạy stealthy nhưng profile khai dynamic thì mở bằng DynamicSession."""
    pool.mode = "stealthy"
    await pool.context_for_profile(make_profile(db, tmp_path))

    assert [session.mode for session in pool.sessions] == ["dynamic"]


async def test_fetcher_profile_refuses_to_open_a_browser(pool, db, tmp_path):
    """fetcher chỉ gửi HTTP: báo lỗi rõ ràng, không lặng lẽ mở Chromium."""
    profile = make_profile(db, tmp_path)
    set_mode(db, profile.id, "fetcher")

    with pytest.raises(BrowserModeError, match="stealthy"):
        await pool.context_for_profile(profiles.get_profile("main"))

    assert pool.sessions == [] and pool.profile_count == 0
    db.flush(timeout=10)
    # Khoá pid không được treo lại sau một lần từ chối.
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] is None


async def test_fetcher_pool_refuses_plain_contexts_too(pool):
    pool.mode = "fetcher"
    await pool.start()                   # fetcher vẫn khởi động được server

    with pytest.raises(BrowserModeError):
        await pool.context_for("site")
    assert pool.sessions == [] and pool.size == 0


async def test_switching_mode_reopens_the_same_user_data_dir(pool, db, tmp_path):
    """Đổi chế độ phải mở lại — và mở lại trên ĐÚNG profile cũ.

    Bug: context đang mở được tái dùng vô điều kiện, nên đổi chế độ từ trang
    Profiles im lặng không có tác dụng cho tới khi restart server.
    """
    profile = make_profile(db, tmp_path)
    dynamic_ctx = await pool.context_for_profile(profile)

    set_mode(db, profile.id, "stealthy")
    stealthy_ctx = await pool.context_for_profile(profiles.get_profile("main"))

    assert stealthy_ctx is not dynamic_ctx
    assert dynamic_ctx.closed, "context chế độ cũ phải đóng để nhả khoá pid"
    assert [session.mode for session in pool.sessions] == ["dynamic", "stealthy"]
    # Cùng user_data_dir = cùng cookie/localStorage: đăng nhập không mất.
    assert [kwargs["user_data_dir"] for kwargs in launched(pool)] == [profile.user_data_dir] * 2
    assert pool.launched_mode("main") == "stealthy"


async def test_mode_switch_releases_the_pid_lock_before_relaunching(
        pool, db, tmp_path, monkeypatch):
    """Session mới đụng đúng thư mục session cũ đang giữ — khoá phải nhả trước."""
    profile = make_profile(db, tmp_path)
    await pool.context_for_profile(profile)
    locks = []
    monkeypatch.setattr(profiles, "release_lock",
                        lambda pid: locks.append(("release", pid)))
    monkeypatch.setattr(profiles, "acquire_lock",
                        lambda p: locks.append(("acquire", p.id)))

    set_mode(db, profile.id, "stealthy")
    await pool.context_for_profile(profiles.get_profile("main"))

    assert locks == [("release", profile.id), ("acquire", profile.id)]


async def test_unchanged_mode_still_reuses_the_open_context(pool, db, tmp_path):
    """Guard đổi chế độ không được làm profile mở lại sau mỗi request."""
    profile = make_profile(db, tmp_path)
    first = await pool.context_for_profile(profile)
    second = await pool.context_for_profile(profiles.get_profile("main"))
    assert first is second
    assert len(pool.sessions) == 1


async def test_launched_mode_reports_what_is_actually_running(pool, db, tmp_path):
    """Cột `scrapling_mode` là ý muốn; `launched_mode` là thực tế đang chạy."""
    profile = make_profile(db, tmp_path)
    assert pool.launched_mode("main") is None
    await pool.context_for_profile(profile)
    assert pool.launched_mode("main") == "dynamic"

    # Đổi cột mà chưa mở lại: thực tế vẫn là dynamic.
    set_mode(db, profile.id, "stealthy")
    assert pool.launched_mode("main") == "dynamic"

    await pool.drop_profile("main")
    assert pool.launched_mode("main") is None


async def test_storage_state_is_seeded_and_session_is_closed(pool, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(
        '{"cookies":[{"name":"sid","value":"x","domain":"example.test","path":"/"}],'
        '"origins":[{"origin":"https://example.test","localStorage":'
        '[{"name":"token","value":"y"}]}]}',
        encoding="utf-8",
    )

    ctx = await pool.context_for("site", state)

    assert ctx.cookies[0]["name"] == "sid"
    assert any(page.goto_calls == ["https://example.test"] for page in ctx.pages)
    await pool.drop("site")
    assert pool.sessions[0].closed


async def test_headed_context_opens_a_visible_session(pool):
    await pool.context_for("a")
    await pool.context_for("b", headed=True)
    assert [kwargs["headless"] for kwargs in launched(pool)] == [True, False]


# ------------------------------------------------------------ tab song song


async def test_each_recipe_gets_its_own_tab_in_one_profile(pool, db, tmp_path):
    profile = make_profile(db, tmp_path)
    chat = await pool.page_for(profile, "chat")
    gpt = await pool.page_for(profile, "gpt")
    claude = await pool.page_for(profile, "claude")

    assert len({id(chat), id(gpt), id(claude)}) == 3
    # Ba recipe, một tiến trình Chromium duy nhất.
    assert len(pool.sessions) == 1
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
    assert len(pool.sessions) == 1


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


async def test_busy_profile_is_not_evicted_even_past_max_profiles(pool, db, tmp_path):
    """Mở nhiều profile cùng lúc không được phép cắt request đang chạy.

    Trần max_profiles là để dọn thứ bỏ quên, không phải để giết phiên đang
    stream — bàn test Sessions mở song song nhiều profile nên hay chạm trần.
    """
    first = make_profile(db, tmp_path, "main")
    second = make_profile(db, tmp_path, "work")
    third = make_profile(db, tmp_path, "spare")

    ctx1 = await pool.context_for_profile(first)
    ctx2 = await pool.context_for_profile(second)
    async with pool.hold("main"):
        ctx3 = await pool.context_for_profile(third)
        # 'main' đang bận nên nạn nhân là 'work' (rảnh, ít dùng nhất kế tiếp).
        assert not ctx1.closed and ctx2.closed and not ctx3.closed
        assert pool.profile_count == 2


async def test_all_profiles_busy_exceeds_the_cap_instead_of_closing_one(pool, db, tmp_path):
    first = make_profile(db, tmp_path, "main")
    second = make_profile(db, tmp_path, "work")
    third = make_profile(db, tmp_path, "spare")

    ctx1 = await pool.context_for_profile(first)
    ctx2 = await pool.context_for_profile(second)
    async with pool.hold("main"), pool.hold("work"):
        await pool.context_for_profile(third)
        assert not ctx1.closed and not ctx2.closed
        # Vượt trần là lựa chọn tường minh: thà tốn RAM còn hơn mất kết quả.
        assert pool.profile_count == 3


async def test_hold_is_released_after_the_request_finishes(pool, db, tmp_path):
    first = make_profile(db, tmp_path, "main")
    second = make_profile(db, tmp_path, "work")
    third = make_profile(db, tmp_path, "spare")

    ctx1 = await pool.context_for_profile(first)
    async with pool.hold("main"):
        pass
    await pool.context_for_profile(second)
    await pool.context_for_profile(third)
    assert ctx1.closed and pool.profile_count == 2


async def test_busy_tab_is_kept_and_an_idle_one_is_closed(pool, db, tmp_path):
    profile = make_profile(db, tmp_path, max_tabs=2)
    a = await pool.page_for(profile, "a")
    b = await pool.page_for(profile, "b")
    async with pool.hold(profile.name, f"{profile.name}::a"):
        await pool.page_for(profile, "c")

    assert not a.is_closed() and b.is_closed()
    assert pool.tab_count("main") == 2


async def test_all_tabs_busy_keeps_them_all_open(pool, db, tmp_path):
    profile = make_profile(db, tmp_path, max_tabs=2)
    a = await pool.page_for(profile, "a")
    b = await pool.page_for(profile, "b")
    async with pool.hold(profile.name, f"{profile.name}::a"), \
            pool.hold(profile.name, f"{profile.name}::b"):
        await pool.page_for(profile, "c")

    assert not a.is_closed() and not b.is_closed()
    assert pool.tab_count("main") == 3


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
    assert pool.sessions == []           # không được chạm vào user_data_dir


async def test_failed_launch_releases_the_lock(pool, db, tmp_path, monkeypatch):
    profile = make_profile(db, tmp_path)

    async def boom(mode, **kwargs):
        raise RuntimeError("Chromium không chạy được")

    monkeypatch.setattr(browserpool, "open_session", boom)
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
    assert pool.sessions == []           # không profile nào được mở


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
    assert len(pool.sessions) == 1
    assert pool.tab_count("main") == 1


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
    assert pool.sessions == []


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
    pytest.importorskip("scrapling.fetchers")

    pool = BrowserPool(max_profiles=1)
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
    db.flush(timeout=10)
    assert db.query("SELECT lock_pid FROM profile")[0]["lock_pid"] is None
