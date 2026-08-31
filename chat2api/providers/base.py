from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ModelInfo:
    id: str
    slug: str
    ready: bool = True
    capability: str = "chat"  # chat | image | both


class Provider(ABC):
    slug: str = ""

    @abstractmethod
    def models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        yield ""  # pragma: no cover

    def supports_image(self) -> bool:
        return any(m.capability in ("image", "both") for m in self.models())

    async def generate_images(self, prompt: str, n: int = 1, size: str = "1024x1024",
                              **kwargs) -> list[dict]:
        raise NotImplementedError(f"Provider '{self.slug}' không hỗ trợ tạo ảnh")
