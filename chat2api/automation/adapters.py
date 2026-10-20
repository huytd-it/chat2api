"""Temporary import boundary during module migration.

Production callers still import ``adapter_for`` here until runtime cutover.
Site-specific implementation now lives in its site package, not in this shim.
"""
from urllib.parse import urlsplit

from .sites.base import SiteAdapter
from .sites.chatgpt.controls import ChatGPTAdapter
from .sites.qwen.controls import QwenAdapter


def adapter_for(url: str) -> SiteAdapter:
    host = urlsplit(url).hostname
    if host == "chat.qwen.ai":
        return QwenAdapter("https://chat.qwen.ai")
    if host == "chatgpt.com":
        return ChatGPTAdapter("https://chatgpt.com")
    return SiteAdapter(url)
