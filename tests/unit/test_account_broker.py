import asyncio
import ast
import inspect
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from chat2api import profiles, store
from chat2api.automation import account_broker, account_errors, account_source, journal, runtime
from chat2api.automation.account_broker import AccountBroker
from chat2api.automation.account_errors import AccountLimitExceeded
from chat2api.automation.account_source import StorageAccountSource
from chat2api.automation.contracts import BrowserReply, BrowserTurn, Phase
from chat2api.automation.sites.qwen import MANIFEST
from chat2api.errors import OpenAIError


class Pool:
    def __init__(self):
        self.holds = 0
        self.page = object()

    def profile_headless(self, name):
        return False

    @asynccontextmanager
    async def hold(self, name, key):
        self.holds += 1
        try:
            yield
        finally:
            self.holds -= 1

    async def page_for(self, profile, key):
        return self.page


class Driver:
    manifest = MANIFEST

    def __init__(self, fail_after_submit=False):
        self.submits = 0
        self.fail_after_submit = fail_after_submit

    async def open_chat(self, page, turn): pass
    async def choose_model(self, page, model): pass
    async def set_thinking(self, page, enabled): pass
    async def fill_prompt(self, page, prompt): pass

    async def submit(self, page):
        self.submits += 1

    async def await_reply(self, page):
        if self.fail_after_submit:
            raise TimeoutError("website result unknown")
        return BrowserReply("new result", "https://chat.qwen.ai/c/new", "<p>new result</p>")


@pytest.fixture
def broker(tmp_path, monkeypatch):
    db = store.connect(tmp_path / "module.db")
    db.migrate()
    directory = tmp_path / "profiles"
    for name in ("first", "second"):
        profile = profiles.ensure_profile(name, directory)
        profiles.add_account(profile.id, "chat.qwen.ai", "main")
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "least_busy")
    source = StorageAccountSource([("__anon__", None)], "round_robin", 50)
    result = AccountBroker("qwen-web", "chat.qwen.ai", Pool(), source=source,
                           file_accounts=[("__anon__", None)], profiles_dir=directory)
    yield result
    store.shutdown()


async def test_broker_is_usable_without_recipe_and_reservations_spread(broker):
    first, second = await asyncio.gather(broker.assign(), broker.assign())
    assert {first.profile_name, second.profile_name} == {"first", "second"}
    assert broker.inflight() == 2
    first.release(); first.release(); second.release()
    assert broker.inflight() == 0


async def test_page_lease_rejects_released_and_foreign_reservations(broker):
    lease = await broker.assign()
    other = AccountBroker("other", "chat.qwen.ai", Pool(), source=broker._rotator,
                          file_accounts=broker._accounts, profiles_dir=broker._profiles_dir)
    try:
        with pytest.raises(ValueError):
            async with other.page_lease(lease): pass
    finally:
        lease.release()
    with pytest.raises(ValueError):
        async with broker.page_lease(lease): pass
    assert broker.pool.holds == 0


async def test_deadline_includes_waiting_for_the_reserved_tab(broker):
    lease = await broker.assign()
    lock = broker._lock_for(lease.ctx_key)
    await lock.acquire()
    driver = Driver()
    async def gate(): raise AssertionError("Must not submit while waiting for tab")
    try:
        with pytest.raises(TimeoutError):
            await runtime.execute_assigned_turn(driver, broker, lease, BrowserTurn("qwen-web", "prompt"),
                                                 before_submit=gate, timeout_seconds=0.01)
    finally:
        lock.release(); lease.release()
    assert driver.submits == 0
    assert broker.pool.holds == 0


async def test_module_turn_uses_existing_journal_and_request_local_output(broker):
    driver = Driver()
    lease = await broker.assign()
    journal.claim("book", "chunk", "qwen-web/qwen-web", "fingerprint")
    try:
        reply = await runtime.execute_journaled_turn(driver, broker, lease, BrowserTurn("qwen-web", "prompt"),
                                                     session_id="book", request_id="chunk")
        assert driver.submits == 1
        assert lease.html == reply.html and lease.conversation_url == reply.conversation_url
        assert journal.get_session("book")["account_id"] == lease.account_id
        journal.complete("book", "chunk", {"text": reply.text})
        assert journal.claim("book", "chunk", "qwen-web/qwen-web", "fingerprint").result == {"text": "new result"}
        assert journal.get_session("book")["successes"] == 1
    finally:
        lease.release()
    assert broker.pool.holds == 0 and broker.inflight() == 0


async def test_no_prepared_claim_means_zero_website_submits(broker):
    lease = await broker.assign()
    driver = Driver()
    try:
        with pytest.raises(OpenAIError):
            await runtime.execute_journaled_turn(driver, broker, lease, BrowserTurn("qwen-web", "prompt"),
                                                 session_id="missing", request_id="missing")
    finally:
        lease.release()
    assert driver.submits == 0
    assert broker.pool.holds == 0


async def test_post_submit_failure_stays_uncertain_without_resending(broker):
    lease = await broker.assign()
    driver = Driver(fail_after_submit=True)
    journal.claim("book", "chunk", "qwen-web/qwen-web", "fingerprint")
    phases = []
    try:
        with pytest.raises(TimeoutError):
            await runtime.execute_journaled_turn(driver, broker, lease, BrowserTurn("qwen-web", "prompt"),
                                                 session_id="book", request_id="chunk", observe=phases.append)
        journal.fail("book", "chunk", "unknown")
        with pytest.raises(OpenAIError) as unresolved:
            journal.claim("book", "chunk", "qwen-web/qwen-web", "fingerprint")
        assert unresolved.value.code == "operation_unresolved"
    finally:
        lease.release()
    assert driver.submits == 1 and phases[-1] == Phase.UNCERTAIN
    assert journal.get_session("book")["successes"] == 0
    assert broker.pool.holds == 0


async def test_single_storage_account_does_not_ignore_exclusion():
    source = StorageAccountSource([("one", Path("state.json"))], "round_robin", 50, domain="chat.qwen.ai")
    with pytest.raises(AccountLimitExceeded):
        await source.next({"file:chat.qwen.ai/one"})


async def test_anonymous_usage_callback_failure_does_not_consume_a_turn():
    def fail(count):
        raise RuntimeError("usage store unavailable")
    source = StorageAccountSource([("__anon__", None)], "round_robin", 50,
                                   anon_trial_limit=1, usage_changed=fail)
    with pytest.raises(RuntimeError):
        await source.next()
    assert source.anon_uses == 0


def test_broker_source_and_executor_have_no_legacy_engine_imports():
    for module in (account_broker, account_source, account_errors, runtime):
        tree = ast.parse(inspect.getsource(module))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not [name for name in imports if any(old in name for old in ("browser_recipe", "flow_runner", "flow_executor", "flows"))]


def test_transitional_provider_no_longer_owns_a_second_account_implementation():
    from chat2api.providers.browser_recipe import BrowserRecipe
    for method in ("assign", "_reserve", "_unreserve", "resolve_target", "resolve_headed",
                   "open_profile_page", "_lock_for", "_pick_row", "_available_rows"):
        assert method not in BrowserRecipe.__dict__
        assert getattr(BrowserRecipe, method) is getattr(AccountBroker, method)
