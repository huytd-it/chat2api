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
    """Lưu phiên đăng nhập vừa mở.

    `domain` để trống là hợp lệ: server đọc cookie của context rồi tự suy ra
    domain (§6.1, bậc 4 của "tự dò domain").
    """

    domain: str = ""
    name: str


class ProfileCreateRequest(BaseModel):
    name: str
    engine: str | None = None
    headless: bool | None = None
    max_tabs: int | None = None
    proxy: str | None = None
    user_agent: str | None = None
    locale: str | None = None
    timezone: str | None = None
    viewport: str | None = None
    notes: str | None = None


class ProfileUpdateRequest(ProfileCreateRequest):
    name: str | None = None
    is_default: bool | None = None


class ProfileOpenRequest(BaseModel):
    url: str = ""


class ProfileAccountRequest(BaseModel):
    domain: str
    label: str = ""


class SettingsRequest(BaseModel):
    values: dict[str, str]


class ApiKeyCreateRequest(BaseModel):
    label: str
    # "chat" = gọi /v1/*, "admin" = gọi /admin/*. Bỏ trống ⇒ cả hai.
    scopes: str | None = None

class SessionUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    tags: list[str] | None = None

class SessionForkRequest(BaseModel):
    up_to_seq: int
