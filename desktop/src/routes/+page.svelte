<script lang="ts">
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import TopBar from "$lib/components/TopBar.svelte";
  import InstrumentRail from "$lib/components/InstrumentRail.svelte";
  import PlaygroundView from "$lib/components/PlaygroundView.svelte";
  import IntegrationsView from "$lib/components/IntegrationsView.svelte";
  import LogsView from "$lib/components/LogsView.svelte";
  import Toast from "$lib/components/Toast.svelte";
  import { currentView, serverStatus, serverLog } from "$lib/stores";
  import { fetchHealth } from "$lib/api";
  import { refreshModels, refreshRecipes } from "$lib/sync";

  /** The sidecar can take a few seconds to boot (browser engine startup, etc.),
   * so unlike the browser build's single /health check, retry until it answers. */
  async function waitForHealth(): Promise<boolean> {
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        const h = await fetchHealth();
        serverStatus.set({ state: "ok", contexts: String(h.contexts), engine: h.engine });
        return true;
      } catch {
        serverStatus.set({ state: "loading", contexts: "-", engine: "-" });
        await new Promise((resolve) => setTimeout(resolve, 750));
      }
    }
    serverStatus.set({ state: "error", contexts: "-", engine: "-" });
    return false;
  }

  onMount(() => {
    let unlisten: (() => void) | undefined;
    listen<string>("server-log", (event) => {
      serverLog.update((lines) => [...lines.slice(-199), event.payload]);
    })
      .then((fn) => {
        unlisten = fn;
      })
      .catch(() => {
        // Not running inside Tauri (e.g. `npm run dev` in a plain browser); nothing to listen to.
      });

    (async () => {
      const ready = await waitForHealth();
      if (ready) {
        refreshModels();
        refreshRecipes();
      }
    })();

    return () => unlisten?.();
  });
</script>

<InstrumentRail />
<TopBar />
<main>
  <div hidden={$currentView !== "playground"}>
    <PlaygroundView />
  </div>
  <div hidden={$currentView !== "integrations"}>
    <IntegrationsView />
  </div>
  <div hidden={$currentView !== "logs"}>
    <LogsView />
  </div>
</main>
<Toast />
