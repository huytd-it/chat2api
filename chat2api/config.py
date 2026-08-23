import os
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Config:
    def __init__(self) -> None:
        self.api_keys = [k.strip() for k in _env("CHAT2API_KEYS").split(",") if k.strip()]
        self.recipes_dir = Path(_env("RECIPES_DIR", "./recipes"))
        self.agent_llm_base_url = _env("AGENT_LLM_BASE_URL").rstrip("/")
        self.agent_llm_api_key = _env("AGENT_LLM_API_KEY")
        self.agent_llm_model = _env("AGENT_LLM_MODEL")
        self.enable_fallback = _env("ENABLE_AGENT_FALLBACK", "false").lower() == "true"
        self.pool_max_contexts = int(_env("POOL_MAX_CONTEXTS", "3"))
        self.pool_acquire_timeout = int(_env("POOL_ACQUIRE_TIMEOUT", "30"))
        self.browser_engine = _env("BROWSER_ENGINE", "playwright")
        self.recipe_timeout_ms = int(_env("RECIPE_TIMEOUT_MS", "120000"))
        self.integrate_max_rounds = int(_env("INTEGRATE_MAX_ROUNDS", "5"))
