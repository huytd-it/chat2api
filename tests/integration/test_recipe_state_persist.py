"""Trạng thái recipe sống sót qua restart (pha 2 của docs/design-v2.md §8).

Hai thứ §1 gọi là "mất khi restart": bộ đếm hỏng của router và số lượt dùng thử
ẩn danh đã tiêu. Bộ đếm hỏng vẫn giữ nguyên ngữ nghĩa cũ (reload là xoá) — DB chỉ
mirror trạng thái sống và giữ *lịch sử* qua last_ok_at / last_error.
"""

import pytest
import yaml

from chat2api import store
from chat2api.providers.browser_recipe import BrowserRecipe, TrialLimitExceeded
from chat2api.router import Router
from chat2api.store import importer

RECIPE = {
    "url": "https://chat.qwen.ai/",
    "slug": "chat",
    "prompt": {"input_selector": "textarea"},
    "response": {"last_message_selector": ".msg", "done_signal": {"type": "stable_text"}},
    "models": [{"id": "qwen-web"}],
    "login": {"anon_trial_limit": 2},
}


@pytest.fixture
def recipes(tmp_path):
    d = tmp_path / "recipes" / "chat"
    d.mkdir(parents=True)
    (d / "recipe.yaml").write_text(yaml.safe_dump(RECIPE, allow_unicode=True, sort_keys=False),
                                   encoding="utf-8")
    return tmp_path / "recipes"


@pytest.fixture
def db(tmp_path, recipes):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    importer.import_all(s, recipes)
    try:
        yield s
    finally:
        store.shutdown()


# ------------------------------------------------------------ health recipe


def test_failure_and_success_mirror_into_db(db, recipes):
    router = Router(recipes)
    router.mark_failure("chat", "recipe timeout sau 120000ms")
    router.mark_failure("chat", "selector không tìm thấy")
    db.flush(timeout=10)

    row = db.query("SELECT failures, last_error, last_error_at, last_ok_at FROM recipe")[0]
    assert row["failures"] == 2
    assert row["last_error"] == "selector không tìm thấy"
    assert row["last_error_at"] > 0 and row["last_ok_at"] is None

    router.mark_success("chat")
    db.flush(timeout=10)
    row = db.query("SELECT failures, last_error, last_ok_at FROM recipe")[0]
    assert row["failures"] == 0 and row["last_ok_at"] > 0
    # Lỗi cuối vẫn giữ làm lịch sử, không bị xoá theo bộ đếm.
    assert row["last_error"] == "selector không tìm thấy"


def test_reload_clears_counter_but_keeps_history(db, recipes):
    router = Router(recipes)
    for _ in range(3):
        router.mark_failure("chat", "hỏng")
    assert router.is_unhealthy("chat") is True

    router.reload()
    db.flush(timeout=10)
    # Người dùng sửa recipe rồi bấm reload là để nó được thử lại từ đầu — ngữ
    # nghĩa này không đổi, và DB phải theo RAM chứ không được hiện "unhealthy" ma.
    assert router.is_unhealthy("chat") is False
    row = db.query("SELECT failures, last_error, last_error_at FROM recipe")[0]
    assert row["failures"] == 0
    assert row["last_error"] == "hỏng" and row["last_error_at"] > 0


def test_router_works_without_store(recipes):
    store.shutdown()
    assert store.default() is None
    router = Router(recipes)
    router.reload()
    for _ in range(3):
        router.mark_failure("chat", "hỏng")
    assert router.is_unhealthy("chat") is True
    router.mark_success("chat")
    assert router.is_unhealthy("chat") is False


def test_unknown_slug_update_is_a_noop(db, recipes):
    Router(recipes).mark_failure("không-có-thật", "x")
    db.flush(timeout=10)
    assert db.query("SELECT COUNT(*) AS n FROM recipe WHERE failures != 0")[0]["n"] == 0


# ----------------------------------------------------- lượt dùng thử ẩn danh


def _recipe(recipes):
    return BrowserRecipe(dict(RECIPE), recipes / "chat", pool=None, accounts_root=recipes)


async def test_anon_uses_survive_restart(db, recipes):
    provider = _recipe(recipes)
    assert provider.trial_status == {"limit": 2, "used": 0}
    await provider._rotator.next()
    db.flush(timeout=10)
    assert db.query("SELECT anon_used FROM recipe")[0]["anon_used"] == 1

    # Dựng lại provider = server restart: bộ đếm phải tiếp tục, không về 0.
    restarted = _recipe(recipes)
    assert restarted.trial_status == {"limit": 2, "used": 1}
    await restarted._rotator.next()
    with pytest.raises(TrialLimitExceeded):
        await restarted._rotator.next()


async def test_anon_uses_start_at_zero_without_store(recipes):
    store.shutdown()
    provider = _recipe(recipes)
    assert provider.trial_status == {"limit": 2, "used": 0}
    await provider._rotator.next()
    assert provider.trial_status == {"limit": 2, "used": 1}


async def test_no_trial_counting_once_an_account_exists(db, recipes):
    account_dir = recipes / ".accounts" / "chat.qwen.ai"
    account_dir.mkdir(parents=True)
    (account_dir / "codex1.json").write_text("{}", encoding="utf-8")
    provider = _recipe(recipes)
    assert provider.account_count == 1
    assert provider.trial_status is None
    await provider._rotator.next()
    db.flush(timeout=10)
    assert db.query("SELECT anon_used FROM recipe")[0]["anon_used"] == 0
