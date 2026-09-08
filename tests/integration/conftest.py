import http.server
import socketserver
import threading
from functools import partial
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


UNSAFE_PORTS = {
    1,7,9,11,13,15,17,19,20,21,22,23,25,37,42,43,53,77,79,87,95,101,102,103,104,
    109,110,111,113,115,117,119,123,135,139,143,179,389,465,512,513,514,515,526,530,531,532,540,556,
    587,601,636,989,1000,1067,1068,1069,1085,1719,1720,1723,2049,3659,4045,5060,5061,6000,6566,6665,6666,6667,6668,6669,6697,10080,
}

@pytest.fixture
def site():
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    for _ in range(20):
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler, bind_and_activate=False)
        httpd.allow_reuse_address = True
        httpd.server_bind()
        port = httpd.server_address[1]
        if port in UNSAFE_PORTS:
            httpd.server_close()
            continue
        httpd.server_activate()
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            httpd.shutdown()
            httpd.server_close()
        return
    # fallback: use whatever port (let Chromium flag allow it)
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{port}"
        httpd.shutdown()


@pytest.fixture
def fixture_recipe(site):
    return {
        "slug": "fixture",
        "url": f"{site}/chat.html",
        "prompt": {"input_selector": "#prompt", "input_mode": "fill", "submit": "click:#send"},
        "response": {
            "last_message_selector": ".msg",
            "done_signal": {"type": "stable_text", "quiet_ms": 400, "timeout_ms": 8000},
        },
        "models": [{"id": "fixture-web"}],
        # Bỏ delay mặc định để test không phải chờ thật; test riêng kiểm delay.
        "timing": {"ready_delay_ms": 0, "input_delay_ms": 0},
    }

@pytest.fixture
async def app_client(tmp_path, site):
    from httpx import ASGITransport, AsyncClient

    from chat2api.config import Config
    from chat2api.main import create_app
    from chat2api.providers.base import ModelInfo, Provider

    class FakeProvider(Provider):
        slug = "fake"

        def models(self):
            return [ModelInfo(id="fake/m1", slug="fake")]

        async def stream(self, messages, model_id):
            for word in ("Hello ", "world"):
                yield word

    cfg = Config()
    cfg.agent_llm_base_url = ""
    cfg.agent_llm_api_key = ""
    cfg.agent_llm_model = ""
    cfg.recipes_dir = tmp_path / "recipes"
    cfg.recipes_dir.mkdir()
    cfg.flows_dir = tmp_path / "flows"
    cfg.flows_dir.mkdir()
    app = create_app(cfg)
    app.state.router.providers["fake"] = FakeProvider()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client