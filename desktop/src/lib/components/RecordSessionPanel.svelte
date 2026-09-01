<script lang="ts">
  import { onDestroy } from "svelte";
  import { apiKey, showToast } from "../stores";
  import { fetchJob, finishRecord, jobAction, startRecord, type JobStatus } from "../api";
  import { refreshAfterRecipeChange } from "../sync";
  import { Button } from "$lib/components/ui/button";
  import { Browser, Check, CircleNotch, Record as RecordIcon, X } from "phosphor-svelte";

  interface Props {
    /** URL trang chat sẽ mở để ghi. */
    url: string;
    /** Bắt buộc — phiên ghi (kể cả đăng nhập giữa chừng) gắn vào profile này. */
    profileId: number | null;
    /** Có slug = ghi đè recipe đang có; không có = sinh recipe mới. */
    slug?: string | null;
    label?: string;
    disabled?: boolean;
    onSuccess?: (slug?: string) => void;
  }
  let { url, profileId, slug = null, label = "Ghi thao tác", disabled = false, onSuccess }: Props = $props();

  // Khớp jobs.TERMINAL_STATUSES ở backend.
  const TERMINAL = ["ok", "failed", "cancelled", "login_timeout", "record_timeout"];

  let jobId = $state<string | null>(null);
  let status = $state("idle");
  let statusText = $state("");
  let kind = $state<"idle" | "busy" | "error" | "success">("idle");
  let log = $state("");
  let starting = $state(false);
  let actionBusy = $state(false);
  let logEl = $state<HTMLElement | null>(null);

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollAbort: AbortController | null = null;
  let pollGen = 0;

  const active = $derived(jobId !== null && !TERMINAL.includes(status));
  const canFinish = $derived(status === "recording");

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer);
    if (pollAbort) pollAbort.abort();
    pollTimer = null;
    pollAbort = null;
    pollGen++;
  }
  onDestroy(stopPolling);

  function show(j: { status: string }) {
    status = j.status;
    kind = j.status === "ok" ? "success"
      : TERMINAL.includes(j.status) ? "error"
      : "busy";
    if (j.status === "recording")
      statusText = "Chromium đang ghi — thao tác thật trên trang, xong bấm Hoàn tất.";
    else if (j.status === "resuming_record")
      statusText = "Đang gửi các selector vừa ghi cho AI sinh recipe…";
    else if (j.status === "ok")
      statusText = "Xong — recipe đã sinh từ thao tác và chạy thử đạt.";
    else if (j.status === "record_timeout")
      statusText = "Hết 30 phút ghi — phiên đã đóng.";
    else statusText = "Trạng thái: " + j.status;
  }

  function startPolling(id: string) {
    jobId = id;
    const gen = ++pollGen;
    let ticks = 0;
    const poll = async () => {
      if (gen !== pollGen || id !== jobId) return;
      // 30 phút ghi + vòng trial của analyzer.
      if (++ticks > 2400) {
        statusText = "Timeout: job quá lâu";
        kind = "error";
        status = "failed";
        return;
      }
      const ctrl = new AbortController();
      pollAbort = ctrl;
      let terminal = false;
      try {
        const j: JobStatus = await fetchJob($apiKey, id, ctrl.signal);
        if (gen !== pollGen || id !== jobId) return;
        log = (j.log || []).join("\n");
        if (logEl) requestAnimationFrame(() => { if (logEl) logEl.scrollTop = logEl.scrollHeight; });
        show(j);
        terminal = TERMINAL.includes(j.status);
        if (terminal) {
          if (pollTimer) clearTimeout(pollTimer);
          pollTimer = null;
          if (j.status === "ok") {
            showToast(`Đã sinh recipe ${j.slug ?? ""} từ thao tác ghi được`.trim());
            await refreshAfterRecipeChange();
            onSuccess?.(j.slug);
          }
        }
      } catch (e: any) {
        if (gen === pollGen && id === jobId && e?.name !== "AbortError") {
          statusText = "Poll lỗi: " + e;
          kind = "error";
          status = "failed";
        }
      } finally {
        if (pollAbort === ctrl) pollAbort = null;
        if (!terminal && gen === pollGen && id === jobId) pollTimer = setTimeout(poll, 1000);
      }
    };
    pollTimer = setTimeout(poll, 800);
  }

  async function start() {
    const target = (url || "").trim();
    if (!target) { showToast("Nhập URL trang chat trước khi ghi thao tác."); return; }
    try { new URL(target); } catch { showToast("URL không hợp lệ."); return; }
    if (!profileId) { showToast("Chọn profile trước khi ghi thao tác."); return; }
    stopPolling();
    log = ""; status = "recording"; kind = "busy";
    statusText = "Đang mở Chromium để ghi…";
    starting = true;
    try {
      const data = await startRecord($apiKey, target, profileId, slug ?? undefined);
      startPolling(data.job_id);
    } catch (e) {
      statusText = "Lỗi: " + e; kind = "error"; status = "failed"; jobId = null;
    } finally {
      starting = false;
    }
  }

  async function finish() {
    const id = jobId;
    if (!id) return;
    actionBusy = true;
    try {
      await finishRecord($apiKey, id);
      show({ status: "resuming_record" });
      startPolling(id);
    } catch (e) {
      statusText = "Lỗi: " + e; kind = "error";
    } finally {
      actionBusy = false;
    }
  }

  async function cancel() {
    const id = jobId;
    if (!id) return;
    actionBusy = true;
    try {
      const data = await jobAction($apiKey, id, "cancel");
      stopPolling();
      show(data);
    } catch (e) {
      statusText = "Lỗi: " + e; kind = "error";
    } finally {
      actionBusy = false;
    }
  }
</script>

<div class="grid gap-2">
  <Button variant="outline" class="w-fit" disabled={disabled || starting || active} onclick={start}>
    {#if starting}<CircleNotch class="animate-spin" /> Đang mở…{:else}<RecordIcon /> {label}{/if}
  </Button>

  {#if statusText}
    <div
      class={`flex items-center gap-2 rounded-lg border p-2 text-sm ${
        kind === "error" ? "border-destructive/30 bg-destructive/5 text-destructive"
        : kind === "success" ? "border-success/30 bg-success/5 text-success"
        : "border-warning/30 bg-warning/5 text-warning"}`}
      role={kind === "error" ? "alert" : "status"}
      aria-live="polite"
    >
      <span class={`size-2 shrink-0 rounded-full ${kind === "error" ? "bg-destructive" : kind === "success" ? "bg-success" : "bg-warning"}`}></span>
      {statusText}
    </div>
  {/if}

  {#if canFinish}
    <div class="flex flex-col gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3">
      <div class="flex items-start gap-2 text-sm text-primary">
        <Browser class="mt-0.5 shrink-0" size={17} aria-hidden="true" />
        <p>Cửa sổ Chromium đã mở <strong>ngoài ứng dụng này</strong> — tìm nó trên taskbar và thao tác như dùng thật (gõ prompt, gửi, bấm Copy khi trả lời xong). Log bên dưới hiện selector vừa bắt được.</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button size="sm" disabled={actionBusy} onclick={finish}><Check /> Hoàn tất</Button>
        <Button size="sm" variant="outline" disabled={actionBusy} onclick={cancel}><X /> Hủy</Button>
      </div>
    </div>
  {/if}

  {#if log}
    <pre
      bind:this={logEl}
      class="m-0 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-[#0a0d0a] p-3 font-data text-[11px] leading-5 text-[#8be8a8]"
      aria-label="Nhật ký ghi thao tác"
      aria-live="polite">{log}</pre>
  {/if}
</div>
