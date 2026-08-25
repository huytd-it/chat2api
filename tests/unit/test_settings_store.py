from chat2api import settings


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
