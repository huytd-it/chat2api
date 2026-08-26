<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { apiKey, headedBrowser, showToast } from "../stores";
  import { models, selectedModel } from "../sync";
  import {
    deleteSession,
    exportSession,
    fetchSession,
    fetchSessions,
    fetchTestTargets,
    forkSession,
    openTestTarget,
    streamChat,
    updateSession,
    type ChatMessage,
    type SessionDetail,
    type SessionMessage,
    type SessionSummary,
    type TestTarget,
    type TestTargetList,
  } from "../api";
  import { renderMarkdown } from "../markdown";
  import MessageInspector from "./MessageInspector.svelte";

  let sessions = $state<SessionSummary[]>([]);
  let active = $state<SessionDetail | null>(null);
  let inspected = $state<SessionMessage | null>(null);
  let query = $state("");
  let modelFilter = $state("");
  let archived = $state(false);
  let loadingList = $state(true);
  let loadingDetail = $state(false);
  let prompt = $state("");
  let extraPrompts = $state<string[]>([]);
  let sending = $state(false);
  let elapsed = $state(0);
  let copiedId = $state<number | null>(null);
  let editingTitle = $state(false);
  let titleDraft = $state("");
  let tagDraft = $state("");
  let targets = $state<TestTarget[]>([]);
  let targetMeta = $state<Omit<TestTargetList, "targets"> | null>(null);
  let targetsLoading = $state(true);
  let benchOpen = $state(false);
  let selectedTargets = $state<number[]>([]);
  /** Model chọn riêng cho từng account — mở nhiều domain một lượt thì mỗi
   * target chạy recipe của domain nó, không dùng chung ô model ở composer. */
  let targetModels = $state<Record<number, string>>({});
  let targetQuery = $state("");
  let profileFilter = $state("");
  let domainFilter = $state("");
  let openingTargets = $state(false);
  /** Target đã thực sự mở tab — chỉ những cái này mới có live view để xem. */
  let openedTargets = $state<number[]>([]);
  let rotationMode = $state<"broadcast" | "round_robin" | "fill_first">("broadcast");
  let maxRequestsPerAccount = $state(1);

  type BatchJob = {
    promptIndex: number;
    prompt: string;
    accountId: number;
    model: string;
    label: string;
    sessionId: string;
    state: "queued" | "running" | "done" | "error";
    detail: string;
  };

  let batchJobs = $state<BatchJob[]>([]);
  let listTimer: ReturnType<typeof setTimeout> | null = null;
  let ticker: ReturnType<typeof setInterval> | null = null;
  let abortCtrl: AbortController | null = null;
  let traceEl = $state<HTMLDivElement | undefined>();
  let promptEl: HTMLTextAreaElement | undefined;

  const visibleMessages = $derived(active?.messages ?? []);

  const profileNames = $derived([...new Set(targets.map((item) => item.profile_name))].sort());
  const domainNames = $derived([...new Set(targets.map((item) => item.domain))].sort());

  const visibleTargets = $derived(targets.filter((item) => {
    if (profileFilter && item.profile_name !== profileFilter) return false;
    if (domainFilter && item.domain !== domainFilter) return false;
    const q = targetQuery.trim().toLowerCase();
    if (!q) return true;
    return `${item.profile_name} ${item.host} ${item.label} ${item.recipes.join(" ")}`
      .toLowerCase().includes(q);
  }));

  /** Gom theo profile: đó là đơn vị thật của Chromium (một tiến trình, một
   * trần tab), nên trạng thái "đã mở / còn bao nhiêu tab" phải đọc được ngay. */
  const targetGroups = $derived.by(() => {
    const groups = new Map<string, { name: string; items: TestTarget[] }>();
    for (const item of visibleTargets) {
      const group = groups.get(item.profile_name)
        ?? { name: item.profile_name, items: [] };
      group.items.push(item);
      groups.set(item.profile_name, group);
    }
    return [...groups.values()];
  });

  const selected = $derived(
    selectedTargets
      .map((id) => targets.find((item) => item.account_id === id))
      .filter((item): item is TestTarget => Boolean(item)),
  );
  const selectedProfiles = $derived([...new Set(selected.map((item) => item.profile_name))]);
  const selectedDomains = $derived([...new Set(selected.map((item) => item.domain))]);

  // Trần của server: vượt thì Chromium đóng bớt profile/tab RẢNH, nên phải nói
  // trước thay vì để người dùng thấy tab tự biến mất giữa chừng.
  const overProfileCap = $derived(
    Boolean(targetMeta) && selectedProfiles.length > (targetMeta?.max_profiles ?? 0));
  const crowdedProfiles = $derived(
    selectedProfiles.filter((name) => countSelectedIn(name) > maxTabsOf(name)));

  const allVisibleSelected = $derived(
    visibleTargets.some((item) => item.ready)
    && visibleTargets.every((item) => !item.ready || selectedTargets.includes(item.account_id)));

  const promptCount = $derived([prompt, ...extraPrompts].filter((item) => item.trim()).length);

  const batchCapacity = $derived(
    rotationMode === "broadcast"
      ? selected.length
      : selected.length * Math.max(1, Math.floor(Number(maxRequestsPerAccount) || 1)));

  /** Một dòng nói đúng cái sắp xảy ra — người dùng không phải tự nhân nhẩm. */
  const planLine = $derived(
    rotationMode === "broadcast"
      ? `${promptCount} prompt × ${selected.length} target = ${promptCount * selected.length} request`
      : `${promptCount}/${batchCapacity} prompt · ${
          rotationMode === "round_robin" ? "chia vòng tròn" : "lấp đầy từng target"}`);

  function countSelectedIn(name: string): number {
    return selected.filter((item) => item.profile_name === name).length;
  }

  function maxTabsOf(name: string): number {
    return targets.find((item) => item.profile_name === name)?.profile_max_tabs
      ?? targetMeta?.max_tabs ?? 8;
  }

  function groupOpen(name: string): TestTarget | undefined {
    return targets.find((item) => item.profile_name === name);
  }

  function modelFor(target: TestTarget): string {
    return targetModels[target.account_id] || target.models[0] || "";
  }

  /** Trạng thái ô tick của một nhóm profile: hết / một phần / không. */
  function groupState(items: TestTarget[]): { all: boolean; some: boolean } {
    const ready = items.filter((item) => item.ready);
    const picked = ready.filter((item) => selectedTargets.includes(item.account_id)).length;
    return { all: ready.length > 0 && picked === ready.length, some: picked > 0 };
  }

  const SEND_MODES = [
    { id: "broadcast", label: "Mọi target", help: "Mỗi prompt chạy trên tất cả target đã chọn." },
    { id: "round_robin", label: "Vòng tròn", help: "Chia đều prompt cho các target, lần lượt." },
    { id: "fill_first", label: "Lấp đầy", help: "Dùng hết hạn mức của target đầu rồi mới sang cái sau." },
  ] as const;

  function openBench() {
    benchOpen = true;
    inspected = null;
  }

  function inspect(message: SessionMessage) {
    inspected = message;
    benchOpen = false;
  }

  function formatDate(ts: number): string {
    const date = new Date(ts);
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return date.toLocaleDateString([], { day: "2-digit", month: "2-digit" });
  }

  function relativeTime(ts: number): string {
    const delta = Date.now() - ts;
    if (delta < 60_000) return "vừa xong";
    if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} phút`;
    if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} giờ`;
    return formatDate(ts);
  }

  async function loadList(preserve = true) {
    loadingList = true;
    try {
      sessions = await fetchSessions($apiKey, query.trim(), modelFilter, archived);
      if (!preserve || (active && !sessions.some((item) => item.id === active?.id))) {
        active = null;
        inspected = null;
      }
    } catch (error) {
      showToast("Không nạp được sessions: " + (error as Error).message);
    } finally {
      loadingList = false;
    }
  }

  function scheduleSearch() {
    if (listTimer) clearTimeout(listTimer);
    listTimer = setTimeout(() => loadList(false), 220);
  }

  async function openSession(id: string) {
    loadingDetail = true;
    inspected = null;
    try {
      active = await fetchSession($apiKey, id);
      titleDraft = active.title;
      // Chỉ theo model của session khi model đó còn dùng được. Model cũ có thể
      // đã bị lọc khỏi danh sách (mất API key, recipe bị xóa) — gán bừa sẽ làm
      // ô chọn rỗng và nút Gửi chết mà không nói vì sao.
      if (active.model_public_id && $models.some((m) => m.id === active?.model_public_id)) {
        $selectedModel = active.model_public_id;
      }
      setTimeout(() => {
        if (traceEl) traceEl.scrollTop = traceEl.scrollHeight;
      });
    } catch (error) {
      showToast("Không mở được session: " + (error as Error).message);
    } finally {
      loadingDetail = false;
    }
  }

  function newSession() {
    active = null;
    inspected = null;
    prompt = "";
    titleDraft = "";
    setTimeout(() => promptEl?.focus());
  }

  async function loadTargets() {
    targetsLoading = true;
    try {
      const { targets: list, ...meta } = await fetchTestTargets($apiKey);
      targets = list;
      targetMeta = meta;
      // Account bị xoá/tắt giữa chừng phải rơi khỏi lựa chọn, nếu không batch
      // sẽ bắn vào một id không còn tồn tại và chỉ báo lỗi lúc gửi.
      const usable = new Set(list.filter((item) => item.ready).map((item) => item.account_id));
      selectedTargets = selectedTargets.filter((id) => usable.has(id));
      openedTargets = openedTargets.filter((id) => usable.has(id));
      const picked: Record<number, string> = {};
      for (const item of list) {
        const kept = targetModels[item.account_id];
        picked[item.account_id] = kept && item.models.includes(kept) ? kept : (item.models[0] ?? "");
      }
      targetModels = picked;
    } catch (error) {
      targets = [];
      targetMeta = null;
      showToast("Không nạp được danh sách target: " + (error as Error).message);
    } finally {
      targetsLoading = false;
    }
  }

  async function applySelection(ids: number[]) {
    const added = ids.filter((id) => !selectedTargets.includes(id));
    selectedTargets = ids;
    if ($headedBrowser && added.length) await prewarmTargets(added);
  }

  async function toggleTarget(id: number) {
    const target = targets.find((item) => item.account_id === id);
    if (!target?.ready) return;
    await applySelection(selectedTargets.includes(id)
      ? selectedTargets.filter((item) => item !== id)
      : [...selectedTargets, id]);
  }

  async function toggleMany(ids: number[]) {
    const usable = ids.filter((id) => targets.find((item) => item.account_id === id)?.ready);
    const all = usable.length > 0 && usable.every((id) => selectedTargets.includes(id));
    await applySelection(all
      ? selectedTargets.filter((id) => !usable.includes(id))
      : [...selectedTargets, ...usable.filter((id) => !selectedTargets.includes(id))]);
  }

  const toggleGroup = (name: string) =>
    toggleMany(visibleTargets.filter((item) => item.profile_name === name)
      .map((item) => item.account_id));

  const toggleAllTargets = () =>
    toggleMany(visibleTargets.map((item) => item.account_id));

  function pickModel(accountId: number, model: string) {
    targetModels = { ...targetModels, [accountId]: model };
  }

  function addPrompt() {
    extraPrompts = [...extraPrompts, ""];
  }

  function updateExtraPrompt(index: number, value: string) {
    extraPrompts[index] = value;
    extraPrompts = [...extraPrompts];
  }

  function removePrompt(index: number) {
    extraPrompts = extraPrompts.filter((_, item) => item !== index);
  }

  async function prewarmTargets(ids = selectedTargets) {
    const list = targets.filter((item) => ids.includes(item.account_id) && item.ready);
    if (!list.length || openingTargets) return;
    openingTargets = true;
    try {
      // Mỗi target một tab riêng nên mở song song được; server tuần tự hoá phần
      // launch profile bằng khoá riêng của nó.
      const results = await Promise.allSettled(
        list.map((item) => openTestTarget($apiKey, modelFor(item), item.account_id)),
      );
      const opened = list
        .filter((_, index) => results[index].status === "fulfilled")
        .map((item) => item.account_id);
      openedTargets = [...new Set([...openedTargets, ...opened])];
      const failedIndex = results.findIndex((result) => result.status === "rejected");
      if (failedIndex >= 0) {
        const reason = (results[failedIndex] as PromiseRejectedResult).reason;
        const item = list[failedIndex];
        showToast(`Mở được ${opened.length}/${list.length} target. `
          + `${item.profile_name}/${item.host}: ${reason?.message ?? reason}`);
      } else {
        const profileCount = new Set(list.map((item) => item.profile_name)).size;
        showToast(`Đã mở ${opened.length} target trên ${profileCount} profile.`);
      }
      await loadTargets();
    } finally {
      openingTargets = false;
    }
  }

  async function onHeadedChange() {
    if ($headedBrowser) await prewarmTargets();
  }

  /** Ghép prompt với target thành danh sách request cụ thể.
   *
   * `broadcast` là chế độ mặc định vì đó chính là việc "mở cùng lúc nhiều
   * domain/profile/account": một prompt chạy trên MỌI target để so kết quả.
   * Hai chế độ còn lại chia prompt ra cho các target (chạy khối lượng lớn). */
  function buildJobs(prompts: string[]): BatchJob[] {
    const list = selected.filter((item) => item.ready);
    const quota = Math.max(1, Math.floor(Number(maxRequestsPerAccount) || 1));
    const jobs: BatchJob[] = [];
    const push = (promptIndex: number, target: TestTarget | undefined) => {
      if (!target) return;
      jobs.push({
        promptIndex,
        prompt: prompts[promptIndex],
        accountId: target.account_id,
        model: modelFor(target),
        label: `${target.profile_name} · ${target.host} · ${target.label}`,
        sessionId: crypto.randomUUID().replaceAll("-", ""),
        state: "queued",
        detail: "",
      });
    };
    prompts.forEach((_, index) => {
      if (rotationMode === "broadcast") list.forEach((target) => push(index, target));
      else if (rotationMode === "fill_first") push(index, list[Math.floor(index / quota)]);
      else push(index, list[index % list.length]);
    });
    return jobs;
  }

  function updateJob(index: number, state: BatchJob["state"], detail = "") {
    batchJobs[index] = { ...batchJobs[index], state, detail };
    batchJobs = [...batchJobs];
  }

  async function sendBatch() {
    const prompts = [prompt, ...extraPrompts].map((item) => item.trim()).filter(Boolean);
    const list = selected.filter((item) => item.ready);
    if (!prompts.length || !list.length || sending) return;
    const quota = Math.max(1, Math.floor(Number(maxRequestsPerAccount) || 1));
    if (rotationMode !== "broadcast" && prompts.length > list.length * quota) {
      showToast(`${prompts.length} prompt vượt sức chứa ${list.length * quota}. `
        + "Tăng max request/account, chọn thêm target, hoặc đổi sang Broadcast.");
      return;
    }
    const missing = list.find((item) => !modelFor(item));
    if (missing) {
      showToast(`${missing.host} chưa có model nào chạy được — bỏ chọn hoặc thêm recipe.`);
      return;
    }
    const jobs = buildJobs(prompts);
    if (!jobs.length) return;
    sending = true;
    elapsed = 0;
    batchJobs = jobs;
    ticker = setInterval(() => (elapsed += 1), 1000);
    const controllers = jobs.map(() => new AbortController());
    abortCtrl = { abort: () => controllers.forEach((item) => item.abort()) } as AbortController;
    // Bắn song song: request cùng một account bị server xếp hàng theo tab của
    // nó, còn account khác nhau chạy thật sự đồng thời.
    const results = await Promise.allSettled(jobs.map(async (job, index) => {
      updateJob(index, "running");
      await streamChat(
        $apiKey, job.model, [{ role: "user", content: job.prompt }], () => {},
        controllers[index].signal, $headedBrowser, job.sessionId, undefined,
        job.accountId,
      );
      updateJob(index, "done");
    }));
    results.forEach((result, index) => {
      if (result.status === "rejected") {
        const reason = result.reason as Error;
        updateJob(index, "error", reason?.name === "AbortError" ? "đã dừng" : reason.message);
      }
    });
    await loadList(false);
    await loadTargets();
    if (jobs[0]) await openSession(jobs[0].sessionId);
    const failed = results.filter((result) => result.status === "rejected").length;
    showToast(failed
      ? `Hoàn tất ${results.length - failed}/${results.length} request.`
      : `Hoàn tất ${results.length} request trên ${selectedProfiles.length} profile.`);
    sending = false;
    abortCtrl = null;
    if (ticker) clearInterval(ticker);
    ticker = null;
  }

  function autoGrow() {
    if (!promptEl) return;
    promptEl.style.height = "auto";
    promptEl.style.height = Math.min(promptEl.scrollHeight, 180) + "px";
  }

  function history(): ChatMessage[] {
    return visibleMessages
      .filter((message) => ["system", "user", "assistant"].includes(message.role) && !message.error)
      .map((message) => ({ role: message.role as ChatMessage["role"], content: message.content }));
  }

  async function send() {
    if (selectedTargets.length) return sendBatch();
    const text = prompt.trim();
    if (!text || !$selectedModel || sending) return;
    prompt = "";
    autoGrow();
    sending = true;
    elapsed = 0;
    ticker = setInterval(() => (elapsed += 1), 1000);
    const existingId = active?.id ?? crypto.randomUUID().replaceAll("-", "");
    const outgoing = [...history(), { role: "user" as const, content: text }];

    // Optimistic trace: phần lưu bền được nạp lại từ server ngay khi stream đóng.
    const temporary: SessionMessage = {
      id: -Date.now(), seq: visibleMessages.length, role: "user", content: text,
      content_markdown: null, content_html: null, reasoning: null, finish_reason: null,
      error: null, ttfb_ms: null, duration_ms: null, char_count: text.length,
      created_at: Date.now(), artifacts: [], request: null,
    };
    const reply: SessionMessage = {
      ...temporary, id: temporary.id - 1, seq: temporary.seq + 1, role: "assistant",
      content: "", char_count: 0,
    };
    if (active) active.messages.push(temporary, reply);

    abortCtrl = new AbortController();
    try {
      await streamChat(
        $apiKey, $selectedModel, outgoing,
        (delta) => {
          reply.content += delta;
          reply.char_count = reply.content.length;
          if (traceEl) traceEl.scrollTop = traceEl.scrollHeight;
        },
        abortCtrl.signal,
        $headedBrowser,
        existingId,
        () => {},
      );
      await openSession(existingId);
      await loadList();
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        showToast("Request lỗi: " + (error as Error).message);
      }
      try { await openSession(existingId); } catch { /* session có thể chưa được tạo */ }
      await loadList();
    } finally {
      sending = false;
      abortCtrl = null;
      if (ticker) clearInterval(ticker);
      ticker = null;
    }
  }

  function onComposerKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  async function saveTitle() {
    if (!active) return;
    active = await updateSession($apiKey, active.id, { title: titleDraft.trim() || active.title });
    editingTitle = false;
    await loadList();
  }

  async function togglePin() {
    if (!active) return;
    active = await updateSession($apiKey, active.id, { pinned: !active.pinned });
    await loadList();
  }

  async function addTag() {
    if (!active) return;
    const tag = tagDraft.trim();
    if (!tag || active.tags.includes(tag)) return;
    active = await updateSession($apiKey, active.id, { tags: [...active.tags, tag] });
    tagDraft = "";
  }

  async function removeTag(tag: string) {
    if (!active) return;
    active = await updateSession($apiKey, active.id, { tags: active.tags.filter((item) => item !== tag) });
  }

  async function archiveActive() {
    if (!active) return;
    await updateSession($apiKey, active.id, { archived: !active.archived });
    showToast(active.archived ? "Đã đưa session về hộp thư" : "Đã lưu trữ session");
    active = null;
    inspected = null;
    await loadList(false);
  }

  async function removeActive() {
    if (!active || !confirm(`Xóa vĩnh viễn “${active.title || "Session"}”?`)) return;
    await deleteSession($apiKey, active.id);
    active = null;
    inspected = null;
    await loadList(false);
    showToast("Đã xóa session");
  }

  async function forkAt(seq: number) {
    if (!active) return;
    const forked = await forkSession($apiKey, active.id, seq);
    await loadList();
    await openSession(forked.id);
    showToast("Đã tạo nhánh tới message đã chọn");
  }

  async function copyMessage(message: SessionMessage) {
    await navigator.clipboard.writeText(message.content_markdown ?? message.content);
    copiedId = message.id;
    setTimeout(() => (copiedId = null), 1400);
  }

  async function saveExport(format: "md" | "html" | "json" | "jsonl") {
    if (!active) return;
    const blob = await exportSession($apiKey, active.id, format);
    // Tauri webview chặn <a download> ở vài platform; clipboard vẫn là đường
    // fallback đáng tin cậy, còn browser/dev mode sẽ tải file bình thường.
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `session-${active.id.slice(0, 8)}.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  onMount(() => {
    loadTargets();
    loadList(false).then(() => {
      const requested = page.url.searchParams.get("open");
      if (requested) openSession(requested);
    });
    return () => {
      if (listTimer) clearTimeout(listTimer);
      if (ticker) clearInterval(ticker);
      abortCtrl?.abort();
    };
  });
</script>

<section
  class="view sessions-workbench"
  class:inspector-open={Boolean(inspected)}
  class:bench-open={benchOpen}
>
  <aside class="session-bank panel" aria-label="Danh sách sessions">
    <header class="session-bank-head">
      <div>
        <h1>Sessions</h1>
        <p>{sessions.length} phiên trong bộ lọc</p>
      </div>
      <button class="icon-button" title="Session mới" aria-label="Tạo session mới" onclick={newSession}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
      </button>
    </header>

    <div class="session-filters">
      <label class="session-search">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6" /><path d="m16 16 4 4" /></svg>
        <input aria-label="Tìm trong hội thoại" placeholder="Tìm toàn văn…" bind:value={query} oninput={scheduleSearch} />
      </label>
      <select aria-label="Lọc model" bind:value={modelFilter} onchange={() => loadList(false)}>
        <option value="">Mọi model</option>
        {#each $models as model (model.id)}<option value={model.id}>{model.id}</option>{/each}
      </select>
      <label class="archive-switch">
        <input type="checkbox" bind:checked={archived} onchange={() => loadList(false)} />
        <span>Đã lưu trữ</span>
      </label>
    </div>

    <div class="session-list" aria-live="polite">
      {#if loadingList}
        {#each [1, 2, 3, 4] as row}<div class="session-skeleton" aria-hidden="true"><i></i><i></i><i></i></div>{/each}
      {:else if sessions.length === 0}
        <div class="session-list-empty">
          <svg viewBox="0 0 32 32" aria-hidden="true"><path d="M6 7h20v17H11l-5 4V7Z" /><path d="M11 13h10M11 18h7" /></svg>
          <strong>Không có tín hiệu</strong>
          <span>{query ? "Thử từ khóa ngắn hơn." : "Gửi prompt đầu tiên để ghi một phiên."}</span>
        </div>
      {:else}
        {#each sessions as item (item.id)}
          <button
            class="session-row"
            class:active={active?.id === item.id}
            class:fault={item.error_count > 0}
            onclick={() => openSession(item.id)}
          >
            <span class="session-lamp" aria-hidden="true"></span>
            <span class="session-row-body">
              <span class="session-row-title">{item.title || "Phiên chưa đặt tên"}</span>
              <span class="session-row-preview">{item.first_prompt || "Không có prompt"}</span>
              <span class="session-row-meta">
                <code>{item.model_public_id || "—"}</code>
                <span>{item.message_count} msg</span>
                <time>{relativeTime(item.updated_at)}</time>
              </span>
            </span>
            {#if item.pinned}
              <svg class="pin-mark" viewBox="0 0 24 24" aria-label="Đã ghim"><path d="m9 4 6 0 1 5 3 3H5l3-3 1-5ZM12 12v8" /></svg>
            {/if}
          </button>
        {/each}
      {/if}
    </div>
  </aside>

  <!-- section chứ không main: layout shell đã có một <main>, và quy tắc CSS
       toàn cục cho `main` (margin:auto + padding theo rail) từng rơi vào đây
       làm console bị căn giữa và thụt lề vô cớ. -->
  <section class="session-console panel" aria-label="Bản ghi phiên">
    {#if loadingDetail}
      <div class="session-loading"><span class="spin-dot"></span>Đang đọc bản ghi…</div>
    {:else if !active}
      <div class="session-zero">
        <div class="zero-scope" aria-hidden="true"><i></i><i></i><span></span></div>
        <h2>Đầu dò sẵn sàng</h2>
        <p>Chọn một session để kiểm tra bản ghi, hoặc gõ vào ô bên dưới để phát tín hiệu mới. Mọi lượt chat từ API đều được lưu tự động.</p>
      </div>
    {:else}
      <header class="session-console-head">
        <div class="session-title-block">
          {#if editingTitle}
            <input class="title-input" bind:value={titleDraft} onkeydown={(e) => e.key === "Enter" && saveTitle()} />
            <button class="button secondary small" onclick={saveTitle}>Lưu</button>
          {:else}
            <button class="editable-title" title="Đổi tên session" onclick={() => { titleDraft = active?.title ?? ""; editingTitle = true; }}>
              <span>{active.title || "Phiên chưa đặt tên"}</span>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 20 4-1 11-11-3-3L5 16l-1 4ZM14 7l3 3" /></svg>
            </button>
          {/if}
          <div class="session-ident">
            <span class="dot on"></span>
            <code>{active.model_public_id}</code>
            <span>{active.kind === "api" ? "API" : "DESKTOP"}</span>
            <span>{active.message_count} MSG</span>
          </div>
        </div>
        <div class="session-tools">
          <button class="tool-button" class:active={Boolean(active.pinned)} title="Ghim session" onclick={togglePin}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 4 6 0 1 5 3 3H5l3-3 1-5ZM12 12v8" /></svg><span>Ghim</span>
          </button>
          <button class="tool-button" title="Lưu trữ" onclick={archiveActive}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16v13H4V7ZM3 4h18v3H3V4ZM9 11h6" /></svg><span>Lưu trữ</span>
          </button>
          <div class="export-menu">
            <button class="tool-button" title="Xuất session">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12M7 10l5 5 5-5M5 20h14" /></svg><span>Xuất</span>
            </button>
            <div class="export-popover">
              {#each ["md", "html", "json", "jsonl"] as fmt}
                <button onclick={() => saveExport(fmt as "md" | "html" | "json" | "jsonl")}>.{fmt}</button>
              {/each}
            </div>
          </div>
          <button class="tool-button danger-tool" title="Xóa session" onclick={removeActive}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M8 10v8M12 10v8M16 10v8M6 7l1 14h10l1-14" /></svg><span>Xóa</span>
          </button>
        </div>
      </header>

      <div class="session-trace" bind:this={traceEl} aria-live="polite">
        <div class="trace-start"><span>SESSION START</span><time>{new Date(active.created_at).toLocaleString()}</time></div>
        {#each visibleMessages as message (message.id)}
          <article class="recorded-message {message.role}" class:fault={Boolean(message.error)}>
            <header>
              <span class="role-badge">{message.role === "user" ? "IN" : message.role === "assistant" ? "OUT" : message.role.toUpperCase()}</span>
              <span>{message.role === "user" ? "Bạn" : message.role === "assistant" ? active.model_public_id : message.role}</span>
              <time>{formatDate(message.created_at)}</time>
              {#if message.ttfb_ms != null}<code>TTFB {message.ttfb_ms} ms</code>{/if}
            </header>
            <!-- Reply lỗi trước byte đầu tiên có content rỗng: bỏ hẳn khung
                 thay vì để lại một hộp trống phía trên dòng lỗi. -->
            {#if message.content || (message.id < 0 && sending)}
              <div class="recorded-content">
                {#if message.role === "assistant"}
                  {@html renderMarkdown(message.content_markdown ?? message.content)}
                {:else}
                  {message.content}
                {/if}
                {#if message.id < 0 && sending}<span class="cursor"></span>{/if}
              </div>
            {/if}
            {#if message.error}<p class="message-error">{message.error}</p>{/if}
            <footer>
              <button onclick={() => copyMessage(message)}>{copiedId === message.id ? "Đã chép" : "Sao chép"}</button>
              {#if message.role === "assistant"}
                <button onclick={() => inspect(message)}>Xem tín hiệu</button>
              {/if}
              <button onclick={() => forkAt(message.seq)}>Tạo nhánh tại đây</button>
              {#if message.artifacts.length}<span>{message.artifacts.length} artifact</span>{/if}
              <code>{message.char_count.toLocaleString()} chars</code>
            </footer>
          </article>
        {/each}
      </div>

      <div class="session-tags">
        <span>Tags</span>
        {#each active.tags as tag (tag)}
          <button title="Gỡ tag" onclick={() => removeTag(tag)}>{tag}<span>×</span></button>
        {/each}
        <input aria-label="Thêm tag" placeholder="+ thêm tag" bind:value={tagDraft} onkeydown={(e) => e.key === "Enter" && addTag()} />
      </div>
    {/if}

    <div class="session-composer">
      <textarea
        aria-label="Tin nhắn mới"
        placeholder={selected.length
          ? `Prompt 1 — chạy trên ${selected.length} target đã chọn…`
          : ($selectedModel ? "Phát tín hiệu tới model…" : "Chưa có model khả dụng")}
        rows="1"
        bind:value={prompt}
        bind:this={promptEl}
        oninput={autoGrow}
        onkeydown={onComposerKeydown}
      ></textarea>

      {#each extraPrompts as item, index (index)}
        <div class="extra-prompt">
          <textarea
            aria-label={`Prompt ${index + 2}`}
            placeholder={`Prompt ${index + 2}`}
            rows="2"
            value={item}
            oninput={(event) => updateExtraPrompt(index, event.currentTarget.value)}
          ></textarea>
          <button type="button" title="Xóa prompt này" onclick={() => removePrompt(index)}>×</button>
        </div>
      {/each}

      <div class="session-composer-controls">
        {#if selected.length}
          <button
            class="composer-scope"
            type="button"
            title="Mỗi target chạy model riêng — chỉnh trong Bàn test"
            onclick={openBench}
          >
            {selected.length} target · {selectedProfiles.length} profile · {selectedDomains.length} domain
          </button>
        {:else}
          <select aria-label="Model" bind:value={$selectedModel}>
            {#each $models as model (model.id)}<option value={model.id}>{model.id}</option>{/each}
          </select>
        {/if}

        <label class="mini-toggle" title="Chạy recipe trong cửa sổ Chromium hiện ra thay vì chạy ẩn">
          <input type="checkbox" bind:checked={$headedBrowser} onchange={onHeadedChange} /><span></span>Hiện cửa sổ
        </label>

        <button
          class="target-trigger"
          class:active={benchOpen}
          class:armed={selected.length > 0}
          type="button"
          title="Chọn profile / domain / account để chạy thử"
          aria-expanded={benchOpen}
          onclick={() => (benchOpen ? (benchOpen = false) : openBench())}
        >
          Bàn test{selected.length ? ` · ${selected.length}` : targets.length ? ` · ${targets.length} sẵn` : ""}
        </button>

        {#if selected.length}
          <button class="ghost-button" type="button" title="Thêm một prompt nữa" onclick={addPrompt}>
            + Prompt
          </button>
        {/if}

        {#if sending}
          <button class="button danger" onclick={() => abortCtrl?.abort()}>Dừng · {elapsed}s</button>
        {:else}
          <button
            class="button"
            disabled={!prompt.trim() || (!selected.length && !$selectedModel)}
            onclick={send}
          >
            {selected.length && promptCount
              ? `Gửi · ${promptCount * (rotationMode === "broadcast" ? selected.length : 1)} req`
              : "Gửi"}
          </button>
        {/if}
      </div>

      {#if selected.length && !benchOpen}
        <div class="target-chips" aria-label="Target đã chọn">
          {#each selected as target (target.account_id)}
            <button type="button" title="Bỏ chọn target này" onclick={() => toggleTarget(target.account_id)}>
              <strong>{target.profile_name}</strong>
              <em>{target.host}</em>
              <span>{target.label}</span>
              <b aria-hidden="true">×</b>
            </button>
          {/each}
        </div>
      {/if}

      <p class="composer-hint">
        {#if selected.length}
          {planLine} · Enter để gửi
        {:else}
          Enter gửi · Shift+Enter xuống dòng · bản ghi được chốt khi stream kết thúc
        {/if}
      </p>
    </div>
  </section>

  {#if benchOpen}
    <aside class="test-bench panel" aria-label="Bàn test">
      <header class="bench-head">
        <div>
          <h2>Bàn test</h2>
          <p>
            {#if targetsLoading}
              Đang nạp…
            {:else}
              {selected.length}/{targets.length} target · {selectedProfiles.length} profile ·
              {selectedDomains.length} domain
            {/if}
          </p>
        </div>
        <button class="icon-button" title="Đóng bàn test" aria-label="Đóng bàn test" onclick={() => (benchOpen = false)}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </header>

      <div class="bench-filters">
        <input
          aria-label="Lọc target"
          placeholder="Lọc profile / domain / account…"
          bind:value={targetQuery}
        />
        <select aria-label="Lọc theo profile" bind:value={profileFilter}>
          <option value="">Mọi profile</option>
          {#each profileNames as name (name)}<option value={name}>{name}</option>{/each}
        </select>
        <select aria-label="Lọc theo domain" bind:value={domainFilter}>
          <option value="">Mọi domain</option>
          {#each domainNames as name (name)}<option value={name}>{name}</option>{/each}
        </select>
      </div>

      <div class="bench-actions">
        <button type="button" disabled={!visibleTargets.some((item) => item.ready)} onclick={toggleAllTargets}>
          {allVisibleSelected ? "Bỏ chọn hết" : "Chọn tất cả"}
        </button>
        <button type="button" onclick={loadTargets}>Nạp lại</button>
        <button
          type="button"
          class="primary"
          disabled={!selected.length || openingTargets}
          onclick={() => prewarmTargets()}
        >
          {openingTargets ? "Đang mở…" : "Mở cửa sổ"}
        </button>
      </div>

      <div class="bench-list">
        {#if targetMeta && !targetMeta.persisted}
          <p class="bench-empty">Kho dữ liệu chưa mở nên chưa có profile nào.</p>
        {:else if targetsLoading && targets.length === 0}
          <p class="bench-empty">Đang nạp ma trận target…</p>
        {:else if targets.length === 0}
          <p class="bench-empty">Chưa có account nào gắn với profile. Thêm tại Integrations → Profiles.</p>
        {:else if visibleTargets.length === 0}
          <p class="bench-empty">Không có target nào khớp bộ lọc.</p>
        {:else}
          {#each targetGroups as group (group.name)}
            {@const head = groupOpen(group.name)}
            {@const state = groupState(group.items)}
            <div class="bench-group">
              <div class="bench-group-head">
                <input
                  id={`bench-group-${group.name}`}
                  type="checkbox"
                  checked={state.all}
                  indeterminate={state.some && !state.all}
                  disabled={!group.items.some((item) => item.ready)}
                  onchange={() => toggleGroup(group.name)}
                />
                <label for={`bench-group-${group.name}`}>{group.name}</label>
                <i class:open={head?.profile_open}>
                  {head?.profile_open ? `${head.profile_tabs} tab` : "chưa mở"}
                </i>
                <span>{countSelectedIn(group.name)}/{group.items.length}</span>
              </div>

              {#each group.items as target (target.account_id)}
                <div
                  class="bench-row"
                  class:selected={selectedTargets.includes(target.account_id)}
                  class:muted={!target.ready}
                >
                  <input
                    id={`target-${target.account_id}`}
                    type="checkbox"
                    disabled={!target.ready}
                    checked={selectedTargets.includes(target.account_id)}
                    onchange={() => toggleTarget(target.account_id)}
                  />
                  <div class="bench-row-body">
                    <label for={`target-${target.account_id}`}>
                      <span class="bench-host">{target.host}</span>
                      <span class="bench-account">{target.label}</span>
                      {#if openedTargets.includes(target.account_id)}
                        <i class="bench-open-flag">đang mở</i>
                      {/if}
                    </label>
                    {#if target.models.length > 1}
                      <select
                        aria-label={`Model cho ${target.host}`}
                        value={modelFor(target)}
                        onchange={(event) => pickModel(target.account_id, event.currentTarget.value)}
                      >
                        {#each target.models as id (id)}<option value={id}>{id}</option>{/each}
                      </select>
                    {:else if target.models.length === 1}
                      <code>{target.models[0]}</code>
                    {:else}
                      <em class="bench-warn-inline">chưa có recipe cho domain này</em>
                    {/if}
                  </div>
                </div>
              {/each}
            </div>
          {/each}
        {/if}
      </div>

      {#if overProfileCap}
        <p class="bench-warn">
          Đang chọn {selectedProfiles.length} profile nhưng trần POOL_MAX_PROFILES là
          {targetMeta?.max_profiles}. Profile rảnh vượt trần có thể bị đóng — tăng ở
          Settings → Browser rồi khởi động lại server.
        </p>
      {/if}
      {#each crowdedProfiles as name (name)}
        <p class="bench-warn">
          Profile “{name}” chọn {countSelectedIn(name)} target nhưng trần chỉ {maxTabsOf(name)} tab.
        </p>
      {/each}

      <div class="bench-mode">
        <span class="bench-label">Cách chia prompt</span>
        <div class="segmented" role="group" aria-label="Cách chia prompt">
          {#each SEND_MODES as mode (mode.id)}
            <button
              type="button"
              class:active={rotationMode === mode.id}
              title={mode.help}
              onclick={() => (rotationMode = mode.id)}
            >
              {mode.label}
            </button>
          {/each}
        </div>
        {#if rotationMode !== "broadcast"}
          <label class="bench-quota">
            Tối đa / account
            <input type="number" min="1" max="100" bind:value={maxRequestsPerAccount} />
          </label>
        {/if}
        <p class="bench-plan">{planLine}</p>
      </div>

      {#if batchJobs.length}
        <div class="bench-jobs">
          <span class="bench-label">Lượt chạy gần nhất</span>
          <div class="batch-job-list">
            {#each batchJobs as job (job.sessionId)}
              <button
                class="batch-job {job.state}"
                type="button"
                title={job.detail || job.prompt}
                onclick={() => openSession(job.sessionId)}
              >
                <span class="batch-job-index">#{job.promptIndex + 1}</span>
                <span class="batch-job-label">{job.label}</span>
                <em>
                  {job.state === "queued" ? "chờ"
                    : job.state === "running" ? "đang chạy"
                    : job.state === "done" ? "xong" : `lỗi · ${job.detail}`}
                </em>
              </button>
            {/each}
          </div>
        </div>
      {/if}
    </aside>
  {/if}

  {#if inspected && active}
    <MessageInspector message={inspected} session={active} onclose={() => (inspected = null)} />
  {/if}
</section>
