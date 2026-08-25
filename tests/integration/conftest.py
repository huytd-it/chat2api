import http.server
import socketserver
import threading
from functools import partial
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def site():
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
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
    app = create_app(cfg)
    app.state.router.providers["fake"] = FakeProvider()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        yield client