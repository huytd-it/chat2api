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
