import pytest

from chat2api.attachments import Attachment
from chat2api.browserpool import BrowserPool
from chat2api.errors import OpenAIError
from chat2api.providers.browser_recipe import BrowserRecipe

pytest.importorskip("playwright.async_api")


def _recipe(fixture_recipe, site, page="attach.html", **prompt):
    return {**fixture_recipe, "url": f"{site}/{page}",
            "prompt": {**fixture_recipe["prompt"], "attach_wait_ms": 0, **prompt}}


def _message(*files):
    return [{"role": "user", "content": "xem file", "attachments": list(files)}]


NOTE = Attachment("note.txt", "text/plain", b"hello")
DATA = Attachment("data.csv", "text/csv", b"a,b")


async def _ask(recipe, tmp_path, messages):
    pool = BrowserPool(max_contexts=1)
    await pool.start()
    try:
        provider = BrowserRecipe(recipe, tmp_path, pool)
        return "".join([d async for d in provider.stream(messages, "fixture-web")]).strip()
    finally:
        await pool.aclose()


async def test_uploads_through_hidden_file_input(fixture_recipe, site, tmp_path):
    recipe = _recipe(fixture_recipe, site, attach_selector="#file",
                     attach_ready_selector=".chip")
    reply = await _ask(recipe, tmp_path, _message(NOTE, DATA))
    assert reply == "files=note.txt|text/plain|5|hello;data.csv|text/csv|3|a,b text=User: xem file"


async def test_finds_file_input_without_selector(fixture_recipe, site, tmp_path):
    reply = await _ask(_recipe(fixture_recipe, site), tmp_path, _message(NOTE))
    assert reply.startswith("files=note.txt|text/plain|5|hello ")


async def test_button_selector_goes_through_file_chooser(fixture_recipe, site, tmp_path):
    recipe = _recipe(fixture_recipe, site, attach_selector="#clip")
    reply = await _ask(recipe, tmp_path, _message(NOTE, DATA))
    assert reply.startswith("files=note.txt|text/plain|5|hello;data.csv|text/csv|3|a,b ")


async def test_single_file_input_takes_files_one_by_one(fixture_recipe, site, tmp_path):
    recipe = _recipe(fixture_recipe, site, attach_selector="#single")
    reply = await _ask(recipe, tmp_path, _message(NOTE, DATA))
    assert reply.startswith("files=note.txt|text/plain|5|hello;data.csv|text/csv|3|a,b ")


async def test_page_without_upload_reports_unsupported(fixture_recipe, site, tmp_path):
    recipe = _recipe(fixture_recipe, site, page="chat.html")
    with pytest.raises(OpenAIError) as caught:
        await _ask(recipe, tmp_path, _message(NOTE))
    assert caught.value.code == "attachments_unsupported"
    assert caught.value.status == 400
