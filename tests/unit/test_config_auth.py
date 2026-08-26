import asyncio
from pathlib import Path

from fastapi import FastAPI

from chat2api.auth import require_key
from chat2api.config import Config
from chat2api.errors import OpenAIError


def test_config_defaults(monkeypatch, tmp_path):
    # Config() nạp `.env` ở cwd vào os.environ, nên delenv một mình không đủ:
    # .env của máy dev sẽ chen ngược vào và test đọc ra giá trị của người khác.
    # Đổi cwd sang thư mục rỗng để "mặc định" đúng nghĩa là mặc định.
    monkeypatch.chdir(tmp_path)
    for k in ("CHAT2API_KEYS", "RECIPES_DIR", "AGENT_LLM_BASE_URL", "ENABLE_AGENT_FALLBACK",
             "ANON_TRIAL_LIMIT", "CHAT2API_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    cfg = Config()
    assert cfg.api_keys == []
    assert cfg.browser_engine == "playwright"
    assert cfg.recipe_timeout_ms == 120000
    assert cfg.enable_fallback is False
    assert cfg.anon_trial_limit == 20
    assert cfg.data_dir == Path("./data")
    assert cfg.db_path == Path("./data/chat2api.db")


def test_config_parse(monkeypatch):
    monkeypatch.setenv("CHAT2API_KEYS", " a , b,, ")
    monkeypatch.setenv("ENABLE_AGENT_FALLBACK", "TRUE")
    monkeypatch.setenv("ANON_TRIAL_LIMIT", "5")
    cfg = Config()
    assert cfg.api_keys == ["a", "b"]
    assert cfg.enable_fallback is True
    assert cfg.anon_trial_limit == 5


def test_config_loads_dotenv_without_overriding_process_env(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "AGENT_LLM_BASE_URL=https://llm.example/v1\n"
        "AGENT_LLM_API_KEY=from-dotenv\n"
        "AGENT_LLM_MODEL=dotenv-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for name in ("AGENT_LLM_BASE_URL", "AGENT_LLM_API_KEY", "AGENT_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENT_LLM_MODEL", "process-model")

    cfg = Config()

    assert cfg.agent_llm_base_url == "https://llm.example/v1"
    assert cfg.agent_llm_api_key == "from-dotenv"
    assert cfg.agent_llm_model == "process-model"


def make_request(path: str, api_keys: list[str]):
    cfg = Config()
    cfg.api_keys = api_keys
    state = type("S", (), {"cfg": cfg})()
    app = type("A", (), {"state": state})()

    class R:
        pass

    r = R()
    r.app = app
    r.url = type("U", (), {"path": path})()
    r.headers = {}
    # Starlette.Request có `.state`; require_key ghi api_key_id vào đó.
    r.state = type("St", (), {})()
    return r


def test_auth_allows_when_no_keys():
    asyncio.run(require_key(make_request("/v1/models", [])))


def test_auth_public_path():
    asyncio.run(require_key(make_request("/health", ["k1"])))


def test_auth_valid_and_invalid_key():
    r = make_request("/v1/models", ["k1"])
    r.headers = {"authorization": "Bearer k1"}
    asyncio.run(require_key(r))
    try:
        asyncio.run(require_key(make_request("/v1/models", ["k1"])))
        assert False
    except OpenAIError as e:
        assert e.status == 401 and e.code == "invalid_api_key"
