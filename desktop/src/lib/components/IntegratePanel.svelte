<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { startIntegration, fetchJob, jobAction, type JobStatus } from "../api";
  import { refreshIntegrations, refreshModels } from "../sync";

  let siteUrl = $state("");
  let headedMode = $state(false);
  let integrateDisabled = $state(false);
  let jobStatusText = $state("");
  let jobLog = $state("");
  let loginActionsVisible = $state(false);
  let loginButtonsDisabled = $state(false);
  let jobLogEl = $state<HTMLElement | null>(null);
  // Watch id doubles as the job id — the server registers the analyzer's
  // page under the job id itself whenever "hiện browser" was checked.

  const terminalStatuses = ["ok", "failed", "cancelled", "login_timeout"];

  let activeJobId: string | null = null;
  let pollGeneration = 0;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let pollAbort: AbortController | null = null;
  let operationGeneration = 0;
  let actionGeneration = 0;
  let actionInFlightFor: number | null = null;

  function resetLoginButtons() {
    loginButtonsDisabled = false;
  }

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
    if (canLogin) {
      if (actionInFlightFor !== pollGeneration) resetLoginButtons();
      jobStatusText = "Chrome đã mở. Hãy đăng nhập trong cửa sổ đó";
    } else if (j.status === "waiting_login") {
      jobStatusText = "Đang đóng phiên đăng nhập hết hạn…";
    } else if (j.status === "resuming") {
      jobStatusText = "Đang lưu session và tiếp tục…";
    } else {
      jobStatusText = "trạng thái: " + j.status;
    }
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
        jobStatusText = "timeout: job quá lâu, kiểm tra lại sau";
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
        if (terminal) {
          stopPolling();
          refreshModels();
          refreshIntegrations();
        }
      } catch (e: any) {
        if (generation === pollGeneration && jobId === activeJobId && e?.name !== "AbortError") {
          jobStatusText = "poll lỗi: " + e;
        }
      } finally {
        if (pollAbort === controller) pollAbort = null;
        if (!terminal && generation === pollGeneration && jobId === activeJobId) {
          pollTimer = setTimeout(poll, 1000);
        }
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
        startPolling(jobId);
        actionInFlightFor = null;
        showJobStatus({ status: "resuming" });
      } else {
        showJobStatus(data);
        if (terminalStatuses.includes(data.status)) {
          stopPolling();
          refreshModels();
          refreshIntegrations();
        }
      }
    } catch (e) {
      if (generation === pollGeneration && jobId === activeJobId && actionToken === actionGeneration) {
        jobStatusText = "lỗi: " + e;
        resetLoginButtons();
      }
    } finally {
      if (generation === pollGeneration && jobId === activeJobId && actionToken === actionGeneration) {
        actionInFlightFor = null;
      }
    }
  }

  async function startIntegrationJob() {
    const url = siteUrl.trim();
    if (!url) {
      showToast("Nhập URL web chat trước khi bắt đầu.");
      return;
    }
    try {
      new URL(url);
    } catch {
      showToast("URL không hợp lệ.");
      return;
    }

    const operation = ++operationGeneration;
    actionGeneration++;
    actionInFlightFor = null;
    resetLoginButtons();
    integrateDisabled = true;
    stopPolling();
    loginActionsVisible = false;
    jobLog = "";
    try {
      const data = await startIntegration($apiKey, url, headedMode);
      if (operation !== operationGeneration) return;
      jobStatusText = "đang chạy job " + data.job_id + "...";
      resetLoginButtons();
      startPolling(data.job_id);
    } catch (e) {
      if (operation === operationGeneration) jobStatusText = "lỗi: " + e;
    } finally {
      if (operation === operationGeneration) integrateDisabled = false;
    }
  }
</script>

<section class="panel dash-card">
  <div class="panel-head">
    <div>
      <h2>Thêm site</h2>
      <p>Analyzer nhận diện giao diện, tạo recipe và đăng ký model mới vào router đang chạy.</p>
    </div>
  </div>
  <div class="dash-body">
    <div class="url-row">
      <input
        type="url"
        inputmode="url"
        placeholder="https://chat.example.com"
        aria-label="URL web chat"
        bind:value={siteUrl}
      />
      <button class="button" disabled={integrateDisabled} onclick={startIntegrationJob}>Phân tích</button>
    </div>
    <label class="headed-toggle">
      <input type="checkbox" bind:checked={headedMode} />
      Hiện browser khi test (không headless)
    </label>

    <div class="status-box" role="status" aria-live="polite">{#if jobStatusText}{jobStatusText}{/if}</div>
    {#if loginActionsVisible}
      <span class="login-actions">
        <button class="button" disabled={loginButtonsDisabled} onclick={() => postJobAction("login-complete")}>
          Đã đăng nhập
        </button>
        <button class="button secondary" disabled={loginButtonsDisabled} onclick={() => postJobAction("cancel")}>
          Hủy
        </button>
      </span>
    {/if}

    <div class="job-log-head">
      <span class="job-log-label">Nhật ký job</span>
      <button
        class="button secondary small"
        disabled={!jobLog}
        onclick={() => navigator.clipboard.writeText(jobLog).catch(() => {})}
      >
        Copy
      </button>
    </div>
    <pre class="job-log" bind:this={jobLogEl} aria-label="Job log">{#if jobLog}{jobLog}{/if}</pre>
  </div>
</section>
