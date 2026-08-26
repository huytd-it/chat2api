import os
import sqlite3

import pytest

from chat2api import settings, store


def test_validate_rejects_unknown_key():
    clean, errs = settings.validate({"HOME": "/tmp"})
    assert clean == {}
    assert "HOME" in errs[0]


def test_validate_coerces_types():
    clean, errs = settings.validate({
        "RECIPE_READY_DELAY_MS": " 900 ",
        "ENABLE_AGENT_FALLBACK": "YES",
        "BROWSER_ENGINE": "cloak",
    })
    assert errs == []
    assert clean == {"RECIPE_READY_DELAY_MS": "900", "ENABLE_AGENT_FALLBACK": "true",
                     "BROWSER_ENGINE": "cloak"}


def test_validate_reports_bad_values():
    _, errs = settings.validate({"RECIPE_READY_DELAY_MS": "abc"})
    assert "số nguyên" in errs[0]
    _, errs = settings.validate({"POOL_MAX_CONTEXTS": "-1"})
    assert ">= 0" in errs[0]
    _, errs = settings.validate({"BROWSER_ENGINE": "firefox"})
    assert "playwright" in errs[0]


def test_empty_secret_means_keep_current():
    clean, errs = settings.validate({"AGENT_LLM_API_KEY": "   "})
    assert (clean, errs) == ({}, [])
    clean, _ = settings.validate({"AGENT_LLM_API_KEY": "sk-new"})
    assert clean == {"AGENT_LLM_API_KEY": "sk-new"}


def test_describe_never_leaks_secret(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_API_KEY", "sk-secret")
    field = next(f for f in settings.describe() if f["key"] == "AGENT_LLM_API_KEY")
    assert field["value"] == ""
    assert field["is_set"] is True


def test_save_preserves_comments_and_updates_in_place(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# cấu hình\nRECIPE_READY_DELAY_MS=100\nOTHER=keep\n", encoding="utf-8")
    monkeypatch.delenv("RECIPE_READY_DELAY_MS", raising=False)

    restart = settings.save(env, {"RECIPE_READY_DELAY_MS": "1500", "POOL_MAX_CONTEXTS": "5"})

    text = env.read_text(encoding="utf-8")
    assert "# cấu hình" in text
    assert "RECIPE_READY_DELAY_MS=1500" in text
    assert "OTHER=keep" in text
    assert "POOL_MAX_CONTEXTS=5" in text
    # Delay áp dụng ngay khi reload recipe; pool phải restart mới có hiệu lực.
    assert restart == ["POOL_MAX_CONTEXTS"]


def test_save_creates_env_when_missing(tmp_path):
    env = tmp_path / "nested" / ".env"
    settings.save(env, {"RECIPE_INPUT_DELAY_MS": "250"})
    assert "RECIPE_INPUT_DELAY_MS=250" in env.read_text(encoding="utf-8")


# ------------------------------------------------- pha 6: bảng `setting` là kho


@pytest.fixture
def clean_settings():
    """Trạng thái module là global — trả về nguyên trạng để test không dây sang nhau."""
    store.shutdown()
    saved_env, saved_injected = set(settings._env_keys), set(settings._injected)
    settings._env_keys.clear()
    settings._injected.clear()
    yield
    store.shutdown()
    settings._env_keys = saved_env
    settings._injected = saved_injected


def _open(tmp_path):
    handle = store.connect(tmp_path / "s.db")
    handle.migrate()
    return handle


def test_save_writes_setting_table_not_env(tmp_path, clean_settings, monkeypatch):
    monkeypatch.delenv("RECIPE_READY_DELAY_MS", raising=False)
    db = _open(tmp_path)
    env = tmp_path / ".env"

    settings.save(env, {"RECIPE_READY_DELAY_MS": "900"})

    assert not env.exists()  # kho mở rồi thì .env không bị đụng tới
    assert db.query("SELECT value FROM setting WHERE key = ?",
                    ("RECIPE_READY_DELAY_MS",))[0]["value"] == "900"


def test_save_marks_secret_rows(tmp_path, clean_settings, monkeypatch):
    monkeypatch.delenv("AGENT_LLM_API_KEY", raising=False)
    db = _open(tmp_path)

    settings.save(tmp_path / ".env", {"AGENT_LLM_API_KEY": "sk-x", "BROWSER_ENGINE": "cloak"})

    rows = {r["key"]: r["is_secret"] for r in db.query("SELECT key, is_secret FROM setting")}
    assert rows == {"AGENT_LLM_API_KEY": 1, "BROWSER_ENGINE": 0}


def test_save_upserts_instead_of_duplicating(tmp_path, clean_settings, monkeypatch):
    monkeypatch.delenv("POOL_MAX_CONTEXTS", raising=False)
    db = _open(tmp_path)

    settings.save(tmp_path / ".env", {"POOL_MAX_CONTEXTS": "5"})
    settings.save(tmp_path / ".env", {"POOL_MAX_CONTEXTS": "7"})

    rows = db.query("SELECT value FROM setting WHERE key = ?", ("POOL_MAX_CONTEXTS",))
    assert [r["value"] for r in rows] == ["7"]


def test_preload_fills_env_for_keys_dotenv_left_alone(tmp_path, clean_settings, monkeypatch):
    monkeypatch.delenv("RECIPE_INPUT_DELAY_MS", raising=False)
    monkeypatch.setenv("BROWSER_ENGINE", "playwright")  # .env của người vận hành
    db_path = tmp_path / "s.db"
    _open(tmp_path)
    settings.capture_env()
    settings.save(tmp_path / ".env", {"RECIPE_INPUT_DELAY_MS": "250", "BROWSER_ENGINE": "cloak"})
    store.shutdown()

    # Giả lập vòng khởi động sau trong một tiến trình mới: os.environ chỉ còn
    # thứ .env đặt, và .env ghim BROWSER_ENGINE nên hàng DB không chen vào được.
    os.environ.pop("RECIPE_INPUT_DELAY_MS", None)
    settings._injected.clear()
    settings.capture_env()
    assert settings.preload(db_path) == 1
    assert os.environ["RECIPE_INPUT_DELAY_MS"] == "250"
    assert os.environ["BROWSER_ENGINE"] == "playwright"


def test_preload_ignores_missing_or_unmigrated_db(tmp_path, clean_settings):
    assert settings.preload(tmp_path / "khong-co.db") == 0
    empty = tmp_path / "trong.db"
    sqlite3.connect(empty).close()
    assert settings.preload(empty) == 0
    # Và không tự tạo file trong thư mục dữ liệu — import phải sạch.
    assert not (tmp_path / "khong-co.db").exists()


def test_preloaded_keys_do_not_lock_themselves(tmp_path, clean_settings, monkeypatch):
    """Giá trị từ DB nằm trong os.environ, nhưng lần capture_env sau không được
    coi chúng là do .env đặt — nếu không, khoá tự khoá chính nó sau một restart."""
    monkeypatch.delenv("RECIPE_READY_TIMEOUT_MS", raising=False)
    db_path = tmp_path / "s.db"
    _open(tmp_path)
    settings.save(tmp_path / ".env", {"RECIPE_READY_TIMEOUT_MS": "30000"})
    store.shutdown()

    settings.capture_env()
    settings.preload(db_path)
    settings.capture_env()

    assert settings.env_locked("RECIPE_READY_TIMEOUT_MS") is False


def test_describe_reports_source_and_env_lock(tmp_path, clean_settings, monkeypatch):
    monkeypatch.delenv("RECIPE_READY_DELAY_MS", raising=False)
    monkeypatch.setenv("BROWSER_ENGINE", "cloak")
    _open(tmp_path)
    settings.capture_env()
    settings.save(tmp_path / ".env", {"RECIPE_READY_DELAY_MS": "900"})

    fields = {f["key"]: f for f in settings.describe()}
    assert fields["RECIPE_READY_DELAY_MS"]["source"] == "db"
    assert fields["RECIPE_READY_DELAY_MS"]["value"] == "900"
    assert fields["BROWSER_ENGINE"]["source"] == "env"
    assert fields["BROWSER_ENGINE"]["env_locked"] is True
    assert fields["POOL_MAX_PROFILES"]["source"] == "default"


def test_env_locked_key_is_saved_but_reported_shadowed(tmp_path, clean_settings, monkeypatch):
    monkeypatch.setenv("BROWSER_ENGINE", "playwright")
    db = _open(tmp_path)
    settings.capture_env()

    settings.save(tmp_path / ".env", {"BROWSER_ENGINE": "cloak"})

    assert settings.shadowed(["BROWSER_ENGINE"]) == ["BROWSER_ENGINE"]
    # Ghi xuống kho để lần bỏ dòng .env đi là dùng được ngay...
    assert db.query("SELECT value FROM setting WHERE key = ?",
                    ("BROWSER_ENGINE",))[0]["value"] == "cloak"
    # ...nhưng tiến trình đang chạy vẫn giữ giá trị của .env.
    assert os.environ["BROWSER_ENGINE"] == "playwright"
