<script lang="ts">
  import "../app.css";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { ModeWatcher } from "mode-watcher";
  import { Toaster } from "$lib/components/ui/sonner/index.js";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import AppSidebar from "$lib/components/AppSidebar.svelte";
  import AppHeader from "$lib/components/AppHeader.svelte";
  import { serverStatus, serverLog, apiKey } from "$lib/stores";
  import { refreshWebsites } from "$lib/websites";
  import { fetchHealth } from "$lib/api";
  import { refreshModels, refreshRecipes, refreshAccounts, refreshOverview } from "$lib/sync";

  let { children } = $props();

  /** The sidecar can take a few seconds to boot (browser engine startup, etc.),
   * so unlike the browser build's single /health check, retry until it answers. */
  async function waitForHealth(): Promise<boolean> {
    for (let attempt = 0; attempt < 40; attempt++) {
      try {
        const h = await fetchHealth();
        serverStatus.set({ state: "ok", contexts: String(h.contexts), engine: h.mode ? `${h.engine} · ${h.mode}` : h.engine });
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
        refreshAccounts();
        refreshOverview();
        refreshWebsites($apiKey);
      }
    })();

    return () => unlisten?.();
  });

  // Plain Svelte template comments are stripped at compile time, so the
  // direction contract is injected via {@html} to survive as a real DOM
  // comment node the production build can be grepped for.
  const directionContract = `<!--
THESIS: website-first automation workspaces replace the generic playground.
OWN-WORLD: cool slate surfaces, cobalt actions, precise sans typography;
semantic status colors never claim unverified account readiness.
STORY: choose a website, select account/model, work in its own history and
inspect the real context. Global administration is secondary.
FIRST VIEWPORT: website rail, module header and target strip, conversation
and composer, with context inspector at wide widths and drawers below.
FORM: operator desk, grounded direction 3, seed 210f6e51; user-approved.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md
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
