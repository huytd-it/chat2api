"""Dò danh sách model + điều khiển chế độ (thinking/fast/effort...) của một web chat.

CHỈ ĐỌC: mở menu, đọc DOM, không gõ prompt, không gửi tin. Riêng `--levels`
có kéo thanh trượt để đọc tên từng mức rồi đặt lại mức cũ.

Chạy từ gốc repo (cần profile Chromium đã đăng nhập site):

    uv run python skills/model-variants/scripts/probe_controls.py --profiles chat.z.ai
    uv run python skills/model-variants/scripts/probe_controls.py \
        --profile codex001 --url https://chat.z.ai/ \
        --open 'click:[aria-label="Select a model"]' \
        --each-model 'click:[aria-label="model-item"][data-value="{value}"]' \
        --reopen 'click:[aria-label="Select a model"]' --levels --out probe.json

    # Menu chế độ riêng (vd Qwen): bấm control rồi liệt kê menuitem
    uv run python skills/model-variants/scripts/probe_controls.py \
        --profile codex07 --url https://chat.qwen.ai/ --menu .qwen-thinking-selector

Profile đang bị app chiếm (`lock_pid`) thì không mở được — chọn profile khác
hoặc tắt app.
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

# Đọc mọi control có thể là "chế độ": slider ARIA, switch, radio, menuitem*,
# option, và nút có chữ gợi ý thinking/fast/effort/reason/search/deep.
READ_JS = r"""() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 100);
  const attrs = el => Object.fromEntries([...el.attributes]
    .filter(a => /^(id|class|role|aria-|data-)/.test(a.name)).map(a => [a.name, a.value.slice(0, 80)]));
  const pick = sel => [...document.querySelectorAll(sel)].filter(vis);
  return {
    sliders: pick('[role="slider"]').map(el => ({label: el.getAttribute('aria-label'),
      min: el.getAttribute('aria-valuemin'), max: el.getAttribute('aria-valuemax'),
      now: el.getAttribute('aria-valuenow'), text: el.getAttribute('aria-valuetext'), attrs: attrs(el)})),
    toggles: pick('[role="switch"],[role="radio"],[role="menuitemradio"],[role="menuitemcheckbox"],[aria-pressed]')
      .map(el => ({text: txt(el), checked: el.getAttribute('aria-checked') ?? el.getAttribute('aria-pressed'), attrs: attrs(el)})),
    menuitems: pick('[role="menuitem"]').map(el => ({text: txt(el), attrs: attrs(el)})),
    options: pick('[role="option"],[aria-label="model-item"],[data-model],[data-model-id]')
      .map(el => ({text: txt(el), attrs: attrs(el)})),
    hint_buttons: pick('button,[role="button"]')
      .filter(el => /think|fast|effort|reason|deep|search|mode|auto/i.test(txt(el) + ' ' + (el.getAttribute('aria-label') || '') + ' ' + el.className))
      .map(el => ({text: txt(el), attrs: attrs(el)})),
  };
}"""


def list_profiles(host: str) -> list[dict]:
    db = sqlite3.connect("data/chat2api.db")
    rows = db.execute(
        "SELECT p.name, p.scrapling_mode, p.lock_pid, a.status FROM account a "
        "JOIN domain d ON d.id = a.domain_id LEFT JOIN profile p ON p.id = a.profile_id "
        "WHERE d.host = ? AND a.disabled = 0", (host,)).fetchall()
    return [{"profile": r[0], "mode": r[1], "locked_by_pid": r[2], "status": r[3]} for r in rows]


async def main(a) -> dict:
    from chat2api.browserpool import open_session
    from chat2api.providers.browser_recipe import BrowserRecipe

    # Provider tối giản chỉ để mượn bộ chạy bước action (click/press/slider...).
    runner = BrowserRecipe({"slug": "probe", "url": a.url, "models": [{"id": "x"}],
                            "prompt": {"input_selector": "body"},
                            "response": {"last_message_selector": "body",
                                         "done_signal": {"type": "stable_text"}}},
                           Path("."), None)
    s = await open_session(a.mode, headless=not a.headed, user_data_dir=f"data/profiles/{a.profile}")
    out: dict = {"url": a.url, "profile": a.profile}
    try:
        page = s.context.pages[0] if s.context.pages else await s.context.new_page()
        await page.goto(a.url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(a.wait_ms)
        await page.keyboard.press("Escape")  # popup quảng cáo/onboarding
        await page.wait_for_timeout(500)
        out["page"] = await page.evaluate(READ_JS)
        if a.open:
            await runner._exec_action_steps(page, a.open)
            await page.wait_for_timeout(800)
            out["opened"] = await page.evaluate(READ_JS)
            from chat2api.providers.browser_recipe import discover_models
            found = await discover_models(page)
            if not found:
                # discover_models chỉ nhận role=option/data-model/select; site
                # khác (z.ai: [aria-label="model-item"][data-value]) đọc từ options.
                for o in out["opened"]["options"]:
                    at = o["attrs"]
                    value = at.get("data-value") or at.get("data-model-id") or at.get("data-model")
                    if value or o["text"]:
                        found.append({"id": str(value or o["text"]).lower().replace(" ", "-"),
                                      "label": o["text"], "value": value})
            out["discovered_models"] = found
            await page.keyboard.press("Escape")
        if a.menu:
            await runner._exec_action_steps(page, f"click:{a.menu}")
            await page.wait_for_timeout(700)
            out["menu"] = (await page.evaluate(READ_JS))["menuitems"]
            await page.keyboard.press("Escape")
        if a.each_model and out.get("discovered_models"):
            per = {}
            for m in out["discovered_models"]:
                key = m.get("value") or m["id"]
                pick = a.each_model.format(value=key, label=m["label"])
                # Đưa về trạng thái menu ĐÓNG hẳn (chờ hết hiệu ứng) rồi mới mở:
                # bấm `--open` lúc menu còn mở/đang đóng sẽ đảo trạng thái.
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(800)
                await runner._exec_action_steps(page, a.open)
                await page.wait_for_timeout(600)
                await runner._exec_action_steps(page, pick)
                await page.wait_for_timeout(800)
                if a.reopen:
                    await runner._exec_action_steps(page, a.reopen)
                    await page.wait_for_timeout(600)
                state = await page.evaluate(READ_JS)
                if a.menu:
                    await page.keyboard.press("Escape")
                    await runner._exec_action_steps(page, f"click:{a.menu}")
                    await page.wait_for_timeout(600)
                    state["menu"] = (await page.evaluate(READ_JS))["menuitems"]
                if a.levels:
                    state["levels"] = await read_levels(page)
                per[key] = state
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(300)
            out["per_model"] = per
        elif a.levels:
            out["levels"] = await read_levels(page)
    finally:
        await s.close()
    return out


async def read_levels(page) -> dict:
    """Tên từng mức của mỗi slider đang hiện; đặt lại mức ban đầu sau khi đọc.

    Đọc qua `document.activeElement` thay vì locator: nhiều site dựng lại
    slider sau mỗi phím, locator cũ sẽ treo tới timeout.
    """
    state = """() => { const e = document.activeElement;
      return e && e.getAttribute('role') === 'slider' ? {now: e.getAttribute('aria-valuenow'),
        text: e.getAttribute('aria-valuetext'), min: e.getAttribute('aria-valuemin'),
        max: e.getAttribute('aria-valuemax')} : null; }"""
    res = {}
    sliders = page.locator('[role="slider"]')
    for i in range(await sliders.count()):
        sl = sliders.nth(i)
        if not await sl.is_visible():
            continue
        name = await sl.get_attribute("aria-label") or f"slider{i}"
        await sl.focus()
        first = await page.evaluate(state)
        if first is None:
            res[name] = "không focus được"
            continue
        await page.keyboard.press("Home")
        names = []
        for _ in range(int(first["max"] or 0) - int(first["min"] or 0) + 1):
            cur = await page.evaluate(state)
            if cur is None:
                names.append("<mất focus>")
                break
            names.append(cur["text"] or cur["now"])
            await page.keyboard.press("ArrowRight")
            await page.wait_for_timeout(150)
        await page.keyboard.press("Home")
        for _ in range(int(first["now"] or 0) - int(first["min"] or 0)):
            await page.keyboard.press("ArrowRight")
        res[name] = names
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", metavar="HOST", help="liệt kê profile đã đăng nhập HOST rồi thoát")
    ap.add_argument("--profile")
    ap.add_argument("--url")
    ap.add_argument("--mode", default="stealthy", choices=["stealthy", "dynamic"])
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--wait-ms", type=int, default=5000)
    ap.add_argument("--open", help="action mở menu model, vd 'click:[aria-label=\"Select a model\"]'")
    ap.add_argument("--each-model", help="action chọn từng model; {value} / {label} được thay")
    ap.add_argument("--reopen", help="action mở lại menu sau khi chọn model (menu tự đóng)")
    ap.add_argument("--menu", help="selector control chế độ cần bấm để liệt kê menuitem")
    ap.add_argument("--levels", action="store_true", help="đọc tên từng mức slider (có đặt lại)")
    ap.add_argument("--out", help="ghi JSON ra file (mặc định in ra stdout)")
    args = ap.parse_args()
    if args.profiles:
        result = list_profiles(args.profiles)
    else:
        if not (args.profile and args.url):
            ap.error("cần --profile và --url (hoặc --profiles HOST)")
        result = asyncio.run(main(args))
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
