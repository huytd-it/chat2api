## Commits
36675f8 feat: gemini native provider (StreamGenerate port)

## Stat
 chat2api/providers/gemini_native.py | 167 ++++++++++++++++++++++++++++++++++++
 chat2api/router.py                  |  14 +++
 recipes/gemini/config.yaml          |  13 +++
 tests/unit/test_gemini_native.py    |  48 +++++++++++
 4 files changed, 242 insertions(+)

## Diffdiff --git a/chat2api/providers/gemini_native.py b/chat2api/providers/gemini_native.py
new file mode 100644
index 0000000..541f24f
--- /dev/null
+++ b/chat2api/providers/gemini_native.py
@@ -0,0 +1,167 @@
+"""Gemini web StreamGenerate protocol ΓÇö port tß╗½ gemini-web2api."""
+import hashlib
+import json
+import re
+import time
+import urllib.parse
+import uuid
+from pathlib import Path
+from typing import AsyncIterator
+
+import httpx
+
+from ..prompt import flatten_messages
+from .base import ModelInfo, Provider
+
+BL = "boq_assistant-bard-web-server_20260218.00_p0"  # cß║¡p nhß║¡t khi Gemini ─æß╗òi "bl"
+
+
+def clean_text(text: str) -> str:
+    text = re.sub(
+        r"```(?:python|javascript|text)\?code_(?:reference|stdout)&code_event_index=\d+\n.*?```\n?",
+        "",
+        text,
+        flags=re.DOTALL,
+    )
+    text = re.sub(r"http://googleusercontent\.com/card_content/\d+\n?", "", text)
+    return text.strip()
+
+
+def make_sapisidhash(sapisid: str) -> str:
+    ts = int(time.time())
+    h = hashlib.sha1(f"{ts} {sapisid} https://gemini.google.com".encode()).hexdigest()
+    return f"SAPISIDHASH {ts}_{h}"
+
+
+def _inner_payload(prompt: str, model_id: int, think_mode: int) -> list:
+    inner = [None] * 102
+    inner[0] = [prompt, 0, None, None, None, None, 0]
+    inner[1] = ["en"]
+    inner[6] = [0]
+    inner[7] = 1
+    inner[10] = 1
+    inner[17] = [[think_mode]]
+    inner[27] = 1
+    inner[30] = [4]
+    inner[41] = [2]
+    inner[59] = str(uuid.uuid4())
+    inner[68] = 1
+    inner[79] = model_id
+    return inner
+
+
+def build_payload(prompt: str, model_id: int, think_mode: int) -> str:
+    outer = [None, json.dumps(_inner_payload(prompt, model_id, think_mode))]
+    return urllib.parse.urlencode({"f.req": json.dumps(outer)})
+
+
+def _extract_texts_from_line(line: str) -> list[str]:
+    if '"wrb.fr"' not in line or len(line) < 200:
+        return []
+    try:
+        # raw_decode, kh├┤ng phß║úi loads: d├▓ng Gemini c├│ thß╗â c├│ r├íc ph├¡a sau JSON
+        arr, _ = json.JSONDecoder().raw_decode(line)
+        inner_str = arr[0][2]
+        if not inner_str or len(inner_str) < 50:
+            return []
+        inner = json.loads(inner_str)
+        if not (isinstance(inner, list) and len(inner) > 4 and inner[4]):
+            return []
+        texts = []
+        for part in inner[4]:
+            if isinstance(part, list) and len(part) > 1 and part[1] and isinstance(part[1], list):
+                for t in part[1]:
+                    if isinstance(t, str) and t:
+                        texts.append(t)
+        return texts
+    except (json.JSONDecodeError, IndexError, TypeError):
+        return []
+
+
+def extract_response_text(raw: str) -> str:
+    bard_err = re.search(r"BardErrorInfo\s*\[(\d+)\]", raw)
+    if bard_err:
+        raise RuntimeError(f"Gemini upstream rejected request: BardErrorInfo [{bard_err.group(1)}]")
+    last = ""
+    for line in raw.split("\n"):
+        for t in _extract_texts_from_line(line):
+            if len(t) > len(last):
+                last = t
+    return clean_text(last)
+
+
+class GeminiNative(Provider):
+    def __init__(self, cfg: dict, base_dir: Path):
+        self.slug = cfg["slug"]
+        self._models_cfg = cfg["models"]
+        self.cookie_file = base_dir / cfg["cookie_file"] if cfg.get("cookie_file") else None
+        self.auth_user = cfg.get("auth_user")
+        self.temporary_chats = bool(cfg.get("temporary_chats", False))
+        self._client = None
+
+    def models(self) -> list[ModelInfo]:
+        ready = bool(self._load_cookie()[0])
+        return [ModelInfo(id=f"{self.slug}/{m['id']}", slug=self.slug, ready=ready) for m in self._models_cfg]
+
+    def _load_cookie(self) -> tuple[str, str]:
+        if not self.cookie_file or not self.cookie_file.exists():
+            return "", ""
+        content = self.cookie_file.read_text(encoding="utf-8").strip()
+        if content.startswith("{"):
+            data = json.loads(content)
+            return data.get("cookie", ""), data.get("sapisid", "")
+        pairs = dict(p.split("=", 1) for p in content.split("; ") if "=" in p)
+        return content, pairs.get("SAPISID", "")
+
+    def _prefix(self) -> str:
+        return f"/u/{self.auth_user}" if self.auth_user is not None else ""
+
+    def _headers(self) -> dict:
+        headers = {
+            "Content-Type": "application/x-www-form-urlencoded",
+            "Origin": "https://gemini.google.com",
+            "Referer": f"https://gemini.google.com{self._prefix()}/app",
+            "X-Same-Domain": "1",
+            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
+        }
+        if self.auth_user is not None:
+            headers["X-Goog-AuthUser"] = str(self.auth_user)
+        cookie, sapisid = self._load_cookie()
+        if cookie:
+            headers["Cookie"] = cookie
+        if sapisid:
+            headers["Authorization"] = make_sapisidhash(sapisid)
+        return headers
+
+    def _url(self) -> str:
+        reqid = int(time.time()) % 1000000
+        return (
+            f"https://gemini.google.com{self._prefix()}/_/BardChatUi/data/"
+            f"assistant.lamda.BardFrontendService/StreamGenerate?bl={BL}&hl=en&_reqid={reqid}&rt=c"
+        )
+
+    async def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
+        mi = next(m for m in self._models_cfg if m["id"] == model_id)
+        think = int(mi.get("think_mode") or 0)
+        body = build_payload(flatten_messages(messages), int(mi["model_id"]), think)
+        if not self._load_cookie()[0]:
+            raise RuntimeError("Cookie Gemini ch╞░a c├│ ΓÇö ─æiß╗ün cookie_file trong recipes/gemini/config.yaml")
+        if self._client is None:
+            self._client = httpx.AsyncClient(timeout=300)
+        emitted = ""
+        async with self._client.stream("POST", self._url(), content=body.encode(), headers=self._headers()) as resp:
+            resp.raise_for_status()
+            buf = ""
+            async for chunk in resp.aiter_text():
+                buf += chunk
+                while "\n" in buf:
+                    line, buf = buf.split("\n", 1)
+                    for t in _extract_texts_from_line(line):
+                        if t == emitted or emitted.startswith(t):
+                            continue
+                        if not t.startswith(emitted):
+                            continue
+                        delta = t[len(emitted):]
+                        emitted = t
+                        if delta.strip():
+                            yield delta
diff --git a/chat2api/router.py b/chat2api/router.py
index ce87959..81ff6e5 100644
--- a/chat2api/router.py
+++ b/chat2api/router.py
@@ -50,10 +50,24 @@ class Router:
         return out
 
     def mark_failure(self, slug: str) -> None:
         self.failures[slug] = self.failures.get(slug, 0) + 1
 
     def mark_success(self, slug: str) -> None:
         self.failures[slug] = 0
 
     def is_unhealthy(self, slug: str) -> bool:
         return self.failures.get(slug, 0) >= UNHEALTHY_THRESHOLD
+
+
+def _gemini_loader(directory: Path, pool):
+    if directory.name != "gemini" or not (directory / "config.yaml").exists():
+        return None
+    import yaml
+
+    from .providers.gemini_native import GeminiNative
+
+    cfg = yaml.safe_load((directory / "config.yaml").read_text(encoding="utf-8"))
+    return GeminiNative(cfg, directory)
+
+
+LOADERS.append(_gemini_loader)
diff --git a/recipes/gemini/config.yaml b/recipes/gemini/config.yaml
new file mode 100644
index 0000000..a2e7cde
--- /dev/null
+++ b/recipes/gemini/config.yaml
@@ -0,0 +1,13 @@
+slug: gemini
+# cookie_file trß╗Å tß╗¢i JSON {"cookie": "...", "sapisid": "..."} hoß║╖c chuß╗ùi cookie th├┤.
+# Copy cookie tß╗½ tr├¼nh duyß╗çt ─æ├ú ─æ─âng nhß║¡p gemini.google.com v├áo recipes/secrets/gemini-cookies.txt
+cookie_file: ../secrets/gemini-cookies.txt
+auth_user: null
+temporary_chats: false
+models:
+  - id: gemini-flash
+    model_id: 1
+    think_mode: null
+  - id: gemini-flash-thinking
+    model_id: 1
+    think_mode: 0
diff --git a/tests/unit/test_gemini_native.py b/tests/unit/test_gemini_native.py
new file mode 100644
index 0000000..0dde7a0
--- /dev/null
+++ b/tests/unit/test_gemini_native.py
@@ -0,0 +1,48 @@
+import json
+import urllib.parse
+
+from chat2api.providers.gemini_native import (
+    build_payload,
+    clean_text,
+    extract_response_text,
+    make_sapisidhash,
+)
+
+
+def inner_line(texts):
+    inner = [None] * 5
+    inner[4] = [[None, texts]]
+    return json.dumps([["wrb.fr", None, json.dumps(inner)]]) + "x" * 250
+
+
+def test_extract_picks_longest_text():
+    raw = ")]}'\n\n" + inner_line(["hello", "hello world"]) + "\n" + inner_line(["tiny"])
+    assert extract_response_text(raw) == "hello world"
+
+
+def test_extract_raises_on_bard_error():
+    try:
+        extract_response_text("BardErrorInfo [123]")
+        assert False
+    except RuntimeError as e:
+        assert "123" in str(e)
+
+
+def test_build_payload_contains_model_and_think():
+    body = build_payload("hi", model_id=7, think_mode=2)
+    params = urllib.parse.parse_qs(body)
+    outer = json.loads(params["f.req"][0])
+    inner = json.loads(outer[1])
+    assert inner[79] == 7
+    assert inner[17] == [[2]]
+    assert inner[0][0] == "hi"
+
+
+def test_sapisidhash_shape():
+    h = make_sapisidhash("abc")
+    assert h.startswith("SAPISIDHASH ") and "_" in h
+
+
+def test_clean_text_strips_artifacts():
+    txt = "before\nhttp://googleusercontent.com/card_content/0\nafter"
+    assert clean_text(txt) == "before\nafter"

