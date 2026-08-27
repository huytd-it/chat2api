from types import SimpleNamespace

from chat2api.agents import model_discovery


def test_models_normalizes_and_filters_agent_output():
    data = {"models": [
        {"id": "GPT 4o", "label": "GPT-4o", "action": "click:#gpt"},
        {"id": "claude", "label": "Claude", "action": "select:#model", "value": "c3"},
        {"id": "broken", "label": "Broken", "action": "select:#model"},
        {"id": "GPT 4o", "label": "Duplicate", "action": "click:#duplicate"},
    ]}

    assert model_discovery._models(data, "click:#picker") == [
        {"id": "gpt-4o", "label": "GPT-4o", "action": "click:#picker;click:#gpt"},
        {"id": "claude", "label": "Claude", "action": "select:#model", "value": "c3"},
    ]


async def test_discover_uses_agent_models(monkeypatch):
    page = SimpleNamespace(url="https://chat.example")

    async def snapshot(_page):
        return "button label=Choose engine sel=#picker"

    async def chat_json(_cfg, _system, user, timeout):
        assert "#picker" in user
        assert timeout == 90
        return {"open_action": None, "models": [
            {"id": "alpha", "label": "Alpha", "action": "click:#alpha"}
        ]}

    async def deterministic(_page, before_action=""):
        return []

    monkeypatch.setattr(model_discovery.dom, "snapshot", snapshot)
    monkeypatch.setattr(model_discovery.llm, "chat_json", chat_json)
    monkeypatch.setattr("chat2api.providers.browser_recipe.discover_models", deterministic)

    assert await model_discovery.discover(page, object()) == [
        {"id": "alpha", "label": "Alpha", "action": "click:#alpha"}
    ]
