<script lang="ts">
  import { apiKey, serverLog } from "../stores";
  import { fetchLogs, type LogEntry } from "../api";

  let entries = $state<LogEntry[]>([]);
  let cursor = 0;
  let paused = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let pollError = $state("");

  let appLogEl: HTMLElement | null = $state(null);
  let procLogEl: HTMLElement | null = $state(null);

  function levelClass(level: string): string {
    return level === "error" ? "fault" : level === "warn" ? "amber" : "";
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
  }

  async function copyAll() {
    const text = entries.map((e) => `[${formatTime(e.ts)}] ${e.level.toUpperCase()} ${e.message}`).join("\n");
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      /* clipboard unavailable — best effort */
    }
  }
</script>

<section class="view logs">
  <header class="page-heading">
    <h1>Nhật ký.</h1>
    <p>Theo dõi hoạt động server (request, integrate, đăng nhập, lỗi) và output tiến trình chạy nền.</p>
  </header>
  <div class="logs-grid">
    <section class="panel logs-card">
      <div class="logs-head">
        <div>
          <h2>Hoạt động server</h2>
          <p>Request, integrate, account, lỗi provider.</p>
        </div>
        <div class="logs-actions">
          <label class="pause-toggle">
            <input type="checkbox" bind:checked={paused} />
            Tạm dừng cuộn
          </label>
          <button class="button secondary small" onclick={copyAll}>Copy</button>
          <button class="button secondary small" onclick={clearView}>Xóa</button>
        </div>
      </div>
      {#if pollError}<div class="logs-error">{pollError}</div>{/if}
      <pre class="app-log" bind:this={appLogEl} aria-label="Server activity log">{#each entries as e (e.id)}<span class="log-line {levelClass(e.level)}">[{formatTime(e.ts)}] {e.level.toUpperCase()} {e.message}</span
        >
{/each}</pre>
    </section>
    <section class="panel logs-card">
      <div class="logs-head">
        <div>
          <h2>Process output</h2>
          <p>stdout/stderr thô của tiến trình chat2api chạy nền.</p>
        </div>
      </div>
      <pre class="app-log" bind:this={procLogEl} aria-label="Sidecar process output">{#each $serverLog as line, i (i)}{line}
{/each}</pre>
    </section>
  </div>
</section>
