<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { startIntegration, fetchJob, jobAction, type JobStatus } from "../api";
  import { refreshIntegrations, refreshModels } from "../sync";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Card from "$lib/components/ui/card";
  import { Browser, Check, CircleNotch, Copy, Globe, TerminalWindow, X } from "phosphor-svelte";

  let siteUrl = $state("");
  let headedMode = $state(false);
  let integrateDisabled = $state(false);
  let jobStatusText = $state("");
  let jobLog = $state("");
  let loginActionsVisible = $state(false);
  let loginButtonsDisabled = $state(false);
  let jobLogEl = $state<HTMLElement | null>(null);
  let statusKind = $state<"idle" | "busy" | "error" | "success">("idle");
  let copyStatus = $state("");

  const terminalStatuses = ["ok", "failed", "cancelled", "login_timeout"];
  let activeJobId: string | null = null;
  let pollGeneration = 0;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollAbort: AbortController | null = null;
  let operationGeneration = 0;
  let actionGeneration = 0;
  let actionInFlightFor: number | null = null;

  function resetLoginButtons() { loginButtonsDisabled = false; }
  function stopPolling() {
    pollGeneration++;
    if (pollTimer !== null) clearTimeout(pollTimer);
    if (pollAbort !== null) pollAbort.abort();
    pollTimer = null;
    pollAbort = null;
    activeJobId = null;
  }
  function showJobStatus(j: Partial<JobStatus> & { status: string }) {
    const canLogin = j.status === "waiting_login" && j.can_complete_login === true;
    loginActionsVisible = canLogin;
    statusKind = j.status === "ok" ? "success" : ["failed", "cancelled", "login_timeout"].includes(j.status) ? "error" : "busy";
    if (canLogin) {
      if (actionInFlightFor !== pollGeneration) resetLoginButtons();
      jobStatusText = "Chrome đã mở. Hãy đăng nhập trong cửa sổ đó";
    } else if (j.status === "waiting_login") jobStatusText = "Đang đóng phiên đăng nhập hết hạn…";
    else if (j.status === "resuming") jobStatusText = "Đang lưu session và tiếp tục…";
    else jobStatusText = "Trạng thái: " + j.status;
  }
  function startPolling(jobId: string) {
    stopPolling();
    const generation = pollGeneration;
    activeJobId = jobId;
    let ticks = 0;
    const poll = async () => {
      if (generation !== pollGeneration || jobId !== activeJobId) return;
      if (++ticks > 660) {
        loginActionsVisible = false;
        jobStatusText = "Timeout: job quá lâu, kiểm tra lại sau";
        statusKind = "error";
        stopPolling();
        return;
      }
      const controller = new AbortController();
      pollAbort = controller;
      let terminal = false;
      try {
        if (generation !== pollGeneration || jobId !== activeJobId) return;
        const j = await fetchJob($apiKey, jobId, controller.signal);
        if (generation !== pollGeneration || jobId !== activeJobId) return;
        jobLog = (j.log || []).join("\n");
        if (jobLogEl) requestAnimationFrame(() => { if (jobLogEl) jobLogEl.scrollTop = jobLogEl.scrollHeight; });
        showJobStatus(j);
        terminal = terminalStatuses.includes(j.status);
        if (terminal) { stopPolling(); refreshModels(); refreshIntegrations(); }
      } catch (e: any) {
        if (generation === pollGeneration && jobId === activeJobId && e?.name !== "AbortError") {
          jobStatusText = "Poll lỗi: " + e;
          statusKind = "error";
        }
      } finally {
        if (pollAbort === controller) pollAbort = null;
        if (!terminal && generation === pollGeneration && jobId === activeJobId) pollTimer = setTimeout(poll, 1000);
      }
    };
    pollTimer = setTimeout(poll, 1000);
  }
  async function postJobAction(action: "login-complete" | "cancel") {
    if (!activeJobId) return;
    const jobId = activeJobId;
    const generation = pollGeneration;
    const actionToken = ++actionGeneration;
    actionInFlightFor = generation;
    loginButtonsDisabled = true;
    try {
      const data = await jobAction($apiKey, jobId, action);
      if (generation !== pollGeneration || jobId !== activeJobId || actionToken !== actionGeneration) return;
      if (action === "login-complete") {
        startPolling(jobId); actionInFlightFor = null; showJobStatus({ status: "resuming" });
      } else {
        showJobStatus(data);
        if (terminalStatuses.includes(data.status)) { stopPolling(); refreshModels(); refreshIntegrations(); }
      }
    } catch (e) {
      if (generation === pollGeneration && jobId === activeJobId && actionToken === actionGeneration) {
        jobStatusText = "Lỗi: " + e; statusKind = "error"; resetLoginButtons();
      }
    } finally {
      if (generation === pollGeneration && jobId === activeJobId && actionToken === actionGeneration) actionInFlightFor = null;
    }
  }
  async function startIntegrationJob() {
    const url = siteUrl.trim();
    if (!url) { showToast("Nhập URL web chat trước khi bắt đầu."); return; }
    try { new URL(url); } catch { showToast("URL không hợp lệ."); return; }
    const operation = ++operationGeneration;
    actionGeneration++; actionInFlightFor = null; resetLoginButtons(); integrateDisabled = true; stopPolling();
    loginActionsVisible = false; jobLog = ""; statusKind = "busy"; jobStatusText = "Đang khởi tạo analyzer…";
    try {
      const data = await startIntegration($apiKey, url, headedMode);
      if (operation !== operationGeneration) return;
      jobStatusText = "Đang chạy job " + data.job_id + "…"; resetLoginButtons(); startPolling(data.job_id);
    } catch (e) {
      if (operation === operationGeneration) { jobStatusText = "Lỗi: " + e; statusKind = "error"; }
    } finally { if (operation === operationGeneration) integrateDisabled = false; }
  }
  async function copyLog() {
    try { await navigator.clipboard.writeText(jobLog); copyStatus = "Đã sao chép nhật ký job."; }
    catch { copyStatus = "Không thể truy cập clipboard."; }
  }
</script>

<Card.Root class="overflow-hidden" aria-labelledby="integrate-title">
  <Card.Header class="border-b">
    <div class="flex items-start gap-3">
      <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Globe size={19} aria-hidden="true" /></div>
      <div><Card.Title id="integrate-title">Thêm integration</Card.Title><Card.Description>Analyzer nhận diện giao diện, tạo recipe và đăng ký model mới.</Card.Description></div>
    </div>
  </Card.Header>
  <Card.Content class="grid gap-5 p-4 sm:p-6">
    <div class="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div class="relative"><Globe class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={17} aria-hidden="true" /><Input class="h-10 pl-10 font-data" type="url" inputmode="url" placeholder="https://chat.example.com" aria-label="URL web chat" bind:value={siteUrl} onkeydown={(e) => e.key === "Enter" && startIntegrationJob()} /></div>
      <Button class="h-10 px-4" disabled={integrateDisabled} onclick={startIntegrationJob}>{#if integrateDisabled}<CircleNotch class="animate-spin" /> Đang bắt đầu{:else}<Browser /> Phân tích site{/if}</Button>
    </div>
    <label class="flex cursor-pointer items-center justify-between gap-4 rounded-lg border bg-muted/30 px-3 py-2.5 text-sm"><span><strong class="font-medium">Hiện browser khi test</strong><span class="block text-xs text-muted-foreground">Tắt headless để quan sát analyzer thao tác.</span></span><Switch bind:checked={headedMode} aria-label="Hiện browser khi test" /></label>

    <section class="overflow-hidden rounded-lg border" aria-labelledby="job-progress-title">
      <header class="flex min-h-12 flex-wrap items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2">
        <div class="flex items-center gap-2"><TerminalWindow size={17} class="text-muted-foreground" aria-hidden="true" /><h3 id="job-progress-title" class="text-sm font-medium">Tiến trình analyzer</h3>{#if statusKind === "busy"}<CircleNotch class="animate-spin text-warning" size={15} aria-hidden="true" />{/if}</div>
        <Button variant="ghost" size="sm" disabled={!jobLog} onclick={copyLog}><Copy /> Sao chép</Button>
      </header>
      {#if jobStatusText}
        <div class={`flex items-center gap-2 border-b px-3 py-2 text-sm ${statusKind === "error" ? "bg-destructive/5 text-destructive" : statusKind === "success" ? "bg-success/5 text-success" : "bg-warning/5 text-warning"}`} role={statusKind === "error" ? "alert" : "status"} aria-live="polite">
          <span class={`size-2 shrink-0 rounded-full ${statusKind === "error" ? "bg-destructive" : statusKind === "success" ? "bg-success" : "bg-warning"}`}></span>{jobStatusText}
        </div>
      {/if}
      {#if loginActionsVisible}<div class="flex flex-wrap gap-2 border-b p-3"><Button disabled={loginButtonsDisabled} onclick={() => postJobAction("login-complete")}><Check /> Đã đăng nhập</Button><Button variant="outline" disabled={loginButtonsDisabled} onclick={() => postJobAction("cancel")}><X /> Hủy job</Button></div>{/if}
      <div class="relative min-h-52 bg-[#0a0d0a] shadow-inner">
        {#if !jobLog}<div class="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center"><TerminalWindow size={25} class="text-[#2c6b47]" aria-hidden="true" /><p class="text-sm text-[#d7f5e2]">Chưa có nhật ký</p><p class="font-data text-xs text-[#6f9b7d]">Log sẽ xuất hiện sau khi analyzer bắt đầu.</p></div>{/if}
        <pre class="m-0 max-h-80 min-h-52 overflow-auto whitespace-pre-wrap break-words p-3 font-data text-[11px] leading-6 text-[#8be8a8]" bind:this={jobLogEl} aria-label="Nhật ký job" aria-live="polite">{jobLog}</pre>
      </div>
    </section>
  </Card.Content>
</Card.Root>
<div class="sr-only" role="status" aria-live="polite">{copyStatus}</div>
