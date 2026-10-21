"""New module contract: no BrowserRecipe/flow dependency or live browser."""
import asyncio
from dataclasses import replace

import pytest

from chat2api.automation.contracts import (
    BrowserReply, BrowserTurn, CapabilityEvidence, Operation, Phase,
    SiteManifest, SiteModel, Support,
)
from chat2api.automation.registry import SiteRegistry, builtin_registry
from chat2api.automation.runtime import TurnExecutionError, execute_turn


def test_builtin_identities_preserve_public_models():
    registry = builtin_registry()
    assert {s.id for s in registry.all()} == {
        "qwen", "chatgpt", "deepseek", "gemini", "grok", "kimi", "dola", "tencent", "zai", "minimax"}
    assert registry.get("qwen").public_model_ids == (
        "qwen-web/qwen3.7-plus", "qwen-web/qwen3.8-max", "qwen-web/image", "qwen-web/qwen-web")
    assert registry.get("gemini").public_model_ids == ("gemini-web/gemini-web",)
    assert registry.for_slug("chat-z-ai").id == "zai"


def test_minimax_is_registered_without_invented_capabilities_or_models():
    registry = builtin_registry()
    site = registry.get("minimax")
    assert registry.for_url("https://agent.minimax.io/") is site
    assert registry.for_slug("minimax-agent") is site
    assert site.public_model_ids == ()
    assert site.operations == frozenset()
    assert registry.for_url("https://api.minimax.io/") is None
    assert registry.for_url("https://agent.minimax.io.evil.test/") is None
    assert registry.for_url("https://user@agent.minimax.io/") is None


def test_unprobed_manifest_cannot_advertise_an_executable_operation():
    with pytest.raises(ValueError, match="distinct model IDs"):
        replace(builtin_registry().get("minimax"), operations=frozenset({Operation.CHAT}))


@pytest.mark.parametrize("url", [
    "http://chat.qwen.ai/c/1", "https://chat.qwen.ai.evil.test/c/1",
    "https://chat.qwen.ai@evil.test/c/1", "https://user:secret@chat.qwen.ai/c/1",
    "https://chat.qwen.ai:8443/c/1", "//chat.qwen.ai/c/1", "javascript:alert(1)",
    "https://chat.qwen.ai:invalid/c/1", "https://[invalid/",
])
def test_registry_rejects_unsafe_destinations(url):
    assert builtin_registry().for_url(url) is None


def test_registry_accepts_real_site_urls_without_query_identity_changes():
    registry = builtin_registry()
    assert registry.for_url("https://chat.qwen.ai/c/1?x=1").id == "qwen"
    assert registry.for_url("https://chatgpt.com/g/g-p-1/project").id == "chatgpt"


def test_duplicate_and_ambiguous_module_identity_is_explicit():
    site = builtin_registry().get("qwen")
    with pytest.raises(ValueError, match="Duplicate"):
        SiteRegistry([site, site])
    registry = SiteRegistry([site, replace(site, id="copy", slug="copy")])
    with pytest.raises(ValueError, match="more than one"):
        registry.for_url(site.origin)


def test_manifest_is_not_evidence_of_account_capability():
    assert CapabilityEvidence(34, Operation.PROJECTS).state == Support.UNKNOWN
    with pytest.raises(ValueError, match="timestamp"):
        CapabilityEvidence(34, Operation.PROJECTS, Support.SUPPORTED)
    evidence = CapabilityEvidence(34, Operation.PROJECTS, Support.SUPPORTED, 123, "live_probe")
    assert evidence.account_id == 34
    with pytest.raises(ValueError, match="persisted account"):
        CapabilityEvidence(0, Operation.CHAT)


def test_invalid_models_cannot_enter_manifest():
    with pytest.raises(ValueError, match="local ID"):
        SiteModel("site/model", "Model")
    with pytest.raises(ValueError, match="distinct"):
        replace(builtin_registry().get("qwen"), models=())
    with pytest.raises(ValueError, match="not declared"):
        SiteManifest("a", "a", "A", "https://a.test", ("a.test",),
                     (SiteModel("image", "Image", Operation.IMAGES),))


class FakeDriver:
    manifest = builtin_registry().get("qwen")

    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at

    async def record(self, step):
        self.calls.append(step)
        if self.fail_at == step:
            raise RuntimeError("fake failure")

    async def open_chat(self, page, turn):
        await self.record("open")

    async def choose_model(self, page, model_id):
        await self.record("model")

    async def set_thinking(self, page, enabled):
        await self.record("thinking")

    async def fill_prompt(self, page, prompt):
        await self.record("fill")

    async def submit(self, page):
        await self.record("submit")

    async def await_reply(self, page):
        await self.record("reply")
        return BrowserReply("done", "https://chat.qwen.ai/c/1")


async def test_runtime_marks_journal_before_submit_and_never_replays_history():
    driver = FakeDriver()
    phases = []

    async def journal():
        driver.calls.append("journal")

    reply = await execute_turn(driver, object(), BrowserTurn("qwen3.7-plus", "new", thinking=False),
                               before_submit=journal, observe=phases.append)
    assert driver.calls == ["open", "model", "thinking", "fill", "journal", "submit", "reply"]
    assert reply.text == "done"
    assert phases == [Phase.OPENING, Phase.READY, Phase.SUBMITTING,
                      Phase.AWAITING_RESULT, Phase.COMPLETED]


@pytest.mark.parametrize("step,phase", [
    ("open", Phase.FAILED), ("model", Phase.FAILED), ("thinking", Phase.FAILED),
    ("fill", Phase.FAILED), ("submit", Phase.UNCERTAIN), ("reply", Phase.UNCERTAIN),
])
async def test_runtime_failure_does_not_retry(step, phase):
    driver = FakeDriver(step)
    phases = []

    async def journal():
        driver.calls.append("journal")

    with pytest.raises(RuntimeError):
        await execute_turn(driver, None, BrowserTurn("qwen3.7-plus", "new", thinking=True),
                           before_submit=journal, observe=phases.append)
    assert phases[-1] == phase
    assert driver.calls.count("submit") <= 1


async def test_journal_failure_prevents_remote_submit():
    driver = FakeDriver()
    phases = []

    async def broken_journal():
        raise OSError("database unavailable")

    with pytest.raises(OSError):
        await execute_turn(driver, None, BrowserTurn("qwen3.7-plus", "new"),
                           before_submit=broken_journal, observe=phases.append)
    assert "submit" not in driver.calls
    assert phases[-1] == Phase.FAILED


async def test_cancellation_after_submit_is_uncertain():
    driver = FakeDriver()
    phases = []

    async def journal():
        pass

    async def cancelled(page):
        raise asyncio.CancelledError()

    driver.submit = cancelled
    with pytest.raises(asyncio.CancelledError):
        await execute_turn(driver, None, BrowserTurn("qwen3.7-plus", "new"),
                           before_submit=journal, observe=phases.append)
    assert phases[-1] == Phase.UNCERTAIN


async def test_preflight_rejects_unknown_operations_without_opening_browser():
    driver = FakeDriver()
    driver.manifest = builtin_registry().get("kimi")

    async def journal():
        pytest.fail("must not journal invalid request")

    with pytest.raises(TurnExecutionError, match="resume"):
        await execute_turn(driver, None, BrowserTurn("default", "new", "https://www.kimi.ai/chat/1"),
                           before_submit=journal)
    assert driver.calls == []


async def test_telemetry_exception_does_not_lose_completed_result():
    driver = FakeDriver()

    async def journal():
        pass

    def observer(phase):
        raise RuntimeError("observer unavailable")

    result = await execute_turn(driver, None, BrowserTurn("qwen3.7-plus", "new"),
                                before_submit=journal, observe=observer)
    assert result.text == "done"


async def test_deadline_after_submission_is_uncertain_without_retry():
    driver = FakeDriver()
    phases = []

    async def journal():
        pass

    async def wait_forever(page):
        await asyncio.Future()

    driver.await_reply = wait_forever
    with pytest.raises(TimeoutError):
        await execute_turn(driver, None, BrowserTurn("qwen3.7-plus", "new"),
                           before_submit=journal, observe=phases.append,
                           timeout_seconds=0.05)
    assert phases[-1] == Phase.UNCERTAIN
    assert driver.calls.count("submit") == 1


def test_adapter_boundary_uses_site_packages_not_duplicate_implementations():
    from chat2api.automation.adapters import adapter_for
    from chat2api.automation.sites.chatgpt.controls import ChatGPTAdapter
    from chat2api.automation.sites.qwen.controls import QwenAdapter
    assert type(adapter_for("https://chat.qwen.ai/")) is QwenAdapter
    assert type(adapter_for("https://chatgpt.com/")) is ChatGPTAdapter


class ToggleButton:
    def __init__(self, pressed, disabled=False):
        self.pressed = pressed
        self.disabled = disabled
        self.clicks = 0

    @property
    def first(self):
        return self

    async def count(self):
        return 1

    async def is_visible(self):
        return True

    async def is_disabled(self):
        return self.disabled

    async def get_attribute(self, name):
        assert name == "aria-pressed"
        return "true" if self.pressed else "false"

    async def click(self):
        self.clicks += 1
        self.pressed = not self.pressed


class TogglePage:
    def __init__(self, button):
        self.button = button

    def get_by_role(self, role, *, name, exact):
        assert (role, name, exact) == ("button", "Think", True)
        return self.button


@pytest.mark.parametrize("initial,desired,clicks", [
    (False, True, 1), (True, False, 1), (True, True, 0), (False, False, 0),
])
async def test_migrated_chatgpt_think_sets_explicit_state(initial, desired, clicks):
    from chat2api.automation.sites.chatgpt.controls import ChatGPTAdapter
    button = ToggleButton(initial)
    await ChatGPTAdapter("https://chatgpt.com").thinking(TogglePage(button), desired)
    assert button.pressed is desired
    assert button.clicks == clicks


async def test_migrated_chatgpt_disabled_think_never_clicks():
    from chat2api.automation.sites.chatgpt.controls import ChatGPTAdapter
    from chat2api.errors import OpenAIError
    button = ToggleButton(False, disabled=True)
    with pytest.raises(OpenAIError) as caught:
        await ChatGPTAdapter("https://chatgpt.com").thinking(TogglePage(button), True)
    assert caught.value.code == "thinking_unavailable"
    assert button.clicks == 0


@pytest.mark.parametrize("url", [
    "https://user@chatgpt.com/c/1", "https://chatgpt.com:8443/c/1",
    "https://evil.test/c/1", "http://chatgpt.com/c/1", "https://chatgpt.com/",
])
def test_migrated_chatgpt_controls_reject_unowned_conversation_urls(url):
    from chat2api.automation.sites.chatgpt.controls import ChatGPTAdapter
    from chat2api.errors import OpenAIError
    with pytest.raises(OpenAIError):
        ChatGPTAdapter("https://chatgpt.com").validate_conversation(url)


def test_new_module_layers_do_not_import_the_legacy_execution_engine():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "chat2api" / "automation"
    files = [root / name for name in ("contracts.py", "registry.py", "runtime.py")]
    files.extend((root / "sites").rglob("*.py"))
    banned = {"browser_recipe", "flow_runner", "flow_compiler", "flow_executor", "flow_converter", "yaml"}
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imports = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            assert not any(set(name.split(".")) & banned for name in imports), path
