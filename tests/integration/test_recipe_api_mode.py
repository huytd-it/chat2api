import json

import pytest

from chat2api.browserpool import BrowserPool
from chat2api.providers import api_mode
from chat2api.providers.browser_recipe import BrowserRecipe, validate_recipe

pytest.importorskip("playwright.async_api")


def _api_recipe(site):
    return {
        "slug": "fixture-api",
        "url": f"{site}/chat.html",
        "models": [{"id": "fixture-web", "api_model": "m-123"}],
        "timing": {"ready_delay_ms": 0, "input_delay_ms": 0},
        "api": {
            "timeout_ms": 8000,
            "send": {"url": "/api/send.json", "method": "GET", "save": {"task_id": "data.id"}},
            "poll": {"url": "/api/task-{{task_id}}.json", "interval_ms": 50,
                     "done": {"path": "data.status", "equals": "done"}},
            "result": "data.content",
        },
    }


def test_api_only_recipe_needs_no_selectors(site):
    assert validate_recipe(_api_recipe(site)) == []


def test_validate_api_rejects_bad_blocks():
    errs = api_mode.validate_api({"send": {"method": "FOO"}, "poll": {"url": "/x", "done": {}}})
    assert "missing/invalid field: api.send.url" in errs
    assert any("api.poll.done" in e for e in errs)


def test_get_path():
    data = {"a": [{"b": 1}, {"b": 2}]}
    assert api_mode.get_path(data, "a.-1.b") == 2
    assert api_mode.get_path(data, "a.5.b") is None
    assert api_mode.get_path(data, "") is data


async def test_stream_uses_send_then_poll(site, tmp_path):
    pool = BrowserPool(mode="stealthy", max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(_api_recipe(site), tmp_path, pool)
        out = [d async for d in provider.stream([{"role": "user", "content": "hi"}], "fixture-web")]
        assert "".join(out) == "Câu trả lời qua API."
    finally:
        await pool.aclose()


async def test_run_fills_templates_and_polls_until_done(site):
    pool = BrowserPool(mode="stealthy", max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("api-mode")
        page = await ctx.new_page()
        seen = {"send": None, "polls": 0}

        async def on_send(route):
            req = route.request
            seen["send"] = {"body": json.loads(req.post_data), "auth": req.headers.get("authorization")}
            await route.fulfill(json={"id": "abc"})

        async def on_poll(route):
            seen["polls"] += 1
            body = ({"state": "running"} if seen["polls"] < 2
                    else {"state": "ok", "msg": {"text": "xong"}})
            await route.fulfill(json=body)

        await page.route("**/v1/send", on_send)
        await page.route("**/v1/poll/abc", on_poll)
        await page.goto(f"{site}/chat.html")
        await page.evaluate("localStorage.setItem('token', 'tk1')")
        cfg = {
            "send": {"url": "/v1/send", "headers": {"Authorization": "Bearer {{ls:token}}"},
                     "body": {"q": "{{prompt}}", "model": "{{model}}", "n": "{{now}}"},
                     "save": {"id": "id"}},
            "poll": {"url": "/v1/poll/{{id}}", "interval_ms": 20,
                     "done": {"path": "state", "equals": "ok"},
                     "fail": {"path": "state", "equals": ["failed"]}},
            "result": "msg.text",
        }
        import time
        text = await api_mode.run(page, cfg, {"prompt": 'a "quoted"\nline', "model": "m", "now": 7},
                                  time.monotonic() + 5)
        assert text == "xong"
        assert seen["send"] == {"body": {"q": 'a "quoted"\nline', "model": "m", "n": 7},
                                "auth": "Bearer tk1"}
        assert seen["polls"] == 2
    finally:
        await pool.aclose()


async def test_run_raises_on_http_error(site):
    pool = BrowserPool(mode="stealthy", max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("api-err")
        page = await ctx.new_page()
        await page.route("**/v1/send", lambda r: r.fulfill(status=429, body="rate limited"))
        await page.goto(f"{site}/chat.html")
        import time
        with pytest.raises(api_mode.ApiCallError, match="429") as info:
            await api_mode.run(page, {"send": {"url": "/v1/send"}}, {}, time.monotonic() + 5)
        assert info.value.body == "rate limited"
    finally:
        await pool.aclose()


def test_poll_only_recipe_keeps_input_but_drops_reply_selectors(fixture_recipe):
    recipe = {k: v for k, v in fixture_recipe.items() if k != "response"}
    recipe["api"] = {"poll": {"url": "/x"}, "result": "a"}
    assert validate_recipe(recipe) == []
    no_input = {**recipe, "prompt": {}}
    assert "missing/invalid field: prompt.input_selector" in validate_recipe(no_input)


def test_url_vars():
    api = {"url_vars": {"chat_id": r"/c/([0-9a-f-]+)"}}
    assert api_mode.url_vars(api, "https://x/c/ab-12?x=1") == {"chat_id": "ab-12"}
    assert api_mode.url_vars(api, "https://x/") is None
    assert api_mode.validate_api({"poll": {"url": "/x"}, "url_vars": {"a": "no-group"}})


async def test_stream_types_prompt_then_reads_reply_from_api(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe, "api": {
        "poll": {"url": "/api/task-t1.json", "interval_ms": 50,
                 "done": {"path": "data.status", "equals": "done"}},
        "result": "data.content",
    }}
    pool = BrowserPool(mode="stealthy", max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        out = [d async for d in provider.stream([{"role": "user", "content": "hi"}], "fixture-web")]
        assert "".join(out) == "Câu trả lời qua API."
    finally:
        await pool.aclose()


async def test_poll_result_skips_previous_answer(site):
    pool = BrowserPool(mode="stealthy", max_contexts=1)
    await pool.start()
    try:
        ctx = await pool.context_for("api-fresh")
        page = await ctx.new_page()
        calls = {"n": 0}

        async def on_poll(route):
            calls["n"] += 1
            last = ({"id": "old", "done": True, "text": "cũ"} if calls["n"] < 3
                    else {"id": "new", "done": True, "text": "mới"})
            await route.fulfill(json={"messages": [last]})

        await page.route("**/v2/chats/c42", on_poll)
        await page.goto(f"{site}/chat.html?c=c42")
        api = {
            "url_vars": {"cid": r"[?&]c=(\w+)"},
            "poll": {"url": "/v2/chats/{{cid}}", "interval_ms": 20, "fresh": "messages.-1.id",
                     "done": {"path": "messages.-1.done", "equals": True}},
            "result": "messages.-1.text",
        }
        found = api_mode.url_vars(api, page.url)
        baseline = await api_mode.snapshot(page, api, found)
        assert baseline == "old"
        import time
        text = await api_mode.poll_result(page, api, {}, time.monotonic() + 5, baseline)
        assert text == "mới"
    finally:
        await pool.aclose()


async def test_slider_step_sets_level_by_label(fixture_recipe, tmp_path):
    pool = BrowserPool(mode="stealthy", max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        ctx = await pool.context_for("slider")
        page = await ctx.new_page()
        # Trang about:blank mới mở không nhận phím; trang thật luôn đã điều hướng.
        await page.goto(fixture_recipe["url"])
        await page.set_content("""
          <div id="s" role="slider" tabindex="0" aria-label="Effort" style="width:80px;height:12px"
               aria-valuemin="0" aria-valuemax="2" aria-valuenow="2" aria-valuetext="Max"></div>
""")
        await page.evaluate("""() => {
            const s = document.getElementById('s'), names = ['Low', 'High', 'Max'];
            s.addEventListener('keydown', e => {
              let v = +s.getAttribute('aria-valuenow');
              if (e.key === 'Home') v = 0; else if (e.key === 'End') v = 2;
              else if (e.key === 'ArrowRight') v = Math.min(2, v + 1);
              s.setAttribute('aria-valuenow', v); s.setAttribute('aria-valuetext', names[v]);
            });
        }""")
        await provider._exec_action_steps(page, 'slider:#s=High')
        assert await page.get_attribute("#s", "aria-valuetext") == "High"
        from chat2api.errors import OpenAIError
        with pytest.raises(OpenAIError, match="Ultra"):
            await provider._exec_action_steps(page, "slider:#s=Ultra")
    finally:
        await pool.aclose()
