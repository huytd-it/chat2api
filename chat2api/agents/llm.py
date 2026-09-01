import json

import httpx

from ..config import Config


class LlmError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        # status của upstream (nếu lỗi đến từ HTTP response) để caller map lại
        # đúng mã cho client thay vì nuốt thành 500.
        self.status = status


def configured(cfg: Config) -> bool:
    return bool(cfg.agent_llm_base_url and cfg.agent_llm_api_key and cfg.agent_llm_model)


def extract_json(text: str) -> dict:
    if "```json" in text:
        block = text.split("```json", 1)[1].split("```", 1)[0]
        return json.loads(block)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise LlmError(f"LLM không trả JSON hợp lệ: {text[:200]!r}")


async def chat_json(cfg: Config, system: str, user: str, timeout: int = 180) -> dict:
    if not configured(cfg):
        raise LlmError(
            "Agent LLM chưa cấu hình. Đặt env AGENT_LLM_BASE_URL, "
            "AGENT_LLM_API_KEY, AGENT_LLM_MODEL (bất kỳ endpoint OpenAI-compatible).")
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{cfg.agent_llm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {cfg.agent_llm_api_key}"},
                json={"model": cfg.agent_llm_model, "temperature": 0,
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": user}]})
    except httpx.RequestError as e:
        raise LlmError(
            f"Không gọi được Agent LLM {cfg.agent_llm_base_url}: {e}") from e
    if resp.status_code >= 400:
        detail = " ".join(resp.text[:300].split())
        raise LlmError(
            f"Agent LLM trả {resp.status_code} (model {cfg.agent_llm_model}): {detail}",
            status=resp.status_code)
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise LlmError(f"Agent LLM trả response lạ: {resp.text[:200]!r}") from e
    return extract_json(content)
