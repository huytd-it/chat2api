from types import SimpleNamespace

import pytest

from chat2api import store
from chat2api.automation.websites import normalize_domain
from chat2api.automation.website_cli import run


@pytest.mark.parametrize(("value", "expected"), [
    (" Chat.Example.COM ", "https://chat.example.com"),
    ("https://chat.example.com:443/", "https://chat.example.com"),
    ("bücher.example", "https://xn--bcher-kva.example"),
])
def test_normalize_domain(value, expected):
    assert normalize_domain(value) == expected


def test_cli_registers_domain_and_reopens_the_same_database(tmp_path, capsys):
    cfg = SimpleNamespace(db_path=tmp_path / "cli.db")
    assert run(cfg, SimpleNamespace(website_action="add", domain="cli.example")) == 0
    assert '"created": true' in capsys.readouterr().out
    assert store.default() is None
    assert run(cfg, SimpleNamespace(website_action="list")) == 0
    assert "https://cli.example" in capsys.readouterr().out
    assert store.default() is None


def test_cli_brief_does_not_create_a_database_or_execute_an_agent(tmp_path, capsys):
    cfg = SimpleNamespace(db_path=tmp_path / "never-created.db")
    assert run(cfg, SimpleNamespace(website_action="brief", domain="cli.example", request="Bật Thinking")) == 0
    brief = capsys.readouterr().out
    assert "Bật Thinking" in brief
    assert "https://cli.example" in brief
    assert not cfg.db_path.exists()


def test_main_routes_website_subcommand_to_the_brief(monkeypatch, tmp_path, capsys):
    import chat2api.config
    from chat2api.__main__ import main
    monkeypatch.setattr(chat2api.config, "Config", lambda: SimpleNamespace(db_path=tmp_path / "unused.db"))
    assert main(["website", "brief", "cli.example", "--request", "Tạo ảnh"]) == 0
    assert "Tạo ảnh" in capsys.readouterr().out
