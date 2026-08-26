<script lang="ts">
  import { apiKey, serverLog } from "../stores";
  import { fetchLogs, type LogEntry } from "../api";
  import PageShell from "./PageShell.svelte";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { cn } from "../utils";
  import CopyIcon from "phosphor-svelte/lib/CopyIcon";
  import TrashIcon from "phosphor-svelte/lib/TrashIcon";

  let entries = $state<LogEntry[]>([]);
  let cursor = 0;
  let paused = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pollError = $state("");
  let clearOpen = $state(false);

  let appLogEl: HTMLElement | null = $state(null);
  let procLogEl: HTMLElement | null = $state(null);

  function levelClass(level: string): string {
    return level === "error"
      ? "text-destructive"
      : level === "warn"
        ? "text-warning"
        : "text-foreground/80";
  }

  function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function stickToBottom(el: HTMLElement | null) {
    if (!el || paused) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }

  async function poll() {
    try {
      const fresh = await fetchLogs($apiKey, cursor);
      if (fresh.length > 0) {
        cursor = fresh[fresh.length - 1].id;
        entries = [...entries.slice(-499), ...fresh];
        pollError = "";
        stickToBottom(appLogEl);
      }
    } catch (e) {
      pollError = "poll lỗi: " + e;
    } finally {
      timer = setTimeout(poll, 1500);
    }
  }

  $effect(() => {
    poll();
    return () => {
      if (timer !== null) clearTimeout(timer);
      timer = null;
    };
  });

  $effect(() => {
    if ($serverLog.length > 0) stickToBottom(procLogEl);
  });

  function clearView() {
    entries = [];
    clearOpen = false;
  }

  async function copyAll() {
    const text = entries
      .map((e) => `[${formatTime(e.ts)}] ${e.level.toUpperCase()} ${e.message}`)
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard unavailable — best effort */
    }
  }
</script>

<PageShell
  title="Logs"
  description="Hoạt động server (request, integrate, đăng nhập, lỗi) và output tiến trình chạy nền."
  width="wide"
>
  <Tabs.Root value="activity" class="gap-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <Tabs.List>
        <Tabs.Trigger value="activity">Hoạt động server</Tabs.Trigger>
        <Tabs.Trigger value="process">Process output</Tabs.Trigger>
      </Tabs.List>
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-2">
          <Switch id="pause-scroll" bind:checked={paused} />
          <Label for="pause-scroll" class="text-xs text-muted-foreground">Tạm dừng cuộn</Label>
        </div>
        <Tooltip.Root>
          <Tooltip.Trigger>
            {#snippet child({ props })}
              <Button {...props} variant="outline" size="icon-sm" onclick={copyAll} aria-label="Sao chép log">
                <CopyIcon size={16} />
              </Button>
            {/snippet}
          </Tooltip.Trigger>
          <Tooltip.Content>Sao chép toàn bộ</Tooltip.Content>
        </Tooltip.Root>
        <AlertDialog.Root bind:open={clearOpen}>
          <AlertDialog.Trigger>
            {#snippet child({ props })}
              <Button
                {...props}
                variant="outline"
                size="icon-sm"
                disabled={entries.length === 0}
                aria-label="Xóa log đang xem"
              >
                <TrashIcon size={16} />
              </Button>
            {/snippet}
          </AlertDialog.Trigger>
          <AlertDialog.Content>
            <AlertDialog.Header>
              <AlertDialog.Title>Xóa log đang xem?</AlertDialog.Title>
              <AlertDialog.Description>
                Chỉ xóa khỏi màn hình này. Log trên server không bị ảnh hưởng.
              </AlertDialog.Description>
            </AlertDialog.Header>
            <AlertDialog.Footer>
              <AlertDialog.Cancel>Hủy</AlertDialog.Cancel>
              <AlertDialog.Action onclick={clearView}>Xóa</AlertDialog.Action>
            </AlertDialog.Footer>
          </AlertDialog.Content>
        </AlertDialog.Root>
      </div>
    </div>

    {#if pollError}
      <p class="rounded-md bg-destructive/10 px-3 py-2 font-data text-xs text-destructive">
        {pollError}
      </p>
    {/if}

    <Tabs.Content value="activity">
      <pre
        bind:this={appLogEl}
        aria-label="Server activity log"
        class="h-[60vh] overflow-auto rounded-lg border border-border bg-muted/30 p-4 font-data text-xs leading-relaxed whitespace-pre-wrap"
        >{#each entries as e (e.id)}<span class={cn("block", levelClass(e.level))}>[{formatTime(
              e.ts,
            )}] {e.level.toUpperCase()} {e.message}</span>{:else}<span class="text-muted-foreground"
          >Chưa có log nào.</span
        >{/each}</pre>
    </Tabs.Content>

    <Tabs.Content value="process">
      <pre
        bind:this={procLogEl}
        aria-label="Sidecar process output"
        class="h-[60vh] overflow-auto rounded-lg border border-border bg-muted/30 p-4 font-data text-xs leading-relaxed whitespace-pre-wrap"
        >{#each $serverLog as line, i (i)}{line}
{:else}<span class="text-muted-foreground">Chưa có output nào.</span>{/each}</pre>
    </Tabs.Content>
  </Tabs.Root>
</PageShell>
