<script lang="ts">
  import "../app.css";

  let { children } = $props();

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
{@render children()}
