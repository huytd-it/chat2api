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
    headed: bool = False


class AddAccountRequest(BaseModel):
    name: str


class AccountLoginRequest(BaseModel):
    """Mở browser đăng nhập cho một domain (không buộc vào recipe nào)."""

    domain: str = ""
    url: str = ""
    name: str = ""


class SaveAccountRequest(BaseModel):
    domain: str
    name: str


class SettingsRequest(BaseModel):
    values: dict[str, str]

class SessionUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = None

class SessionForkRequest(BaseModel):
    up_to_seq: int
