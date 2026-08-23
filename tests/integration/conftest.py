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
    }
