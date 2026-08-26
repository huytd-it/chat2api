"""Chọn account/profile cho từng request (`BrowserRecipe.assign`).

Câu hỏi cả file này trả lời: hai request đến cùng lúc có được gửi tới HAI
profile khác nhau không, và request đó có ghi lại được nó đã đi tới đâu không.
Không mở Chromium — assign chỉ đọc DB và bộ đếm trong RAM.
"""

import asyncio
import os
from pathlib import Path

import pytest

from chat2api import profiles, store
from chat2api.providers.browser_recipe import BrowserRecipe


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        store.shutdown()


@pytest.fixture
def recipe(tmp_path):
    return BrowserRecipe({
        "slug": "qwen", "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "#p"},
        "response": {"last_message_selector": ".m",
                     "done_signal": {"type": "stable_text"}},
        "models": [{"id": "max"}],
    }, tmp_path / "recipes" / "qwen", None, accounts_root=tmp_path / "recipes")


def _accounts(count: int, host: str = "chat.qwen.ai") -> list[dict]:
    """`count` profile, mỗi profile một account trên cùng domain."""
    out = []
    for index in range(count):
        profile = profiles.ensure_profile(f"p{index}", Path(os.environ["TEST_PROFILES_DIR"]))
        out.append(profiles.add_account(profile.id, host, f"acc{index}"))
    return out


@pytest.fixture(autouse=True)
def _profiles_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_PROFILES_DIR", str(tmp_path / "profiles"))
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "least_busy")
    monkeypatch.setenv("API_MAX_CONCURRENT_PER_ACCOUNT", "1")


async def test_assign_reports_account_and_profile(db, recipe):
    [account] = _accounts(1)
    assignment = await recipe.assign()
    try:
        assert assignment.account_id == account["id"]
        assert assignment.account_label == "acc0"
        assert assignment.profile_name == "p0"
        assert assignment.host == "chat.qwen.ai"
        assert assignment.label == "p0/chat.qwen.ai/acc0"
    finally:
        assignment.release()


async def test_two_concurrent_requests_land_on_two_profiles(db, recipe):
    _accounts(2)
    first, second = await asyncio.gather(recipe.assign(), recipe.assign())
    try:
        # Đây chính là lỗi ban đầu: hai request cùng lúc dồn vào một profile.
        assert {first.profile_name, second.profile_name} == {"p0", "p1"}
        assert first.ctx_key != second.ctx_key
    finally:
        first.release()
        second.release()


async def test_least_busy_reuses_account_once_it_is_free_again(db, recipe):
    _accounts(2)
    first = await recipe.assign()
    second = await recipe.assign()
    assert {first.profile_name, second.profile_name} == {"p0", "p1"}
    first.release()
    # p0 rảnh trở lại nên request thứ ba phải về đó, không phải xếp hàng sau p1.
    third = await recipe.assign()
    try:
        assert third.profile_name == first.profile_name
    finally:
        second.release()
        third.release()


async def test_release_is_idempotent(db, recipe):
    _accounts(1)
    assignment = await recipe.assign()
    assignment.release()
    assignment.release()
    assert recipe.inflight() == 0


async def test_round_robin_cycles_even_when_everything_is_free(db, recipe, monkeypatch):
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "round_robin")
    _accounts(3)
    names = []
    for _ in range(6):
        assignment = await recipe.assign()
        names.append(assignment.profile_name)
        assignment.release()
    assert names == ["p0", "p1", "p2", "p0", "p1", "p2"]


async def test_sticky_session_keeps_one_session_on_one_account(db, recipe, monkeypatch):
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "sticky_session")
    _accounts(3)
    picked = []
    for _ in range(4):
        assignment = await recipe.assign(sticky_key="session-abc")
        picked.append(assignment.profile_name)
        assignment.release()
    assert len(set(picked)) == 1
    other = await recipe.assign(sticky_key="session-xyz")
    other.release()
    # Khoá khác thì được phép rơi vào cùng account (băm), chỉ cần ổn định.
    again = await recipe.assign(sticky_key="session-xyz")
    try:
        assert again.profile_name == other.profile_name
    finally:
        again.release()


async def test_strategy_off_falls_back_to_storage_state(db, recipe, monkeypatch):
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "off")
    _accounts(2)
    assignment = await recipe.assign()
    try:
        assert assignment.account_id is None
        assert assignment.profile_name is None
        assert assignment.ctx_key == "qwen"
    finally:
        assignment.release()


async def test_explicit_account_beats_every_strategy(db, recipe):
    accounts = _accounts(2)
    wanted = accounts[1]["id"]
    first = await recipe.assign()          # least_busy sẽ chọn p0
    second = await recipe.assign(wanted)   # nhưng client chỉ đích danh p1
    try:
        assert second.account_id == wanted
        assert second.profile_name == "p1"
    finally:
        first.release()
        second.release()


async def test_extra_slots_open_a_second_tab_on_the_same_account(db, recipe, monkeypatch):
    monkeypatch.setenv("API_MAX_CONCURRENT_PER_ACCOUNT", "2")
    _accounts(1)
    first = await recipe.assign()
    second = await recipe.assign()
    try:
        # Cùng account, hai tab khác nhau ⇒ chạy song song thay vì nối đuôi.
        assert first.account_id == second.account_id
        assert first.ctx_key != second.ctx_key
        assert second.ctx_key.endswith("#1")
    finally:
        first.release()
        second.release()


async def test_account_of_another_domain_is_never_picked(db, recipe):
    _accounts(1)
    other = profiles.ensure_profile("gpt", Path(os.environ["TEST_PROFILES_DIR"]))
    profiles.add_account(other.id, "chatgpt.com", "acc0")
    for _ in range(4):
        assignment = await recipe.assign()
        try:
            assert assignment.host == "chat.qwen.ai"
        finally:
            assignment.release()


async def test_disabled_account_is_skipped(db, recipe):
    accounts = _accounts(2)
    db.connection().execute("UPDATE account SET disabled = 1 WHERE id = ?",
                            (accounts[0]["id"],))
    db.connection().commit()
    assignment = await recipe.assign()
    try:
        assert assignment.account_id == accounts[1]["id"]
    finally:
        assignment.release()


async def test_no_db_account_falls_back_to_anonymous_path(db, recipe):
    assignment = await recipe.assign()
    try:
        assert assignment.account_id is None
        assert assignment.ctx_key == "qwen"
    finally:
        assignment.release()


# ------------------------------------------------- hiện cửa sổ hay chạy ẩn


def _profile(db, name="show", headless=True):
    profile = profiles.ensure_profile(name, Path(os.environ["TEST_PROFILES_DIR"]),
                                      headless=headless)
    profiles.add_account(profile.id, "chat.qwen.ai", "main")
    return profile


def test_client_header_beats_every_setting(db, recipe, monkeypatch):
    profile = _profile(db)
    monkeypatch.setenv("API_HEADED", "never")
    assert recipe.resolve_headed(True, profile) is True
    monkeypatch.setenv("API_HEADED", "always")
    assert recipe.resolve_headed(False, profile) is False


def test_api_headed_always_shows_a_window(db, recipe, monkeypatch):
    monkeypatch.setenv("API_HEADED", "always")
    # Profile khai "chạy ẩn" nhưng người dùng bảo mọi request API phải hiện cửa sổ.
    assert recipe.resolve_headed(None, _profile(db, headless=True)) is True


def test_api_headed_never_stays_hidden(db, recipe, monkeypatch):
    monkeypatch.setenv("API_HEADED", "never")
    assert recipe.resolve_headed(None, _profile(db, "quiet", headless=False)) is False


def test_api_headed_auto_follows_the_profile(db, recipe, monkeypatch):
    monkeypatch.setenv("API_HEADED", "auto")
    assert recipe.resolve_headed(None, _profile(db, "hidden", headless=True)) is False
    assert recipe.resolve_headed(None, _profile(db, "shown", headless=False)) is True


def test_api_headed_auto_without_profile_uses_provider_default(db, recipe, monkeypatch):
    monkeypatch.setenv("API_HEADED", "auto")
    assert recipe.resolve_headed(None, None) is False
