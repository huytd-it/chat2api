"""Kiểm chứng model biến thể của một recipe trên site thật — KHÔNG gửi tin.

Với mỗi model (đã bung `variants`), chạy đúng đường chọn model của provider
(`flows.select_model.action` + `models[].action`) rồi chạy biểu thức JS
`--state` để đọc lại trạng thái trên trang, so với kỳ vọng.

    uv run python skills/model-variants/scripts/check_variants.py \
        --recipe recipes/chat-z-ai/recipe.yaml --profile codex001 --only 'glm-*' \
        --peek 'click:[aria-label="Select a model"]' \
        --state "document.querySelector('[role=slider][aria-label=Effort]')?.getAttribute('aria-valuetext')"

    # Qwen: nhãn chế độ đang chọn
    uv run python skills/model-variants/scripts/check_variants.py \
        --recipe recipes/qwen-web/recipe.yaml --profile codex07 --only 'qwen3.8-max-*' \
        --state "document.querySelector('.qwen-thinking-selector .qwen-chat-v2-dropdown-menu-select-label')?.innerText"

Kết quả: mỗi model một dòng `id  variant  state  OK|LỖI`. Model biến thể
cuối danh sách để lại trạng thái trên account — chạy thêm `--restore <id>`
để đặt lại chế độ mặc định (vd `qwen3.8-max-fast`).
"""
import argparse
import asyncio
import json
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import yaml


async def main(a) -> list[dict]:
    from chat2api.browserpool import open_session
    from chat2api.providers.browser_recipe import BrowserRecipe

    recipe_path = Path(a.recipe)
    recipe = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    provider = BrowserRecipe(recipe, recipe_path.parent, None)
    models = [m for m in provider._recipe["models"]
              if any(fnmatchcase(m["id"], p) for p in a.only)]
    s = await open_session(a.mode, headless=not a.headed, user_data_dir=f"data/profiles/{a.profile}")
    rows = []
    try:
        page = s.context.pages[0] if s.context.pages else await s.context.new_page()
        await page.goto(provider.url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(a.wait_ms)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)
        for m in models:
            row = {"id": m["id"], "variant": m.get("variant")}
            try:
                await provider._select_model(page, m)
                await page.wait_for_timeout(600)
                if a.peek:  # mở menu/khung chứa control để đọc trạng thái
                    await provider._exec_action_steps(page, a.peek)
                    await page.wait_for_timeout(600)
                row["state"] = await page.evaluate(a.state) if a.state else None
                row["ok"] = True
            except Exception as error:
                row["ok"] = False
                row["error"] = str(error).splitlines()[0][:300]
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            rows.append(row)
        if a.restore:
            await provider._select_model(page, provider.model_spec(a.restore))
            rows.append({"id": a.restore, "restored": True})
    finally:
        await s.close()
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--only", action="append", default=None, help="glob model id (lặp được), mặc định mọi model")
    ap.add_argument("--state", help="biểu thức JS đọc trạng thái sau khi chọn model")
    ap.add_argument("--peek", help="action chạy trước --state (vd mở lại menu chứa slider)")
    ap.add_argument("--restore", help="model chọn lại ở cuối để trả account về chế độ mặc định")
    ap.add_argument("--mode", default="stealthy", choices=["stealthy", "dynamic"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--wait-ms", type=int, default=5000)
    args = ap.parse_args()
    args.only = args.only or ["*"]
    sys.stdout.reconfigure(encoding="utf-8")
    result = asyncio.run(main(args))
    for r in result:
        if r.get("restored"):
            print(f"(đã đặt lại {r['id']})")
        else:
            print(f"{r['id']:<28} {str(r.get('variant') or '-'):<10} "
                  f"{json.dumps(r.get('state'), ensure_ascii=False):<20} "
                  f"{'OK' if r['ok'] else 'LỖI: ' + r.get('error', '')}")
