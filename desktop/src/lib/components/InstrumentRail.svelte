<script lang="ts">
  import { onDestroy } from "svelte";
  import { serverStatus } from "../stores";
  import { recipes } from "../sync";

  let seconds = $state(0);
  let timer: ReturnType<typeof setInterval> | null = null;

  $effect(() => {
    if ($serverStatus.state === "ok") {
      if (timer === null) {
        timer = setInterval(() => {
          seconds += 1;
        }, 1000);
      }
    } else {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
      seconds = 0;
    }
  });

  onDestroy(() => {
    if (timer !== null) clearInterval(timer);
  });

  function formatUptime(total: number): string {
    const m = Math.floor(total / 60).toString().padStart(2, "0");
    const s = (total % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
  }

  const lampClass = $derived(
    $serverStatus.state === "ok" ? "on" : $serverStatus.state === "error" ? "fault" : "warn",
  );
</script>

<aside class="rail" aria-label="Server vitals">
  <div class="rail-item">
    <span class="rail-lamp {lampClass}"></span>
    <span class="rail-label">Link</span>
  </div>
  <div class="rail-item">
    <span class="rail-value">{formatUptime(seconds)}</span>
    <span class="rail-label">Uptime</span>
  </div>
  <div class="rail-spacer"></div>
  <div class="rail-item">
    <span class="rail-value">{$recipes.length}</span>
    <span class="rail-label">Channels</span>
  </div>
</aside>
