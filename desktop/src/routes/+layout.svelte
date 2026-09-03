<script lang="ts">
  import "../app.css";
  import "../sessions.css";
  import "../session-inspector.css";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { ModeWatcher } from "mode-watcher";
  import { Toaster } from "$lib/components/ui/sonner/index.js";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import AppSidebar from "$lib/components/AppSidebar.svelte";
  import AppHeader from "$lib/components/AppHeader.svelte";
  import { serverStatus, serverLog } from "$lib/stores";
  import { fetchHealth } from "$lib/api";
  import { refreshModels, refreshRecipes, refreshFlows, refreshAccounts, refreshOverview } from "$lib/sync";

  let { children } = $props();

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
      if (await waitForHealth()) {
        refreshModels();
        refreshRecipes();
        refreshFlows();
        refreshAccounts();
        refreshOverview();
      }
    })();

    return () => unlisten?.();
  });

  // Plain Svelte template comments are stripped at compile time, so the
  // direction contract is injected via {@html} to survive as a real DOM
  // comment node the production build can be grepped for.
  const directionContract = `<!--
THESIS: chat2api desktop reads as a focused developer tool, not a themed
instrument panel: dense enough to work in, quiet enough to trust, honest
about state (connecting, healthy, degraded) at every layer.
OWN-WORLD: neutral zinc surfaces, one cobalt-blue accent for interactive
intent, green/amber/red reserved strictly for healthy/running/error
semantics; shadcn-svelte + Bits UI primitives on Tailwind v4 tokens, system
sans for UI text, monospace only for ids, models, timestamps and logs.
STORY: an operator opens the app to a collapsible sidebar and a slim header
with live connection status; Sessions is the dense workbench (session list,
conversation, composer, inspector); Integrations, Logs and Settings stay
narrow and legible.
FINISH: DESIGN.md documents the token system and component inventory this
build ships with; light, dark and system themes are first-class, not an
afterthought.
-->`;
</script>

<ModeWatcher />
<Toaster richColors closeButton />
{@html directionContract}

<Sidebar.Provider>
  <AppSidebar />
  <Sidebar.Inset class="h-svh overflow-hidden">
    <AppHeader />
    <main class="flex min-h-0 flex-1 flex-col overflow-hidden">
      {@render children()}
    </main>
  </Sidebar.Inset>
</Sidebar.Provider>
