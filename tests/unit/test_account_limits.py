"""Phat hien account limit theo tung site/recipe + cooldown tam.

Khong mo Chromium: detector/retry/condition deu test duoc o muc logic
(regex, validate, assign skip, stream retry, node condition) voi _run gia lap.
"""

import types

import pytest
import yaml

from chat2api import account_limits as limits
from chat2api import store
from chat2api.flow_executor import FlowContext
from chat2api.providers.browser_recipe import (
    AccountLimitExceeded,
    BrowserRecipe,
    account_key_of,
)

QWEN_SAMPLE = (
    "You've reached today's Qwen3.8-Max limit. "
    "Upgrade your membership or switch to another model above to continue."
)


@pytest.fixture
def db(tmp_path):
    s = store.connect(tmp_path / "chat2api.db")
    s.migrate()
    try:
        yield s
    finally:
        limits.reset_memory()
        store.shutdown()


@pytest.fixture(autouse=True)
def _file_strategy(monkeypatch):
    # Di duong file .accounts/ thay vi DB de khong can profile Chromium.
    monkeypatch.setenv("API_ACCOUNT_STRATEGY", "off")


def _recipe(**over):
    base = {
        "slug": "lim",
        "url": "https://chat.qwen.ai/",
        "prompt": {"input_selector": "#p"},
        "response": {
            "last_message_selector": ".m",
            "done_signal": {"type": "stable_text"},
            "limit_patterns": ["reached.+limit", "quota exceeded"],
            "limit_cooldown_hours": 24,
        },
        "models": [{"id": "max"}],
        "login": {
            "accounts": [
                {"name": "a1", "storage_state": "auth/a1.json"},
                {"name": "a2", "storage_state": "auth/a2.json"},
            ]
        },
    }
    base.update(over)
    return base


@pytest.fixture
def recipe(tmp_path):
    return BrowserRecipe(_recipe(), tmp_path / "recipes" / "lim", None,
                         accounts_root=tmp_path / "recipes")


# ------------------------------------------------------------- detector


def test_limit_regex_case_insensitive():
    compiled = limits.compile_patterns(["reached.+limit"])
    assert limits.match_limit(QWEN_SAMPLE, compiled)
    assert limits.match_limit("YOU'VE REACHED TODAY'S QWEN LIMIT", compiled)
    assert limits.match_limit("Everything is fine.", compiled) is None


def test_limit_disabled_when_no_patterns():
    assert limits.match_limit(QWEN_SAMPLE, []) is None
    cfg = limits.limit_config({})
    assert cfg["patterns"] == [] and cfg["compiled"] == []
    assert cfg["cooldown_hours"] == limits.DEFAULT_COOLDOWN_HOURS
    assert cfg["on_missing_copy"] is False


def test_validate_limit_fields():
    assert limits.validate_limit_fields({}, "response") == []
    assert limits.validate_limit_fields({"limit_patterns": []}, "response") == []
    ok = {"limit_patterns": ["a.+b"], "limit_cooldown_hours": 12,
          "limit_on_missing_copy": True}
    assert limits.validate_limit_fields(ok, "response") == []
    assert limits.validate_limit_fields({"limit_patterns": ["(unclosed"]},
                                        "response")
    assert limits.validate_limit_fields({"limit_patterns": "not-a-list"},
                                        "response")
    assert limits.validate_limit_fields({"limit_patterns": [""]}, "response")
    assert limits.validate_limit_fields({"limit_cooldown_hours": -1}, "response")
    assert limits.validate_limit_fields({"limit_cooldown_hours": "nhieu"},
                                        "response")
    assert limits.validate_limit_fields({"limit_on_missing_copy": "yes"},
                                        "response")


def test_validate_recipe_limit_config(tmp_path):
    from chat2api.providers.browser_recipe import validate_recipe

    minimal = {
        "slug": "x", "url": "https://x.example",
        "prompt": {"input_selector": "textarea"},
        "response": {"last_message_selector": ".m",
                     "done_signal": {"type": "stable_text"}},
        "models": [{"id": "x-web"}],
    }
    assert validate_recipe(minimal) == []
    good = {**minimal, "response": {**minimal["response"],
            "limit_patterns": ["reached.+limit"],
            "limit_cooldown_hours": 24, "limit_on_missing_copy": True}}
    assert validate_recipe(good) == []
    bad = {**minimal, "response": {**minimal["response"],
           "limit_patterns": ["(hong"]}}
    assert any("limit_patterns" in e for e in validate_recipe(bad))
    bad_flow = {**good, "flows": {"text": {
        "prompt": {"input_selector": "t"},
        "response": {"last_message_selector": ".m",
                     "limit_patterns": ["(hong"]}}}}
    assert any("limit_patterns" in e for e in validate_recipe(bad_flow))


# ------------------------------------------------------------- cooldown store


def test_migration_creates_cooldown_table(db):
    names = {r["name"] for r in db.query(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "account_cooldown" in names


def test_cooldown_mark_list_clear(db):
    assert limits.is_cooled_down("lim", "db:1") == (False, 0, "")
    until = limits.mark_cooldown("lim", "db:1", 24, "reached limit")
    assert until > 0
    # Mirror in-memory thay ngay, khong cho writer flush.
    hit, got, _ = limits.is_cooled_down("lim", "db:1")
    assert hit and got == until
    db.flush()
    rows = limits.list_cooldowns("lim")
    assert [r["account_key"] for r in rows] == ["db:1"]
    assert rows[0]["retry_after"] > 0
    limits.clear_cooldown("lim", "db:1")
    db.flush()
    assert limits.is_cooled_down("lim", "db:1") == (False, 0, "")
    assert limits.list_cooldowns("lim") == []


def test_cooldown_expired_row_lazy_expires(db):
    db.submit("INSERT INTO account_cooldown(recipe_slug, account_key, until_ms,"
              " reason, updated_at) VALUES ('lim', 'db:9', 1, 'cu', 1)")
    db.flush()
    assert limits.is_cooled_down("lim", "db:9") == (False, 0, "")


def test_anon_never_cooled(db):
    assert limits.mark_cooldown("lim", "__anon__", 24, "x") == 0
    assert limits.is_cooled_down("lim", "__anon__") == (False, 0, "")


def test_account_key_shapes():
    assert limits.db_key(7) == "db:7"
    assert limits.file_key("Chat.Qwen.AI", "a1") == "file:chat.qwen.ai/a1"
    fake_db = types.SimpleNamespace(account_id=3, account_label="x", host="h")
    assert account_key_of(fake_db) == "db:3"
    fake_file = types.SimpleNamespace(account_id=None, account_label="a1",
                                      host="chat.qwen.ai")
    assert account_key_of(fake_file) == "file:chat.qwen.ai/a1"
    fake_anon = types.SimpleNamespace(account_id=None, account_label="",
                                      host="chat.qwen.ai")
    assert account_key_of(fake_anon) == "__anon__"


# ------------------------------------------------------------- assign skip


async def test_assign_skips_cooled_file_account(db, recipe):
    first = await recipe.assign()
    assert account_key_of(first) == "file:chat.qwen.ai/a1"
    first.release()
    limits.mark_cooldown("lim", "file:chat.qwen.ai/a1", 24, "reached limit")
    second = await recipe.assign()
    try:
        assert account_key_of(second) == "file:chat.qwen.ai/a2"
    finally:
        second.release()


async def test_assign_exhausted_raises_without_browser(db, recipe):
    limits.mark_cooldown("lim", "file:chat.qwen.ai/a1", 24, "x")
    limits.mark_cooldown("lim", "file:chat.qwen.ai/a2", 24, "x")
    with pytest.raises(AccountLimitExceeded) as exc:
        await recipe.assign()
    assert exc.value.retry_after >= 0
    assert exc.value.recipe_slug == "lim"


async def test_rotator_exclude_set(db, recipe):
    name, _ = await recipe._rotator.next(exclude={"file:chat.qwen.ai/a1"})
    assert name == "a2"
    with pytest.raises(AccountLimitExceeded):
        await recipe._rotator.next(
            exclude={"file:chat.qwen.ai/a1", "file:chat.qwen.ai/a2"})


# ------------------------------------------------------------- retry trong stream


async def test_stream_retries_next_account_once(db, recipe, monkeypatch):
    seen: list[str] = []

    async def fake_run(self, prompt, model_id, assignment, headed, flow="text"):
        seen.append(account_key_of(assignment))
        if len(seen) == 1:
            raise self._record_limit_hit("reached limit", assignment, flow)
        yield "real answer"

    monkeypatch.setattr(BrowserRecipe, "_run", fake_run)
    out = [d async for d in recipe.stream(
        [{"role": "user", "content": "hi"}], "max")]
    assert "".join(out) == "real answer"
    assert seen == ["file:chat.qwen.ai/a1", "file:chat.qwen.ai/a2"]
    hit, _, _ = limits.is_cooled_down("lim", "file:chat.qwen.ai/a1")
    assert hit


async def test_stream_pinned_does_not_retry(db, recipe, monkeypatch):
    holder = await recipe.assign()
    calls: list = []

    async def fake_assign(self, account_id=None, sticky_key="", exclude=None):
        calls.append((account_id, exclude))
        return holder

    async def boom(self, prompt, model_id, assignment, headed, flow="text"):
        raise self._record_limit_hit("reached limit", assignment, flow)
        yield  # khong bao gio toi: chi de thanh async generator nhu _run that

    monkeypatch.setattr(BrowserRecipe, "assign", fake_assign)
    monkeypatch.setattr(BrowserRecipe, "_run", boom)
    try:
        with pytest.raises(AccountLimitExceeded):
            async for _ in recipe.stream(
                    [{"role": "user", "content": "hi"}], "max",
                    target_account_id=7):
                pass
        assert len(calls) == 1
    finally:
        holder.release()


# ------------------------------------------------------------- node condition


def _limit_flow(slug: str = "limflow") -> dict:
    def node(nid, ntype, params=None, x=0):
        out = {"id": nid, "type": ntype, "position": {"x": x, "y": 0}}
        if params:
            out["params"] = params
        return out

    nodes = [
        node("start", "start"),
        node("goto", "goto-url", {"url": "https://chat.qwen.ai/"}),
        node("fill", "fill-input", {"selector": "#p"}),
        node("sub", "submit-enter"),
        node("wait", "wait-done-signal",
             {"type": "stable_text", "limit_patterns": ["reached.+limit"]}),
        node("ext", "extract-text", {"selector": ".m"}),
        node("cond", "condition", {"check": "limit"}),
        node("out", "output"),
    ]
    edges = [{"source": nodes[i]["id"], "target": nodes[i + 1]["id"],
              "id": f"e{i}"} for i in range(len(nodes) - 1)]
    return {"slug": slug, "kind": "text", "flow_type": "text",
            "capability": "chat", "model": {"id": "m"},
            "nodes": nodes, "edges": edges}


def test_flow_condition_validate_and_compile(tmp_path):
    from chat2api.flow_store import validate_flow

    flow = _limit_flow()
    assert validate_flow(flow) == []
    bad = _limit_flow()
    bad["nodes"][6] = {"id": "cond", "type": "condition",
                       "position": {"x": 0, "y": 0},
                       "params": {"expression": "(hong"}}
    # Bieu thuc thuong van cho qua (khong phai limit); thieu han moi loi.
    assert validate_flow(bad) == []
    empty = _limit_flow()
    empty["nodes"][6] = {"id": "cond", "type": "condition",
                         "position": {"x": 0, "y": 0}, "params": {}}
    assert any("expression" in e for e in validate_flow(empty))


def test_flow_converter_inserts_limit_condition(tmp_path):
    from chat2api.flow_converter import convert_recipe

    flows = convert_recipe(_recipe())
    assert flows, "recipe co limit phai convert duoc"
    conds = [n for n in flows[0]["nodes"]
             if n.get("type") == "condition"
             and (n.get("params") or {}).get("check") == "limit"]
    assert len(conds) == 1
    plain = {k: v for k, v in _recipe().items()}
    plain["response"] = {k: v for k, v in plain["response"].items()
                         if not k.startswith("limit_")}
    no_limit = convert_recipe(plain)
    assert not [n for n in no_limit[0]["nodes"] if n.get("type") == "condition"]


async def test_node_condition_limit_true_false(db, tmp_path):
    from chat2api.providers.flow_runner import FlowRunner

    runner = FlowRunner(_limit_flow(), tmp_path / "flows", None,
                        accounts_root=tmp_path / "recipes")
    assert runner._flow_limit_cfg()["patterns"] == ["reached.+limit"]
    assign = types.SimpleNamespace(account_id=None, account_label="a1",
                                   host="chat.qwen.ai")
    ctx = FlowContext("hi")
    ctx.assignment = assign
    ctx.text = "cau tra loi binh thuong"
    assert await runner._node_condition(ctx, {"check": "limit"}) is False
    assert await runner._node_condition(ctx, {"expression": "limit"}) is False
    ctx.text = QWEN_SAMPLE
    with pytest.raises(AccountLimitExceeded):
        await runner._node_condition(ctx, {"check": "limit"})
    hit, _, _ = limits.is_cooled_down("limflow", "file:chat.qwen.ai/a1")
    assert hit


# ------------------------------------------------------------- seed Qwen


def test_qwen_seed_recipe_matches_sample():
    from pathlib import Path

    from chat2api.providers.browser_recipe import validate_recipe

    path = Path(__file__).resolve().parents[2] / "recipes" / "qwen-web" / "recipe.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert validate_recipe(data) == []
    cfg = limits.limit_config(data.get("response") or {})
    assert cfg["patterns"], "qwen-web phai seed san limit_patterns"
    assert limits.match_limit(QWEN_SAMPLE, cfg["compiled"])
    assert cfg["on_missing_copy"] is True
