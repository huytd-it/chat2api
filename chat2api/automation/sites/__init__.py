"""Built-in website manifests. Driver migration is tracked separately.

These declarations describe intended module boundaries and stable public IDs,
not a claim that runtime migration or account verification is complete.
"""
from .chatgpt import MANIFEST as CHATGPT
from .deepseek import MANIFEST as DEEPSEEK
from .dola import MANIFEST as DOLA
from .gemini import MANIFEST as GEMINI
from .grok import MANIFEST as GROK
from .kimi import MANIFEST as KIMI
from .minimax import MANIFEST as MINIMAX
from .qwen import MANIFEST as QWEN
from .tencent import MANIFEST as TENCENT
from .zai import MANIFEST as ZAI

MANIFESTS = (QWEN, CHATGPT, DEEPSEEK, GEMINI, GROK, KIMI, DOLA, TENCENT, ZAI, MINIMAX)
