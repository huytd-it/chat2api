"""`tailscale serve --tcp` — không gọi CLI thật, chỉ kiểm lệnh dựng ra và cách
đọc JSON trả về."""

import json
import subprocess

import pytest

from chat2api import tailscale

NODE = {"BackendState": "Running",
        "Self": {"TailscaleIPs": ["100.64.0.7", "fd7a::7"], "DNSName": "box.tail.ts.net."}}


@pytest.fixture
def cli(monkeypatch):
    """CLI giả: giữ cấu hình serve trong bộ nhớ, ghi lại mọi lệnh đã chạy."""
    state = {"serve": {}, "node": NODE, "calls": []}

    def fake_run(argv, **kwargs):
        args = argv[1:]
        state["calls"].append(args)
        out, code, err = "", 0, ""
        if args == ["status", "--json"]:
            out = json.dumps(state["node"])
        elif args == ["serve", "status", "--json"]:
            out = json.dumps(state["serve"])
        elif args[:3] == ["serve", "--bg", "--tcp"]:
            state["serve"].setdefault("TCP", {})[args[3]] = {
                "TCPForward": args[4].removeprefix("tcp://")}
        elif args[:2] == ["serve", "--tcp"] and args[-1] == "off":
            state["serve"].get("TCP", {}).pop(args[2], None)
        else:
            code, err = 1, "unknown"
        return subprocess.CompletedProcess(argv, code, out, err)

    monkeypatch.setattr(tailscale, "find_cli", lambda: "tailscale")
    monkeypatch.setattr(tailscale.subprocess, "run", fake_run)
    return state


def test_status_not_installed(monkeypatch):
    monkeypatch.setattr(tailscale, "find_cli", lambda: None)
    status = tailscale.status(8100)
    assert status["installed"] is False and status["open"] is False
    with pytest.raises(tailscale.TailscaleError):
        tailscale.open_tcp(8100)


def test_open_then_close(cli):
    assert tailscale.status(8100)["open"] is False
    status = tailscale.open_tcp(8100)
    assert ["serve", "--bg", "--tcp", "8100", "tcp://127.0.0.1:8100"] in cli["calls"]
    assert status["open"] is True and status["target"] == "127.0.0.1:8100"
    # IPv4 và tên MagicDNS; IPv6 không đưa vào URL.
    assert status["urls"] == ["http://100.64.0.7:8100", "http://box.tail.ts.net:8100"]
    assert tailscale.close_tcp(8100)["open"] is False
    assert ["serve", "--tcp", "8100", "off"] in cli["calls"]


def test_close_when_already_closed_skips_cli(cli):
    assert tailscale.close_tcp(8100)["open"] is False
    assert not any(call[-1:] == ["off"] for call in cli["calls"])


def test_other_port_and_web_handler_are_not_ours(cli):
    cli["serve"] = {"TCP": {"443": {"HTTPS": True}, "9000": {"TCPForward": "127.0.0.1:9000"}}}
    assert tailscale.status(8100)["open"] is False
    assert tailscale.status(443)["open"] is False


def test_stopped_backend_reports_state(cli):
    cli["node"] = {"BackendState": "Stopped", "Self": {}}
    status = tailscale.status(8100)
    assert status["running"] is False and status["state"] == "Stopped"
    assert ["serve", "status", "--json"] not in cli["calls"]


def test_cli_failure_surfaces_message(cli, monkeypatch):
    monkeypatch.setattr(tailscale.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 1, "", "serve is not enabled on your tailnet"))
    with pytest.raises(tailscale.TailscaleError, match="not enabled"):
        tailscale.open_tcp(8100)
    assert "not enabled" in tailscale.status(8100)["error"]


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_rejects_bad_port(cli, port):
    with pytest.raises(tailscale.TailscaleError):
        tailscale.open_tcp(port)
