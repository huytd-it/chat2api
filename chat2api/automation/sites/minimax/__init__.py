"""MiniMax Agent registration; models and browser operations await probing.

Do not publish a guessed default model or infer capabilities from the MiniMax
API: agent.minimax.io is a separate website automation surface.
"""
from ...contracts import SiteManifest

MANIFEST = SiteManifest(
    id="minimax", slug="minimax-agent", title="MiniMax Agent",
    origin="https://agent.minimax.io/", hosts=("agent.minimax.io",),
    models=(), operations=frozenset(),
)
