### Task 2: flatten history + schemas

**Files:**
- Create: `chat2api/prompt.py`, `chat2api/schemas.py`
- Test: `tests/unit/test_prompt.py`

**Interfaces:**
- Produces: `flatten_messages(messages: list[dict]) -> str`; `Message{role:str, content:str}`, `ChatRequest(BaseModel)` vá»›i `model: str`, `messages: list[Message]`, `stream: bool = False`, method `as_list() -> list[dict]`; `IntegrateRequest{url: str}`.

- [ ] **Step 1: Viáº¿t test tháº¥t báº¡i**

`tests/unit/test_prompt.py`:

```python
from chat2api.prompt import flatten_messages
from chat2api.schemas import ChatRequest


def test_single_user():
    assert flatten_messages([{"role": "user", "content": "hi"}]) == "User: hi"


def test_system_first_then_turns():
    msgs = [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
        {"role": "user", "content": "q2"},
    ]
    assert flatten_messages(msgs) == "System: be brief\n\nUser: q1\n\nAssistant: a1\n\nUser: q2"


def test_empty_assistant_dropped():
    msgs = [{"role": "assistant", "content": ""}, {"role": "user", "content": "q"}]
    assert flatten_messages(msgs) == "User: q"


def test_chat_request_as_list():
    req = ChatRequest.model_validate(
        {"model": "a/b", "messages": [{"role": "user", "content": "x"}], "stream": True}
    )
    assert req.as_list() == [{"role": "user", "content": "x"}]
    assert req.stream is True
```

- [ ] **Step 2: Cháº¡y xÃ¡c nháº­n fail**

Run: `python -m pytest tests/unit/test_prompt.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'chat2api.prompt'`

- [ ] **Step 3: Implement**

`chat2api/prompt.py`:

```python
def flatten_messages(messages: list[dict]) -> str:
    parts = []
    system = "\n".join(m["content"] for m in messages if m["role"] == "system" and m["content"])
    if system:
        parts.append(f"System: {system}")
    for m in messages:
        if m["role"] == "system" or not m["content"]:
            continue
        who = "User" if m["role"] == "user" else "Assistant"
        parts.append(f"{who}: {m['content']}")
    return "\n\n".join(parts)
```

`chat2api/schemas.py`:

```python
from pydantic import BaseModel


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = False

    def as_list(self) -> list[dict]:
        return [{"role": m.role, "content": m.content} for m in self.messages]


class IntegrateRequest(BaseModel):
    url: str
```

- [ ] **Step 4: Cháº¡y xÃ¡c nháº­n pass**

Run: `python -m pytest tests/unit/test_prompt.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add chat2api/prompt.py chat2api/schemas.py tests/unit/test_prompt.py
git commit -m "feat: history flattening + request schemas"
```

---


