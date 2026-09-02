<script lang="ts">
  import { onDestroy } from "svelte";
  import { apiKey, showToast } from "../stores";
  import {
    fetchJob, finishRecord, jobAction, setRecordSegment, startRecord,
    fetchTrace, FLOW_KINDS, FLOW_LABELS,
    type FlowKind, type JobStatus, type RecordSegment,
  } from "../api";
  import { refreshAfterRecipeChange } from "../sync";
  import { Button } from "$lib/components/ui/button";
  import {
    Browser, Check, CircleNotch, Cube, Image as ImageIcon, Record as RecordIcon,
    Stop, TextT, VideoCamera, X,
  } from "phosphor-svelte";

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
  /** Đoạn đang ghi và các đoạn đã ghi được, đồng bộ từ job mỗi lần poll. */
  let segment = $state<FlowKind | null>(null);
  let segments = $state<RecordSegment[]>([]);
  let segmentBusy = $state<FlowKind | "stop" | null>(null);

  const FLOW_ICONS = { select_model: Cube, text: TextT, image: ImageIcon, video: VideoCamera };
  const eventsOf = (flow: FlowKind) => segments.find((s) => s.flow === flow)?.events ?? 0;

  let traceBusy = $state<null | "json" | "md">(null);
  async function downloadTrace(fmt: "json" | "md") {
    if (!jobId) return;
    traceBusy = fmt;
    try {
      const data = await fetchTrace($apiKey, jobId, fmt);
      const text = fmt === "json" ? JSON.stringify(data, null, 2) : String(data);
      const blob = new Blob([text], { type: fmt === "json" ? "application/json" : "text/markdown" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${jobId}-${fmt === "json" ? "trace.json" : "trace.md"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showToast(`Đã tải trace .${fmt}`);
    } catch (e) {
      showToast("Không tải được trace: " + e);
    } finally {
      traceBusy = null;
    }
  }

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
      statusText = segment
        ? `Đang ghi đoạn “${FLOW_LABELS[segment]}” — thao tác trên trang, xong bấm Kết thúc đoạn.`
        : "Chromium đã sẵn sàng — chọn loại thao tác bên dưới rồi bắt đầu ghi đoạn.";
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
        // Server là nguồn sự thật cho đoạn ghi, trừ lúc đang có lệnh chuyển đoạn
        // bay đi — poll trả về trạng thái cũ sẽ làm nút nhấp nháy ngược.
        if (!segmentBusy) {
          segment = j.segment ?? null;
          segments = j.segments ?? [];
        }
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
    segment = null; segments = [];
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

  /** Mở đoạn ghi cho `flow`, hoặc đóng đoạn đang mở khi `flow` là null. */
  async function switchSegment(flow: FlowKind | null) {
    const id = jobId;
    if (!id) return;
    segmentBusy = flow ?? "stop";
    try {
      const j = await setRecordSegment($apiKey, id, flow);
      segment = j.segment ?? null;
      segments = j.segments ?? [];
      show(j);
    } catch (e) {
      showToast("Không chuyển được đoạn ghi: " + e);
    } finally {
      segmentBusy = null;
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
    <div class="flex flex-col gap-3 rounded-lg border border-primary/20 bg-primary/5 p-3">
      <div class="flex items-start gap-2 text-sm text-primary">
        <Browser class="mt-0.5 shrink-0" size={17} aria-hidden="true" />
        <p>Cửa sổ Chromium đã mở <strong>ngoài ứng dụng này</strong> — tìm nó trên taskbar. Ghi <strong>từng việc một</strong>: chọn loại thao tác bên dưới, bấm ghi, làm thật trên trang (gõ prompt, gửi, bấm Copy khi xong), rồi kết thúc đoạn và chuyển sang việc tiếp theo.</p>
      </div>

      <fieldset class="grid gap-2">
        <legend class="mb-1 text-xs font-medium text-muted-foreground">Đoạn ghi</legend>
        <div class="flex flex-wrap gap-2">
          {#each FLOW_KINDS as flow (flow)}
            {@const Icon = FLOW_ICONS[flow]}
            {@const count = eventsOf(flow)}
            {@const active = segment === flow}
            <Button
              size="sm"
              variant={active ? "default" : "outline"}
              disabled={segmentBusy !== null || actionBusy}
              aria-pressed={active}
              onclick={() => switchSegment(active ? null : flow)}
            >
              {#if segmentBusy === flow}
                <CircleNotch class="animate-spin" />
              {:else if active}
                <Stop weight="fill" />
              {:else}
                <Icon />
              {/if}
              {FLOW_LABELS[flow]}
              {#if count > 0}
                <span class="ml-1 rounded-full bg-foreground/10 px-1.5 text-[11px] tabular-nums">{count}</span>
              {/if}
            </Button>
          {/each}
        </div>
        <p class="text-xs text-muted-foreground">
          {#if segment}
            Đang ghi <strong>{FLOW_LABELS[segment]}</strong> — bấm lại nút đó để kết thúc đoạn, hoặc chọn việc khác để chuyển thẳng sang đoạn mới.
          {:else}
            Chưa ghi đoạn nào. Thao tác ngoài mọi đoạn vẫn được ghi nhận nhưng chỉ dùng làm ngữ cảnh, không thành flow.
          {/if}
        </p>
      </fieldset>

      <div class="flex flex-wrap gap-2">
        <Button size="sm" disabled={actionBusy || segmentBusy !== null} onclick={finish}>
          <Check /> Hoàn tất
        </Button>
        <Button size="sm" variant="outline" disabled={actionBusy} onclick={cancel}><X /> Hủy</Button>
      </div>
    </div>
  {/if}

  {#if jobId}
    <div class="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" disabled={traceBusy !== null} onclick={() => downloadTrace("json")}>
        {#if traceBusy === "json"}<CircleNotch class="animate-spin" />{:else}<Cube />{/if} Tải trace .json
      </Button>
      <Button size="sm" variant="outline" disabled={traceBusy !== null} onclick={() => downloadTrace("md")}>
        {#if traceBusy === "md"}<CircleNotch class="animate-spin" />{:else}<TextT />{/if} Tải trace .md
      </Button>
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
