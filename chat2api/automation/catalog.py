import asyncio
import json
import os
import re

from fastapi import APIRouter, Depends, Request

from .. import auth, store
from ..errors import OpenAIError
from .journal import connection


def cached(slug, account_id):
    row = connection().execute("SELECT details,checked_at,state FROM automation_capability "
                               "WHERE recipe_slug=? AND account_id=? AND name='models'", (slug, account_id)).fetchone()
    return {"models": json.loads(row["details"]), "checked_at": row["checked_at"], "state": row["state"]} if row else None


def save(slug, account_id, name, state, details):
    conn = connection()
    with conn:
        conn.execute("INSERT INTO automation_capability VALUES(?,?,?,?,?,?) "
                     "ON CONFLICT(recipe_slug,account_id,name) DO UPDATE SET state=excluded.state,"
                     "details=excluded.details,checked_at=excluded.checked_at",
                     (slug, account_id, name, state, json.dumps(details), store.now_ms()))


def known_models(slug):
    if store.default() is None:
        return []
    try:
        rows = connection().execute("SELECT details FROM automation_capability WHERE recipe_slug=? AND name='models' AND state='supported'", (slug,))
        return list({item["id"]: item for row in rows for item in json.loads(row[0])}.values())
    except Exception:
        # Legacy standalone recipe runners may use an unmigrated optional store.
        return []


async def refresh(provider, account_id, force=False, headed=None):
    from .projects import account_page
    from .service import session_lock
    from ..providers.browser_recipe import discover_models
    async with session_lock(f"models:{provider.slug}:{account_id}"):
        old = await asyncio.to_thread(cached, provider.slug, account_id)
        ttl = max(0, int(os.environ.get("AUTOMATION_MODEL_TTL_SECONDS", "0")))
        if old and not force and store.now_ms() - old["checked_at"] < ttl * 1000:
            return old
        async with account_page(provider, account_id, headed) as page:
            await page.goto(provider.url, wait_until="domcontentloaded")
            action = (provider.flows.get("select_model") or {}).get("action", "")
            if action:
                await provider._exec_action_steps(page, action)
            if provider.domain == "chat.qwen.ai":
                more = page.get_by_text("Expand more models", exact=True)
                if await more.is_visible():
                    await more.click()
                await page.locator('[role="listbox"][aria-label="Models"] .wms-list__name-text').first.wait_for()
                labels = await page.locator('[role="listbox"][aria-label="Models"] .wms-list__name-text').all_text_contents()
                found = [{"id": re.sub(r"[^a-z0-9._-]+", "-", label.strip().lower()),
                          "label": label.strip(),
                          "action": 'click:[role="listbox"][aria-label="Models"] [role="option"]:has(.wms-list__name-text:text-is(' + json.dumps(label.strip()) + '))'}
                         for label in labels]
            elif provider.domain == "chatgpt.com":
                # Giao diện web (kể cả Free) không mở dropdown model: nó luôn
                # dùng model mặc định của tài khoản. Xác nhận composer đã đăng
                # nhập rồi ghi nhận đúng một model thay vì bịa danh sách.
                from ..providers.browser_recipe import _resolve_locator
                selector = (provider.flow_prompt("text").get("input_selector")
                            or 'div[contenteditable="true"][role="textbox"]')
                await _resolve_locator(page, selector).first.wait_for(state="visible", timeout=20000)
                found = [{"id": "default", "label": "ChatGPT (model mặc định của web)"}]
            else:
                found = await discover_models(page)
            if not found:
                await asyncio.to_thread(save, provider.slug, account_id, "models", "unknown", [])
                raise OpenAIError(422, "model_discovery_unknown", "Không đọc được danh sách model; chưa kết luận account không hỗ trợ")
            for item in found:
                item["capability"] = "chat"
                # Stable recipe aliases stay in /v1/models. Only new IDs join it.
            await asyncio.to_thread(save, provider.slug, account_id, "models", "supported", found)
        return await asyncio.to_thread(cached, provider.slug, account_id)


def register(app):
    api = APIRouter(prefix="/v1/accounts", dependencies=[Depends(auth.require_key)])

    @api.get("/{account_id}/models")
    async def models(account_id: int, request: Request, model: str, refresh_now: bool = False):
        from ..providers.browser_recipe import BrowserRecipe
        from ..router import ModelNotFound
        from .service import headed_from
        try:
            provider, _ = request.app.state.router.resolve(model)
        except ModelNotFound:
            # Endpoint này nhận model chỉ để tìm provider; model sai là lỗi
            # người gọi (404), không phải lỗi máy chủ 500.
            raise OpenAIError(404, "model_not_found", f"Model '{model}' không tồn tại")
        if not isinstance(provider, BrowserRecipe):
            raise OpenAIError(422, "models_unsupported", "Model không dùng browser recipe")
        result = await refresh(provider, account_id, refresh_now, headed_from(request))
        return {"account_id": account_id, "checked_at": result["checked_at"], "state": result["state"],
                "data": [dict(item, id=f"{provider.slug}/{item['id']}") for item in result["models"]]}

    @api.get("/{account_id}/capabilities")
    async def capabilities(account_id: int, recipe_slug: str):
        def load():
            rows = connection().execute("SELECT name,state,details,checked_at FROM automation_capability WHERE account_id=? AND recipe_slug=?",
                                        (account_id, recipe_slug)).fetchall()
            values = {name: {"state": "unknown", "checked_at": None} for name in ("models", "thinking", "projects", "images")}
            values.update({r["name"]: {"state": r["state"], "details": json.loads(r["details"]), "checked_at": r["checked_at"]} for r in rows})
            return values
        return await asyncio.to_thread(load)

    app.include_router(api)
