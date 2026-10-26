"""MiniMax Agent module.

Automation surface: https://agent.minimax.io/. Selectors verified via recorded
trace (job 3200e9755b21). Execution currently provided by the legacy recipe
`recipes/minimax-agent/recipe.yaml`; module driver migration is tracked
separately.
"""
from ...contracts import Operation, SiteManifest, SiteModel

MANIFEST = SiteManifest(
    id="minimax", slug="minimax-agent", title="MiniMax Agent",
    origin="https://agent.minimax.io/", hosts=("agent.minimax.io",),
    models=(SiteModel("m3.1-flash", "M3.1-Flash (Free)"),),
    operations=frozenset({Operation.CHAT}),
)
