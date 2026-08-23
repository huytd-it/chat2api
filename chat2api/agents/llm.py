import json

import httpx

from ..config import Config


class LlmError(RuntimeError):
    pass


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
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{cfg.agent_llm_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {cfg.agent_llm_api_key}"},
            json={"model": cfg.agent_llm_model, "temperature": 0,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]})
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return extract_json(content)
