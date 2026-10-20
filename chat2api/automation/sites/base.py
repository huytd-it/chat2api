"""Explicit site controls. Unknown controls are errors, never a fake success."""
from urllib.parse import urlsplit

from ...errors import OpenAIError


class SiteAdapter:
    def __init__(self, origin: str):
        self.origin = origin

    def validate_conversation(self, url: str):
        try:
            parsed = urlsplit(url)
            origin = urlsplit(self.origin)
            valid = (parsed.scheme == "https" and parsed.hostname == origin.hostname
                     and not parsed.username and not parsed.password
                     and parsed.port in (None, 443))
        except ValueError:
            valid = False
        if not valid:
            raise OpenAIError(409, "conversation_invalid", "URL hội thoại không thuộc website/account đã chọn")

    async def thinking(self, page, enabled: bool):
        raise OpenAIError(422, "thinking_unknown", "Chưa kiểm chứng điều khiển Thinking cho account/model này")

    async def list_projects(self, page):
        raise OpenAIError(422, "projects_unknown", "Chưa kiểm chứng thao tác project cho website này")

    async def create_project(self, page, title, instructions, files):
        raise OpenAIError(422, "projects_unknown", "Chưa kiểm chứng thao tác project cho website này")

    async def delete_project(self, page, url):
        raise OpenAIError(422, "projects_unknown", "Chưa kiểm chứng thao tác project cho website này")
