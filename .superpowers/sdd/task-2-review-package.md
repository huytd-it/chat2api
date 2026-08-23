## Commits
104f383 feat: history flattening + request schemas

## Stat
 chat2api/prompt.py        | 11 +++++++++++
 chat2api/schemas.py       | 19 +++++++++++++++++++
 tests/unit/test_prompt.py | 29 +++++++++++++++++++++++++++++
 3 files changed, 59 insertions(+)

## Diffdiff --git a/chat2api/prompt.py b/chat2api/prompt.py
new file mode 100644
index 0000000..589a8fa
--- /dev/null
+++ b/chat2api/prompt.py
@@ -0,0 +1,11 @@
+def flatten_messages(messages: list[dict]) -> str:
+    parts = []
+    system = "\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
+    if system:
+        parts.append(f"System: {system}")
+    for m in messages:
+        if m["role"] == "system" or not m["content"]:
+            continue
+        who = "User" if m["role"] == "user" else "Assistant"
+        parts.append(f"{who}: {m['content']}")
+    return "\n\n".join(parts)
diff --git a/chat2api/schemas.py b/chat2api/schemas.py
new file mode 100644
index 0000000..9fcd589
--- /dev/null
+++ b/chat2api/schemas.py
@@ -0,0 +1,19 @@
+from pydantic import BaseModel
+
+
+class Message(BaseModel):
+    role: str
+    content: str
+
+
+class ChatRequest(BaseModel):
+    model: str
+    messages: list[Message]
+    stream: bool = False
+
+    def as_list(self) -> list[dict]:
+        return [{"role": m.role, "content": m.content} for m in self.messages]
+
+
+class IntegrateRequest(BaseModel):
+    url: str
diff --git a/tests/unit/test_prompt.py b/tests/unit/test_prompt.py
new file mode 100644
index 0000000..c361668
--- /dev/null
+++ b/tests/unit/test_prompt.py
@@ -0,0 +1,29 @@
+from chat2api.prompt import flatten_messages
+from chat2api.schemas import ChatRequest
+
+
+def test_single_user():
+    assert flatten_messages([{"role": "user", "content": "hi"}]) == "User: hi"
+
+
+def test_system_first_then_turns():
+    msgs = [
+        {"role": "system", "content": "be brief"},
+        {"role": "user", "content": "q1"},
+        {"role": "assistant", "content": "a1"},
+        {"role": "user", "content": "q2"},
+    ]
+    assert flatten_messages(msgs) == "System: be brief\n\nUser: q1\n\nAssistant: a1\n\nUser: q2"
+
+
+def test_empty_assistant_dropped():
+    msgs = [{"role": "assistant", "content": ""}, {"role": "user", "content": "q"}]
+    assert flatten_messages(msgs) == "User: q"
+
+
+def test_chat_request_as_list():
+    req = ChatRequest.model_validate(
+        {"model": "a/b", "messages": [{"role": "user", "content": "x"}], "stream": True}
+    )
+    assert req.as_list() == [{"role": "user", "content": "x"}]
+    assert req.stream is True

