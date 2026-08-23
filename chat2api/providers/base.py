from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class ModelInfo:
    id: str
    slug: str
    ready: bool = True


class Provider(ABC):
    slug: str = ""

    @abstractmethod
    def models(self) -> list[ModelInfo]: ...

    @abstractmethod
    def stream(self, messages: list[dict], model_id: str) -> AsyncIterator[str]:
        yield ""  # pragma: no cover
