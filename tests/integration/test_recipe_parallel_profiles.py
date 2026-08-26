"""Hai request cùng lúc phải chạy trên HAI profile Chromium thật.

Đây là bằng chứng cuối cho lỗi ban đầu: trước khi có `assign()`, mọi request
dùng chung một tab nên chúng nối đuôi nhau và không bản ghi nào nói được request
nào đã đi tới account nào. File này mở Chromium thật vì cái cần kiểm đúng là
phần mà fake không thay được: hai persistent context riêng, hai tab riêng.
"""

import asyncio

import pytest

from chat2api import accounts, profiles, store
from chat2api.browserpool import BrowserPool
from chat2api.providers.browser_recipe import BrowserRecipe

pytest.importorskip("playwright.async_api")


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        store.shutdown()


@pytest.fixture(autouse=True)
def _spread_settings(monkeypatch):
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "least_busy")
    monkeypatch.setenv("API_MAX_CONCURRENT_PER_ACCOUNT", "1")


async def test_two_requests_run_on_two_profiles_at_once(db, fixture_recipe, tmp_path):
    host = accounts.domain_of(fixture_recipe["url"])
    for name, label in (("alpha", "one"), ("beta", "two")):
        profile = profiles.ensure_profile(name, tmp_path / "profiles", max_tabs=4)
        profiles.add_account(profile.id, host, label)

    pool = BrowserPool(max_contexts=2, max_profiles=2)
    await pool.start()
    provider = BrowserRecipe(fixture_recipe, tmp_path / "recipe", pool,
                             accounts_root=tmp_path / "recipe")
    try:
        first, second = await asyncio.gather(provider.assign(), provider.assign())
        assert {first.profile_name, second.profile_name} == {"alpha", "beta"}

        async def run(assignment):
            out = []
            async for delta in provider.stream([{"role": "user", "content": "hi"}],
                                               "fixture-web", assignment=assignment):
                out.append(delta)
            return "".join(out).strip()

        try:
            replies = await asyncio.gather(run(first), run(second))
        finally:
            first.release()
            second.release()

        assert replies == ["This is the reply.", "This is the reply."]
        # Hai profile = hai tiến trình Chromium, mỗi cái đúng một tab của recipe.
        assert sorted(pool.open_profiles) == ["alpha", "beta"]
        assert pool.tab_count("alpha") == 1 and pool.tab_count("beta") == 1
        # Và mỗi request để lại link của riêng nó để mở xem trực tiếp.
        assert first.conversation_url and second.conversation_url
    finally:
        await pool.aclose()


async def test_requests_on_one_account_queue_on_the_same_tab(db, fixture_recipe, tmp_path):
    host = accounts.domain_of(fixture_recipe["url"])
    profile = profiles.ensure_profile("solo", tmp_path / "profiles", max_tabs=4)
    profiles.add_account(profile.id, host, "only")

    pool = BrowserPool(max_contexts=1, max_profiles=1)
    await pool.start()
    provider = BrowserRecipe(fixture_recipe, tmp_path / "recipe", pool,
                             accounts_root=tmp_path / "recipe")
    try:
        first, second = await asyncio.gather(provider.assign(), provider.assign())
        # Một account, một slot ⇒ cùng tab: hai request phải nối đuôi nhau chứ
        # không chen ngang vào cùng một ô input.
        assert first.ctx_key == second.ctx_key

        async def run(assignment):
            out = []
            async for delta in provider.stream([{"role": "user", "content": "hi"}],
                                               "fixture-web", assignment=assignment):
                out.append(delta)
            return "".join(out).strip()

        try:
            replies = await asyncio.gather(run(first), run(second))
        finally:
            first.release()
            second.release()
        assert replies == ["This is the reply.", "This is the reply."]
        assert pool.tab_count("solo") == 1
    finally:
        await pool.aclose()


async def test_api_headed_always_opens_a_visible_window(db, fixture_recipe, tmp_path,
                                                        monkeypatch):
    """API_HEADED=always cho request API đúng đường mà bàn test vẫn đang chạy."""
    monkeypatch.setenv("API_HEADED", "always")
    host = accounts.domain_of(fixture_recipe["url"])
    # Profile khai "chạy ẩn" — cài đặt API phải thắng nó.
    profile = profiles.ensure_profile("shown", tmp_path / "profiles", headless=True)
    profiles.add_account(profile.id, host, "main")

    pool = BrowserPool(max_contexts=1, max_profiles=1)
    await pool.start()
    provider = BrowserRecipe(fixture_recipe, tmp_path / "recipe", pool,
                             accounts_root=tmp_path / "recipe")
    try:
        assignment = await provider.assign()
        try:
            out = []
            async for delta in provider.stream([{"role": "user", "content": "hi"}],
                                               "fixture-web", assignment=assignment):
                out.append(delta)
            assert "".join(out).strip() == "This is the reply."
            assert assignment.headed is True
            # False = context được launch với headless=False, tức có cửa sổ thật.
            assert pool.profile_headless("shown") is False
        finally:
            assignment.release()
    finally:
        await pool.aclose()


async def test_headless_profile_is_reopened_when_a_window_is_asked_for(
        db, fixture_recipe, tmp_path, monkeypatch):
    """Profile đang chạy nền không thể 'hiện' cửa sổ — phải dựng lại tiến trình."""
    monkeypatch.setenv("API_HEADED", "never")
    host = accounts.domain_of(fixture_recipe["url"])
    profile = profiles.ensure_profile("flip", tmp_path / "profiles", headless=True)
    profiles.add_account(profile.id, host, "main")

    pool = BrowserPool(max_contexts=1, max_profiles=1)
    await pool.start()
    provider = BrowserRecipe(fixture_recipe, tmp_path / "recipe", pool,
                             accounts_root=tmp_path / "recipe")
    try:
        first = await provider.assign()
        try:
            async for _ in provider.stream([{"role": "user", "content": "hi"}],
                                           "fixture-web", assignment=first):
                pass
        finally:
            first.release()
        assert pool.profile_headless("flip") is True

        monkeypatch.setenv("API_HEADED", "always")
        second = await provider.assign()
        try:
            async for _ in provider.stream([{"role": "user", "content": "hi"}],
                                           "fixture-web", assignment=second):
                pass
        finally:
            second.release()
        assert pool.profile_headless("flip") is False
    finally:
        await pool.aclose()


# ------------------------------ nhiều request hơn số profile


async def test_more_requests_than_profiles_queue_instead_of_failing(
        db, fixture_recipe, tmp_path):
    """6 request, 2 profile: không cái nào bị từ chối, mức song song trần ở 2.

    Đây là câu trả lời cho "quá tải thì sao": xếp hàng, không rớt. Request thứ
    ba trở đi chờ ở khoá ctx_key của account nó được gán, và chỉ bắt đầu tính
    giờ timeout của recipe SAU khi giành được khoá.
    """
    host = accounts.domain_of(fixture_recipe["url"])
    for name, label in (("alpha", "one"), ("beta", "two")):
        profile = profiles.ensure_profile(name, tmp_path / "profiles", max_tabs=4)
        profiles.add_account(profile.id, host, label)

    pool = BrowserPool(max_contexts=2, max_profiles=2)
    await pool.start()
    provider = BrowserRecipe(fixture_recipe, tmp_path / "recipe", pool,
                             accounts_root=tmp_path / "recipe")
    peak = 0
    sampling = True

    async def watch():
        nonlocal peak
        while sampling:
            peak = max(peak, pool.busy_tabs)
            await asyncio.sleep(0.02)

    async def one():
        assignment = await provider.assign()
        try:
            out = []
            async for delta in provider.stream([{"role": "user", "content": "hi"}],
                                               "fixture-web", assignment=assignment):
                out.append(delta)
            return "".join(out).strip(), assignment.profile_name
        finally:
            assignment.release()

    watcher = asyncio.create_task(watch())
    try:
        results = await asyncio.gather(*(one() for _ in range(6)))
    finally:
        sampling = False
        await watcher
        await pool.aclose()

    assert [text for text, _ in results] == ["This is the reply."] * 6
    # Hai account, mỗi account một slot ⇒ nhiều nhất 2 request chạy cùng lúc…
    assert peak == 2
    # …và 6 request được chia đều chứ không dồn hết vào một profile.
    picked = [name for _, name in results]
    assert picked.count("alpha") == 3 and picked.count("beta") == 3
    assert provider.inflight() == 0
