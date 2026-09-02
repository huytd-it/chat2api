import time

import pytest

from chat2api.browserpool import BrowserPool
from chat2api.providers.browser_recipe import (
    DEFAULT_COPY_BUTTON_SELECTOR,
    BrowserRecipe,
    TrialLimitExceeded,
    discover_models,
    validate_recipe,
)

pytest.importorskip("playwright.async_api")


async def _record_drop(dropped, key):
    dropped.append(key)


async def test_roundtrip_stream(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        assert "".join(out).strip() == "This is the reply."
    finally:
        await pool.aclose()


async def test_reply_preserves_markdown_block_structure(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe, "response": {
        **fixture_recipe["response"], "last_message_selector": ".qwen-markdown",
        "format": "markdown",
    }}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        context = await pool.context_for("markdown")
        page = await context.new_page()
        await page.set_content("""
          <div class="qwen-markdown">
            <div class="qwen-markdown-paragraph"><span>Đoạn một.</span></div>
            <div class="qwen-markdown-space"></div>
            <div class="qwen-markdown-paragraph"><span>Đoạn hai.</span></div>
            <div class="qwen-markdown-hr"><hr></div>
            <div class="qwen-markdown-paragraph"><strong>GLOSSARY</strong></div>
            <ul><li>秦老板: Chủ tiệm họ Tần</li><li>警服: đồng phục cảnh sát</li></ul>
          </div>
        """)

        text, html = await provider._reply(page)

        assert text == (
            "Đoạn một.\n\nĐoạn hai.\n\n---\n\n**GLOSSARY**\n\n"
            "- 秦老板: Chủ tiệm họ Tần\n- 警服: đồng phục cảnh sát"
        )
        assert html is None
    finally:
        await pool.aclose()


def _copy_button_recipe(fixture_recipe, **ds):
    return {**fixture_recipe, "response": {
        **fixture_recipe["response"],
        "done_signal": {"type": "copy_button", "quiet_ms": 300, "timeout_ms": 8000, **ds},
    }}


async def test_copy_button_done_signal_waits_for_the_button(fixture_recipe, tmp_path):
    recipe = _copy_button_recipe(fixture_recipe)
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        # Nút copy chỉ gắn vào khi fixture viết xong câu cuối, nên chốt sớm là
        # sẽ thiếu chữ.
        assert "".join(out).strip() == "This is the reply."
    finally:
        await pool.aclose()


async def test_discover_and_select_model_before_prompt(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe({**fixture_recipe, "models": [
            {"id": "fast", "action": "select:#model", "value": "fast-v1"},
            {"id": "max", "action": "select:#model", "value": "max-v2"},
        ]}, tmp_path, pool)
        context = await pool.context_for("discover")
        page = await context.new_page()
        await page.goto(fixture_recipe["url"])
        found = await discover_models(page)
        assert [(item["id"], item["value"]) for item in found] == [
            ("fast-v1", "fast-v1"), ("max-v2", "max-v2")]

        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "max"):
            out.append(delta)
        assert "".join(out).strip() == "This is the max reply."
    finally:
        await pool.aclose()


async def test_copy_button_can_return_the_clipboard_result(fixture_recipe, tmp_path):
    recipe = _copy_button_recipe(fixture_recipe, use_copy_result=True)
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        assert "".join(out).strip() == "This is the copied reply."
    finally:
        await pool.aclose()


async def test_copy_button_falls_back_to_stable_text_when_selector_never_matches(
        fixture_recipe, tmp_path):
    recipe = _copy_button_recipe(
        fixture_recipe, selector="button.khong-bao-gio-co", fallback_quiet_ms=400)
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        assert "".join(out).strip() == "This is the reply."
    finally:
        await pool.aclose()


async def test_copy_button_ignores_button_of_earlier_message(fixture_recipe, tmp_path):
    """Nút copy của lượt TRƯỚC không được tính là lượt này đã xong."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        context = await pool.context_for("copy-scope")
        page = await context.new_page()
        await page.set_content("""
          <div class="msg">Câu trả lời cũ.</div>
          <div><button aria-label="Copy">Copy</button></div>
          <div class="msg">Câu trả lời đang</div>
        """)
        sel = DEFAULT_COPY_BUTTON_SELECTOR
        assert await provider._copy_button_ready(page, sel, "after", "") is False

        await page.evaluate("""() => {
          const bar = document.createElement("div");
          bar.innerHTML = '<button aria-label="Copy">Copy</button>';
          document.querySelectorAll(".msg")[1].after(bar);
        }""")
        assert await provider._copy_button_ready(page, sel, "after", "") is True
    finally:
        await pool.aclose()


async def test_copy_button_ignores_code_block_copy_button(fixture_recipe, tmp_path):
    """Nút "Copy code" mọc lên ngay khi code block bắt đầu stream, chưa phải xong."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        context = await pool.context_for("copy-code")
        page = await context.new_page()
        await page.set_content("""
          <div class="msg">
            <div><button aria-label="Copy code">Copy code</button></div>
            <pre><code>print("dang stream")</code></pre>
          </div>
        """)
        sel = DEFAULT_COPY_BUTTON_SELECTOR
        assert await provider._copy_button_ready(page, sel, "after", "") is False

        await page.evaluate("""() => {
          const bar = document.createElement("div");
          bar.innerHTML = '<button aria-label="Copy">Copy</button>';
          document.querySelector(".msg").after(bar);
        }""")
        assert await provider._copy_button_ready(page, sel, "after", "") is True
    finally:
        await pool.aclose()


async def test_copy_button_result_uses_last_button_after_reply(fixture_recipe, tmp_path):
    """Thanh thao tác có nhiều nút copy thì lấy nút cuối cùng của reply hiện tại."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        context = await pool.context_for("copy-last")
        page = await context.new_page()
        await page.goto(fixture_recipe["url"])
        await page.set_content("""
          <div class="msg">Câu trả lời mới.</div>
          <div>
            <button aria-label="Copy" onclick="navigator.clipboard.writeText('first')">Copy</button>
            <button aria-label="Copy" onclick="navigator.clipboard.writeText('last')">Copy</button>
          </div>
        """)
        copied = await provider._copy_button_result(
            page, DEFAULT_COPY_BUTTON_SELECTOR, "after", "")
        assert copied == "last"
    finally:
        await pool.aclose()


async def test_multi_account_round_robin_uses_distinct_contexts(fixture_recipe, tmp_path, monkeypatch):
    for name in ("a1", "a2"):
        (tmp_path / f"{name}.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    recipe = {**fixture_recipe, "login": {
        "strategy": "round_robin",
        "accounts": [
            {"name": "a1", "storage_state": "a1.json"},
            {"name": "a2", "storage_state": "a2.json"},
        ],
    }}
    pool = BrowserPool(max_contexts=3)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None, headed=False):
        calls.append(key)
        return await original(key, storage_state, headed=headed)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert calls == ["fixture::a1", "fixture::a2", "fixture::a1"]
    finally:
        await pool.aclose()


async def test_multi_account_fill_first_exhausts_quota_before_switching(fixture_recipe, tmp_path,
                                                                         monkeypatch):
    for name in ("a1", "a2"):
        (tmp_path / f"{name}.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    recipe = {**fixture_recipe, "login": {
        "strategy": "fill_first",
        "quota": 2,
        "accounts": [
            {"name": "a1", "storage_state": "a1.json"},
            {"name": "a2", "storage_state": "a2.json"},
        ],
    }}
    pool = BrowserPool(max_contexts=3)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None, headed=False):
        calls.append(key)
        return await original(key, storage_state, headed=headed)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert calls == ["fixture::a1", "fixture::a1", "fixture::a2"]
    finally:
        await pool.aclose()


async def test_headed_flag_propagates_to_pool_context_for(fixture_recipe, tmp_path, monkeypatch):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None, headed=False):
        calls.append(headed)
        # Ghi lại cờ headed nhưng vẫn chạy context thật ở chế độ headless để
        # test không tự mở cửa sổ Chromium hiện ra.
        return await original(key, storage_state, headed=False)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool, headed=True)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        assert calls == [True]
    finally:
        await pool.aclose()


async def test_per_call_headed_overrides_constructor_default(fixture_recipe, tmp_path, monkeypatch):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    calls = []
    original = pool.context_for

    async def spy(key, storage_state=None, headed=False):
        calls.append(headed)
        return await original(key, storage_state, headed=False)

    monkeypatch.setattr(pool, "context_for", spy)
    try:
        # Provider mặc định headless (như mọi recipe production), nhưng một
        # request cụ thể có thể yêu cầu hiện browser qua tham số stream().
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool, headed=False)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web",
                                            headed=True):
            pass
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        assert calls == [True, False]
    finally:
        await pool.aclose()


async def test_anon_trial_limit_blocks_after_quota(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe, "login": {"anon_trial_limit": 2}}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        assert provider.account_count == 0
        for _ in range(2):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
        assert provider.trial_status == {"limit": 2, "used": 2}
        with pytest.raises(TrialLimitExceeded):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
    finally:
        await pool.aclose()


async def test_accounts_disable_anon_trial_limit(fixture_recipe, tmp_path):
    (tmp_path / "a1.json").write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    recipe = {**fixture_recipe, "login": {
        "anon_trial_limit": 1,
        "accounts": [{"name": "a1", "storage_state": "a1.json"}],
    }}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        assert provider.account_count == 1
        assert provider.trial_status is None
        for _ in range(3):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
    finally:
        await pool.aclose()


def test_validate_recipe_rejects_bad_anon_trial_limit(fixture_recipe):
    bad = {**fixture_recipe, "login": {"anon_trial_limit": -1}}
    errs = validate_recipe(bad)
    assert any("anon_trial_limit" in e for e in errs)


async def test_roundtrip_timeout(fixture_recipe, tmp_path):
    bad = {**fixture_recipe, "response": {**fixture_recipe["response"],
           "last_message_selector": ".does-not-exist",
           "done_signal": {**fixture_recipe["response"]["done_signal"], "timeout_ms": 2000}}}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(bad, tmp_path, pool)
        with pytest.raises(TimeoutError):
            async for _ in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
                pass
    finally:
        await pool.aclose()


async def test_context_kept_alive_across_streams_by_default(fixture_recipe, tmp_path, monkeypatch):
    """Browser được duy trì giữa các request để khỏi mở lại + đăng nhập lại."""
    pool = BrowserPool(max_contexts=3)
    await pool.start()
    dropped = []
    monkeypatch.setattr(pool, "drop", lambda key: _record_drop(dropped, key))
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        for _ in range(2):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}],
                                                "fixture-web"):
                pass
        assert dropped == []
    finally:
        await pool.aclose()


async def test_keep_context_false_drops_context_after_each_stream(fixture_recipe, tmp_path,
                                                                  monkeypatch):
    recipe = {**fixture_recipe, "keep_context": False}
    pool = BrowserPool(max_contexts=3)
    await pool.start()
    dropped = []
    monkeypatch.setattr(pool, "drop", lambda key: _record_drop(dropped, key))
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        for _ in range(2):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}],
                                                "fixture-web"):
                pass
        assert dropped == ["fixture", "fixture"]
    finally:
        await pool.aclose()


async def test_page_stays_open_after_stream_completes(fixture_recipe, tmp_path):
    """Trả lời xong browser phải còn nguyên — chỉ người dùng mới được tắt."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        page = provider._pages["fixture"]
        assert not page.is_closed()
        assert len(pool._contexts["fixture"].pages) == 1
    finally:
        await pool.aclose()


async def test_second_request_reuses_same_page(fixture_recipe, tmp_path):
    """Không mở tab mới mỗi request, tránh rò tab khi browser sống lâu."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        pages = []
        for _ in range(2):
            async for _delta in provider.stream([{"role": "user", "content": "hi"}],
                                                "fixture-web"):
                pass
            pages.append(provider._pages["fixture"])
        assert pages[0] is pages[1]
        assert len(pool._contexts["fixture"].pages) == 1
    finally:
        await pool.aclose()


async def test_close_browser_is_the_manual_off_switch(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        page = provider._pages["fixture"]
        assert await provider.close_browser() == 1
        assert page.is_closed()
        assert "fixture" not in pool._contexts
    finally:
        await pool.aclose()


async def test_stream_recovers_after_user_closes_page(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(fixture_recipe, tmp_path, pool)
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        await provider._pages["fixture"].close()
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        assert "".join(out).strip() == "This is the reply."
    finally:
        await pool.aclose()


async def test_new_chat_selector_starts_fresh_session(fixture_recipe, tmp_path):
    """Context được tái sử dụng nên mỗi request phải tự mở phiên chat mới."""
    recipe = {**fixture_recipe, "new_chat": {"selector": "#new-chat"}}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        out = []
        async for delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            out.append(delta)
        assert "".join(out).strip() == "This is the reply."
    finally:
        await pool.aclose()


async def test_timing_delays_applied_before_typing(fixture_recipe, tmp_path):
    recipe = {**fixture_recipe, "timing": {"ready_delay_ms": 300, "input_delay_ms": 300}}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        started = time.monotonic()
        async for _delta in provider.stream([{"role": "user", "content": "hi"}], "fixture-web"):
            pass
        assert time.monotonic() - started >= 0.6
    finally:
        await pool.aclose()


async def test_timing_defaults_come_from_env(fixture_recipe, tmp_path, monkeypatch):
    monkeypatch.setenv("RECIPE_READY_DELAY_MS", "250")
    monkeypatch.setenv("RECIPE_INPUT_DELAY_MS", "150")
    recipe = {k: v for k, v in fixture_recipe.items() if k != "timing"}
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        assert (provider._ready_delay_ms, provider._input_delay_ms) == (250, 150)
    finally:
        await pool.aclose()


# ---------------------------------------------------------------- flow video
# Flow video dùng chung khung với flow ảnh nhưng đọc `<video>`: URL thật hay
# nằm ở `<source>` con hoặc data-src chứ không phải `video.src`, và không được
# chờ video tải xong (file rất nặng) — có metadata là đủ.

def _video_recipe(fixture_recipe):
    return {
        **fixture_recipe,
        "flows": {
            "select_model": {"selector": "#model-btn", "action": "click:#model-btn"},
            "text": {"prompt": fixture_recipe["prompt"],
                     "response": fixture_recipe["response"]},
            "video": {
                "action": "click:#tab-video",
                "prompt": fixture_recipe["prompt"],
                "response": {"video_selector": "video.result",
                             "done_signal": {"type": "stable_text", "timeout_ms": 8000}},
            },
        },
        "models": [{"id": "fixture-web"}, {"id": "fixture-vid", "capability": "video"}],
    }


async def test_video_flow_is_declared_separately_from_the_chat_flow(fixture_recipe, tmp_path):
    provider = BrowserRecipe(_video_recipe(fixture_recipe), tmp_path, None)

    assert provider.supported_flows() == ["select_model", "text", "video"]
    assert provider.supports_video() and not provider.supports_image()
    # Flow video có selector riêng, không mượn last_message_selector của chat.
    assert provider.flow_response("video")["media_selector"] == "video.result"
    assert provider.flow_response("text")["last_message_selector"] == ".msg"
    # Luồng chat cũ vẫn nguyên vẹn.
    assert provider.prompt_cfg["input_selector"] == "#prompt"


async def test_a_recipe_without_a_video_flow_refuses_video_requests(fixture_recipe, tmp_path):
    provider = BrowserRecipe(fixture_recipe, tmp_path, None)

    assert not provider.supports_video()
    with pytest.raises(NotImplementedError):
        await provider.generate_videos("a cat")


async def test_video_srcs_are_read_from_source_children_and_data_src(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(_video_recipe(fixture_recipe), tmp_path, pool)
        context = await pool.context_for("video")
        page = await context.new_page()
        await page.set_content("""
          <div class="result-wrap">
            <video class="result"><source src="https://cdn.tld/a.mp4"></video>
            <video class="result" data-src="https://cdn.tld/b.mp4"></video>
          </div>
        """)

        srcs = await provider._extract_media_srcs(page, 4, "video")

        assert srcs == ["https://cdn.tld/a.mp4", "https://cdn.tld/b.mp4"]
    finally:
        await pool.aclose()


async def test_video_flow_does_not_pick_up_images_from_the_same_page(fixture_recipe, tmp_path):
    """Nhiều trang tạo video kèm ảnh thumbnail; lấy nhầm là API trả ra ảnh."""
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(_video_recipe(fixture_recipe), tmp_path, pool)
        context = await pool.context_for("video-mixed")
        page = await context.new_page()
        await page.set_content("""
          <div class="result-wrap">
            <img src="https://cdn.tld/thumb.png">
            <video class="result"><source src="https://cdn.tld/clip.mp4"></video>
          </div>
        """)

        srcs = await provider._extract_media_srcs(page, 4, "video")

        assert srcs == ["https://cdn.tld/clip.mp4"]
    finally:
        await pool.aclose()


async def test_waiting_for_video_accepts_metadata_without_a_full_download(fixture_recipe, tmp_path):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(_video_recipe(fixture_recipe), tmp_path, pool)
        context = await pool.context_for("video-wait")
        page = await context.new_page()
        # `readyState` là 0 (chưa tải gì) nhưng đã có src — đủ để trả kết quả,
        # nếu không mọi request video đều chạy tới timeout.
        await page.set_content('<video class="result" src="https://cdn.tld/clip.mp4"></video>')

        srcs = await provider._wait_for_media(page, 1, time.monotonic() + 5, "video")

        assert srcs == ["https://cdn.tld/clip.mp4"]
    finally:
        await pool.aclose()
