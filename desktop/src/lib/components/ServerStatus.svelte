<script lang="ts">
  import { onDestroy } from "svelte";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { serverStatus } from "../stores";
  import { recipes } from "../sync";
  import { cn } from "../utils";

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
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60)
      .toString()
      .padStart(2, "0");
    const s = (total % 60).toString().padStart(2, "0");
    return h > 0 ? `${h}:${m}:${s}` : `${m}:${s}`;
  }

  const labels: Record<"loading" | "ok" | "error", string> = {
    loading: "Đang kết nối",
    ok: "Server sẵn sàng",
    error: "Mất kết nối",
  };

  const dotClass = $derived(
    $serverStatus.state === "ok"
      ? "bg-success"
      : $serverStatus.state === "error"
        ? "bg-destructive"
        : "bg-warning",
  );
</script>

<Tooltip.Root>
  <Tooltip.Trigger>
    {#snippet child({ props })}
      <div
        {...props}
        class="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5 text-xs"
        data-state={$serverStatus.state}
      >
        <span class={cn("size-2 rounded-full", dotClass, $serverStatus.state === "loading" && "animate-pulse")}
        ></span>
        <span class="hidden font-medium text-foreground sm:inline">{labels[$serverStatus.state]}</span>
        {#if $serverStatus.state === "ok"}
          <span class="font-data text-muted-foreground">{formatUptime(seconds)}</span>
        {/if}
      </div>
    {/snippet}
  </Tooltip.Trigger>
  <Tooltip.Content side="bottom" align="end" class="font-data text-xs">
    <div class="grid gap-1">
      <div>engine: {$serverStatus.engine}</div>
      <div>contexts: {$serverStatus.contexts}</div>
      <div>recipes: {$recipes.length}</div>
      <div>uptime: {formatUptime(seconds)}</div>
    </div>
  </Tooltip.Content>
</Tooltip.Root>
