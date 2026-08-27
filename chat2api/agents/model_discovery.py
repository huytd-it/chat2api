import re

from . import dom, llm


SYSTEM = """Bạn là AI agent hỗ trợ web automation. Hãy đọc snapshot DOM của một trang
chat và tìm bộ chọn model.

Chỉ trả JSON theo dạng:
{
  "open_action": "click:<css selector>" hoặc null,
  "models": [
    {"id": "model-id-ngan", "label": "Tên hiển thị", "action": "click:<css selector>"},
    {"id": "model-id-ngan", "label": "Tên hiển thị", "action": "select:<css selector>", "value": "option-value"}
  ]
}

Quy tắc:
- Nếu danh sách model đang đóng, đặt open_action là selector của nút mở danh sách.
- Nếu options đã hiện, trả models và để open_action là null.
- Chỉ dùng selector có trong snapshot, không tự bịa selector.
- id chỉ gồm chữ thường ASCII, số, dấu chấm, gạch dưới hoặc gạch ngang.
- Không xem các mode như Search, Thinking, Tools là model nếu chúng chỉ là tính năng.
- Không tìm thấy thì trả models rỗng.
"""


def _slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return clean[:100] or "model"


def _valid_step(action: str, kind: str | None = None) -> bool:
    match = re.fullmatch(r"(click|select):(.+)", action.strip(), re.DOTALL)
    return bool(match and match.group(2).strip() and (kind is None or match.group(1) == kind))


def _models(data: dict, before_action: str = "") -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    raw_models = data.get("models")
    if not isinstance(raw_models, list):
        return out
    for raw in raw_models:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("id") or "").strip()
        action = str(raw.get("action") or "").strip()
        value = str(raw.get("value") or "").strip()
        if not label or len(label) > 100 or not _valid_step(action):
            continue
        if action.startswith("select:") and not value:
            continue
        model_id = _slug(str(raw.get("id") or value or label))
        if model_id in seen:
            continue
        seen.add(model_id)
        if before_action and action.startswith("click:"):
            action = f"{before_action};{action}"
        item = {"id": model_id, "label": label, "action": action}
        if value:
            item["value"] = value
        out.append(item)
    return out


async def discover(page, cfg, before_action: str = "") -> list[dict]:
    """Dùng LLM để mở model picker (tối đa một lần) và đọc danh sách model.

    Đây là fallback có kiểm soát cho bộ dò DOM thuần: agent chỉ được click selector
    có trong snapshot và kết quả vẫn được chuẩn hóa trước khi đưa vào recipe.
    ``before_action`` giữ lại nút picker mà heuristic đã mở trước khi gọi agent.
    """
    from ..providers.browser_recipe import discover_models

    for _ in range(2):
        snapshot = await dom.snapshot(page)
        data = await llm.chat_json(
            cfg,
            SYSTEM,
            f"URL: {page.url}\n\nDOM SNAPSHOT:\n{snapshot}",
            timeout=90,
        )
        models = _models(data, before_action)
        if models:
            return models

        open_action = str(data.get("open_action") or "").strip()
        if before_action or not _valid_step(open_action, "click"):
            return []
        selector = open_action.split(":", 1)[1]
        trigger = page.locator(selector).first
        if not await trigger.count() or not await trigger.is_visible():
            return []
        await trigger.click()
        await page.wait_for_timeout(300)
        before_action = open_action

        # Khi agent đã mở đúng picker, ưu tiên bộ dò xác định để không tốn thêm
        # một lượt LLM và giữ selector/value đúng nguyên văn từ DOM.
        found = await discover_models(page, before_action)
        if found:
            return found
    return []
