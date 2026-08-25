<script lang="ts">
  import "../app.css";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import TopBar from "$lib/components/TopBar.svelte";
  import InstrumentRail from "$lib/components/InstrumentRail.svelte";
  import Toast from "$lib/components/Toast.svelte";
  import { serverStatus, serverLog } from "$lib/stores";
  import { fetchHealth } from "$lib/api";
  import { refreshModels, refreshRecipes, refreshAccounts, refreshOverview } from "$lib/sync";

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
THESIS: chat2api desktop stops reading as a chatbot demo and becomes a bench
instrument: every panel is something you probe, calibrate, or read, never
just scroll past.
OWN-WORLD: charcoal-graphite chassis, brushed-steel bezels, engraved
off-white panel labels, one phosphor-green live-signal accent, amber for
in-progress, calibration-red faults; Big Shoulders Display for the
nameplate and headlines, Archivo for body, Cascadia Code for every readout.
STORY: an operator selects a channel, sends a probe, watches the reply draw
as a live trace, reads server vitals off a permanent rail, and wires new
sites in at a calibration bench.
FIRST VIEWPORT: nameplate topbar with rocker-switch nav; a slim vitals rail
down the left edge; center chat renders as an oscilloscope face -- graticule
ground, phosphor-trace replies; right sidebar is a meter bank of
nixie-style counters and toggles.
FORM: The Instrument Bench, assigned index 6 of 7 grounded directions,
raised by Nixie Counter Bank (digit counters), Depth Gauge Descent (vitals
rail), the Saville catalog sleeve (negative space), and the festival
lineup poster (headline scale); seed key 861da6bc.
FINISH: unreviewed and undocumented is unfinished; this build ends with the
finish review, the verdict, DESIGN.md, and every shipping raster carrying
its provenance.
-->`;
</script>

{@html directionContract}
<InstrumentRail />
<TopBar />
<main>
  {@render children()}
</main>
<Toast />
