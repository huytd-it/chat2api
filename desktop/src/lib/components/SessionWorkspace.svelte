<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { Broadcast, List, X } from "phosphor-svelte";
  import { apiKey, headedBrowser, showToast } from "../stores";
  import { models, selectedModel } from "../sync";
  import {
    deleteSessions,
    exportSession,
    fetchSession,
    fetchSessions,
    fetchTestTargets,
    forkSession,
    openSessionConversation,
    openTestTarget,
    streamChat,
    updateSession,
    type ChatMessage,
    type ChatTarget,
    type SessionDetail,
    type SessionMessage,
    type SessionSummary,
    type TestTarget,
    type TestTargetList,
  } from "../api";
  import MessageInspector from "./MessageInspector.svelte";
  import SessionMessageCard from "./SessionMessageCard.svelte";
  import SessionBank from "./sessions/SessionBank.svelte";
  import SessionComposer from "./sessions/SessionComposer.svelte";
  import SessionConsoleHeader from "./sessions/SessionConsoleHeader.svelte";
  import TestBench from "./sessions/TestBench.svelte";
  import { modelFor, type BatchJob, type RotationMode } from "./sessions/shared";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";

  let sessions = $state<SessionSummary[]>([]);
  let active = $state<SessionDetail | null>(null);
  let inspected = $state<SessionMessage | null>(null);
  let inspectedArtifactId = $state<number | null>(null);
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
  let tagDraft = $state("");
  let targets = $state<TestTarget[]>([]);
  let targetMeta = $state<Omit<TestTargetList, "targets"> | null>(null);
  let targetsLoading = $state(true);
  let benchOpen = $state(false);
  /** Rail danh sách là drawer chồng lên console khi màn hẹp (< lg). */
  let bankOpen = $state(false);
  let selectedTargets = $state<number[]>([]);
  /** Model chọn riêng cho từng account — mở nhiều domain một lượt thì mỗi
   * target chạy recipe của domain nó, không dùng chung ô model ở composer. */
  let targetModels = $state<Record<number, string>>({});
  let openingTargets = $state(false);
  /** Target đã thực sự mở tab — chỉ những cái này mới có live view để xem. */
  let openedTargets = $state<number[]>([]);
  let rotationMode = $state<RotationMode>("broadcast");
  let maxRequestsPerAccount = $state(1);
  let selectedSessions = $state<string[]>([]);
  let deleteDialogOpen = $state(false);
  let deleteScope = $state<"active" | "selected" | "all">("active");
  let deleting = $state(false);
  /** Target server chọn cho lượt đang gửi — đọc từ header nên có ngay trước khi
   * có delta đầu tiên, tức là "đang gửi tới đâu" hiện được trong lúc còn chờ. */
  let liveTarget = $state<ChatTarget | null>(null);
  let openingConversation = $state(false);

  let batchJobs = $state<BatchJob[]>([]);
  let listTimer: ReturnType<typeof setTimeout> | null = null;
  let ticker: ReturnType<typeof setInterval> | null = null;
  let abortCtrl: AbortController | null = null;
  let traceEl = $state<HTMLDivElement | undefined>();
  /** Chỉ cần đúng phần instance được component export ra. */
  let composer = $state<{ focusPrompt: () => void } | undefined>();

  const visibleMessages = $derived(active?.messages ?? []);

  const selected = $derived(
    selectedTargets
      .map((id) => targets.find((item) => item.account_id === id))
      .filter((item): item is TestTarget => Boolean(item)),
  );
  const selectedProfiles = $derived([...new Set(selected.map((item) => item.profile_name))]);

  const promptCount = $derived([prompt, ...extraPrompts].filter((item) => item.trim()).length);

  const batchCapacity = $derived(
    rotationMode === "broadcast"
      ? selected.length
      : selected.length * Math.max(1, Math.floor(Number(maxRequestsPerAccount) || 1)),
  );

  /** Một dòng nói đúng cái sắp xảy ra — người dùng không phải tự nhân nhẩm. */
  const planLine = $derived(
    rotationMode === "broadcast"
      ? `${promptCount} prompt × ${selected.length} target = ${promptCount * selected.length} request`
      : `${promptCount}/${batchCapacity} prompt · ${
          rotationMode === "round_robin" ? "chia vòng tròn" : "lấp đầy từng target"
        }`,
  );

  /** Bàn test và trình xem message dùng chung một rail bên phải. */
  function openBench() {
    benchOpen = true;
    inspected = null;
  }

  function inspect(message: SessionMessage) {
    inspected = message;
    inspectedArtifactId = null;
    benchOpen = false;
  }

  function inspectArtifact(message: SessionMessage, artifactId: number) {
    inspected = message;
    inspectedArtifactId = artifactId;
    benchOpen = false;
  }

  async function openConversation(sessionId: string) {
    if (openingConversation) return;
    openingConversation = true;
    try {
      const result = await openSessionConversation($apiKey, sessionId);
      showToast(`Đã mở hội thoại trong profile ${result.profile}.`);
    } catch (error) {
      showToast("Không mở được hội thoại: " + (error as Error).message);
    } finally {
      openingConversation = false;
    }
  }

  async function copyConversationUrl(url: string) {
    await navigator.clipboard.writeText(url);
    showToast("Đã chép link hội thoại.");
  }

  async function loadList(preserve = true) {
    loadingList = true;
    try {
      sessions = await fetchSessions($apiKey, query.trim(), modelFilter, archived);
      const available = new Set(sessions.map((item) => item.id));
      selectedSessions = selectedSessions.filter((id) => available.has(id));
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
    bankOpen = false;
    try {
      active = await fetchSession($apiKey, id);
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
    bankOpen = false;
    setTimeout(() => composer?.focusPrompt());
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
    await applySelection(
      selectedTargets.includes(id)
        ? selectedTargets.filter((item) => item !== id)
        : [...selectedTargets, id],
    );
  }

  async function toggleMany(ids: number[]) {
    const usable = ids.filter((id) => targets.find((item) => item.account_id === id)?.ready);
    const all = usable.length > 0 && usable.every((id) => selectedTargets.includes(id));
    await applySelection(
      all
        ? selectedTargets.filter((id) => !usable.includes(id))
        : [...selectedTargets, ...usable.filter((id) => !selectedTargets.includes(id))],
    );
  }

  function pickModel(accountId: number, model: string) {
    targetModels = { ...targetModels, [accountId]: model };
  }

  async function prewarmTargets(ids = selectedTargets) {
    const list = targets.filter((item) => ids.includes(item.account_id) && item.ready);
    if (!list.length || openingTargets) return;
    openingTargets = true;
    try {
      // Mỗi target một tab riêng nên mở song song được; server tuần tự hoá phần
      // launch profile bằng khoá riêng của nó.
      const results = await Promise.allSettled(
        list.map((item) => openTestTarget($apiKey, modelFor(item, targetModels), item.account_id)),
      );
      const opened = list
        .filter((_, index) => results[index].status === "fulfilled")
        .map((item) => item.account_id);
      openedTargets = [...new Set([...openedTargets, ...opened])];
      const failedIndex = results.findIndex((result) => result.status === "rejected");
      if (failedIndex >= 0) {
        const reason = (results[failedIndex] as PromiseRejectedResult).reason;
        const item = list[failedIndex];
        showToast(
          `Mở được ${opened.length}/${list.length} target. ` +
            `${item.profile_name}/${item.host}: ${reason?.message ?? reason}`,
        );
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
        model: modelFor(target, targetModels),
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
      showToast(
        `${prompts.length} prompt vượt sức chứa ${list.length * quota}. ` +
          "Tăng max request/account, chọn thêm target, hoặc đổi sang Broadcast.",
      );
      return;
    }
    const missing = list.find((item) => !modelFor(item, targetModels));
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
    const results = await Promise.allSettled(
      jobs.map(async (job, index) => {
        updateJob(index, "running");
        await streamChat(
          $apiKey,
          job.model,
          [{ role: "user", content: job.prompt }],
          () => {},
          controllers[index].signal,
          $headedBrowser,
          job.sessionId,
          undefined,
          job.accountId,
        );
        updateJob(index, "done");
      }),
    );
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
    showToast(
      failed
        ? `Hoàn tất ${results.length - failed}/${results.length} request.`
        : `Hoàn tất ${results.length} request trên ${selectedProfiles.length} profile.`,
    );
    sending = false;
    abortCtrl = null;
    if (ticker) clearInterval(ticker);
    ticker = null;
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
    sending = true;
    elapsed = 0;
    ticker = setInterval(() => (elapsed += 1), 1000);
    const existingId = active?.id ?? crypto.randomUUID().replaceAll("-", "");
    const outgoing = [...history(), { role: "user" as const, content: text }];

    // Optimistic trace: phần lưu bền được nạp lại từ server ngay khi stream đóng.
    const temporary: SessionMessage = {
      id: -Date.now(),
      seq: visibleMessages.length,
      role: "user",
      content: text,
      content_markdown: null,
      content_html: null,
      reasoning: null,
      finish_reason: null,
      error: null,
      ttfb_ms: null,
      duration_ms: null,
      char_count: text.length,
      created_at: Date.now(),
      artifacts: [],
      request: null,
    };
    const reply: SessionMessage = {
      ...temporary,
      id: temporary.id - 1,
      seq: temporary.seq + 1,
      role: "assistant",
      content: "",
      char_count: 0,
    };
    if (active) active.messages.push(temporary, reply);

    liveTarget = null;
    abortCtrl = new AbortController();
    try {
      await streamChat(
        $apiKey,
        $selectedModel,
        outgoing,
        (delta) => {
          reply.content += delta;
          reply.char_count = reply.content.length;
          if (traceEl) traceEl.scrollTop = traceEl.scrollHeight;
        },
        abortCtrl.signal,
        $headedBrowser,
        existingId,
        () => {},
        undefined,
        (target) => (liveTarget = target),
      );
      await openSession(existingId);
      await loadList();
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        showToast("Request lỗi: " + (error as Error).message);
      }
      try {
        await openSession(existingId);
      } catch {
        /* session có thể chưa được tạo */
      }
      await loadList();
    } finally {
      sending = false;
      abortCtrl = null;
      if (ticker) clearInterval(ticker);
      ticker = null;
    }
  }

  async function renameSession(title: string) {
    if (!active) return;
    active = await updateSession($apiKey, active.id, { title });
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
    active = await updateSession($apiKey, active.id, {
      tags: active.tags.filter((item) => item !== tag),
    });
  }

  async function archiveActive() {
    if (!active) return;
    await updateSession($apiKey, active.id, { archived: !active.archived });
    showToast(active.archived ? "Đã đưa session về hộp thư" : "Đã lưu trữ session");
    active = null;
    inspected = null;
    await loadList(false);
  }

  function toggleSession(id: string) {
    selectedSessions = selectedSessions.includes(id)
      ? selectedSessions.filter((item) => item !== id)
      : [...selectedSessions, id];
  }

  function setAllSessions(checked: boolean) {
    selectedSessions = checked ? sessions.map((item) => item.id) : [];
  }

  function confirmDelete(scope: "active" | "selected" | "all") {
    if (scope === "active" && !active) return;
    if (scope === "selected" && !selectedSessions.length) return;
    if (scope === "all" && !sessions.length) return;
    deleteScope = scope;
    deleteDialogOpen = true;
  }

  async function removeSessions() {
    const ids =
      deleteScope === "active"
        ? active
          ? [active.id]
          : []
        : deleteScope === "selected"
          ? selectedSessions
          : sessions.map((item) => item.id);
    if (!ids.length || deleting) return;
    deleting = true;
    try {
      const deleted = await deleteSessions(
        $apiKey,
        deleteScope === "all" ? { all: true } : { ids },
      );
      selectedSessions = [];
      if (active && (deleteScope === "all" || ids.includes(active.id))) {
        active = null;
        inspected = null;
      }
      deleteDialogOpen = false;
      await loadList(false);
      showToast(`Đã xóa ${deleted} session.`);
    } catch (error) {
      showToast("Không xóa được session: " + (error as Error).message);
    } finally {
      deleting = false;
    }
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

<div class="relative flex h-full min-h-0 w-full overflow-hidden bg-background">
  {#if bankOpen}
    <!-- Nền mờ chỉ tồn tại ở bề ngang hẹp, nơi rail trái đang là drawer. -->
    <button
      type="button"
      class="absolute inset-0 z-20 bg-foreground/25 lg:hidden"
      aria-label="Đóng danh sách sessions"
      onclick={() => (bankOpen = false)}
    ></button>
  {/if}

  <div
    class="absolute inset-y-0 left-0 z-30 w-72 max-w-[85vw] transition-transform duration-200 ease-out
      lg:static lg:z-auto lg:w-72 lg:translate-x-0 lg:shadow-none
      {bankOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full'}"
  >
    <SessionBank
      {sessions}
      activeId={active?.id ?? null}
      selectedIds={selectedSessions}
      loading={loadingList}
      bind:query
      bind:modelFilter
      bind:archived
      onSearch={scheduleSearch}
      onFilterChange={() => loadList(false)}
      onNew={newSession}
      onOpen={openSession}
      onToggle={toggleSession}
      onSelectAll={setAllSessions}
      onDeleteSelected={() => confirmDelete("selected")}
      onDeleteAll={() => confirmDelete("all")}
      onClose={() => (bankOpen = false)}
    />
  </div>

  <!-- section chứ không main: layout shell đã có một <main>, và quy tắc CSS
       toàn cục cho `main` từng rơi vào đây làm console bị căn giữa. -->
  <section class="flex min-w-0 flex-1 flex-col bg-card" aria-label="Bản ghi phiên">
    {#if active && !loadingDetail}
      <SessionConsoleHeader
        session={active}
        {openingConversation}
        onRename={renameSession}
        onTogglePin={togglePin}
        onArchive={archiveActive}
        onExport={saveExport}
        onDelete={() => confirmDelete("active")}
        onOpenConversation={() => active && openConversation(active.id)}
        onToggleBank={() => (bankOpen = !bankOpen)}
      />
    {:else}
      <header class="flex flex-none items-center gap-2 border-b border-border px-3 py-2.5 lg:hidden">
        <Button size="icon-sm" variant="ghost" aria-label="Mở danh sách sessions" onclick={() => (bankOpen = true)}>
          <List />
        </Button>
        <span class="text-sm font-medium">Sessions</span>
      </header>
    {/if}

    {#if loadingDetail}
      <div class="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
        <span class="size-2 animate-pulse rounded-full bg-warning" aria-hidden="true"></span>
        Đang đọc bản ghi…
      </div>
    {:else if !active}
      <div class="flex flex-1 flex-col items-center justify-center px-6 py-10 text-center">
        <div class="mb-3 grid size-12 place-items-center rounded-xl bg-primary/10 text-primary">
          <Broadcast size={24} aria-hidden="true" />
        </div>
        <h2 class="display-face text-lg font-semibold tracking-[-0.02em]">Đầu dò sẵn sàng</h2>
        <p class="mt-1.5 max-w-[48ch] text-[13px] leading-relaxed text-muted-foreground">
          Chọn một session để kiểm tra bản ghi, hoặc gõ vào ô bên dưới để phát tín hiệu mới. Mọi
          lượt chat từ API đều được lưu tự động.
        </p>
      </div>
    {:else}
      <div
        class="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background px-4 py-6 md:px-8 lg:px-12"
        bind:this={traceEl}
        aria-live="polite"
      >
        <div
          class="mb-6 flex flex-none items-center gap-2.5 self-stretch font-data text-[10px] text-muted-foreground"
        >
          <span class="h-px flex-1 bg-border" aria-hidden="true"></span>
          <span>SESSION START</span>
          <time datetime={new Date(active.created_at).toISOString()}>
            {new Date(active.created_at).toLocaleString()}
          </time>
          <span class="h-px flex-1 bg-border" aria-hidden="true"></span>
        </div>

        {#each visibleMessages as message (message.id)}
          <SessionMessageCard
            {message}
            model={active.model_public_id}
            {sending}
            copied={copiedId === message.id}
            oncopy={() => copyMessage(message)}
            oninspect={message.role === "assistant" ? () => inspect(message) : undefined}
            onfork={() => forkAt(message.seq)}
            onartifact={(artifactId) => inspectArtifact(message, artifactId)}
            oncopylink={copyConversationUrl}
          />
        {/each}
      </div>

      <div
        class="flex min-h-10 flex-none items-center gap-1.5 overflow-x-auto border-t border-border px-3 py-1.5 md:px-6"
      >
        <span class="flex-none text-[11px] text-muted-foreground">Tags</span>
        {#each active.tags as tag (tag)}
          <button
            type="button"
            class="flex flex-none items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 text-[11px] text-muted-foreground transition-colors hover:border-destructive/40 hover:text-foreground"
            title="Gỡ tag"
            onclick={() => removeTag(tag)}
          >
            {tag}
            <X size={9} aria-hidden="true" />
          </button>
        {/each}
        <Input
          class="h-7 w-28 flex-none border-transparent bg-transparent text-xs"
          aria-label="Thêm tag"
          placeholder="+ thêm tag"
          bind:value={tagDraft}
          onkeydown={(event) => event.key === "Enter" && addTag()}
        />
      </div>
    {/if}

    <SessionComposer
      bind:this={composer}
      bind:prompt
      bind:extraPrompts
      {selected}
      targetCount={targets.length}
      {benchOpen}
      {sending}
      {elapsed}
      {liveTarget}
      {planLine}
      {promptCount}
      {rotationMode}
      onSend={send}
      onStop={() => abortCtrl?.abort()}
      onToggleBench={() => (benchOpen ? (benchOpen = false) : openBench())}
      onOpenBench={openBench}
      {onHeadedChange}
      onRemoveTarget={toggleTarget}
    />
  </section>

  {#if benchOpen}
    <div
      class="absolute inset-y-0 right-0 z-30 w-88 max-w-[92vw] shadow-2xl xl:static xl:z-auto xl:shadow-none"
    >
      <TestBench
        {targets}
        meta={targetMeta}
        loading={targetsLoading}
        selectedIds={selectedTargets}
        openedIds={openedTargets}
        {targetModels}
        bind:rotationMode
        bind:maxRequestsPerAccount
        {planLine}
        {batchJobs}
        opening={openingTargets}
        onClose={() => (benchOpen = false)}
        onToggle={toggleTarget}
        onToggleMany={toggleMany}
        onReload={loadTargets}
        onOpenWindows={() => prewarmTargets()}
        onPickModel={pickModel}
        onOpenSession={openSession}
      />
    </div>
  {:else if inspected && active}
    <div
      class="absolute inset-y-0 right-0 z-30 w-88 max-w-[92vw] shadow-2xl xl:static xl:z-auto xl:shadow-none"
    >
      <MessageInspector
        message={inspected}
        session={active}
        artifactId={inspectedArtifactId}
        onclose={() => (inspected = null)}
        onopen={() => active && openConversation(active.id)}
      />
    </div>
  {/if}
</div>

<AlertDialog.Root bind:open={deleteDialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {deleteScope === "all"
          ? "Xóa tất cả session?"
          : deleteScope === "selected"
            ? "Xóa các session đã chọn?"
            : "Xóa session?"}
      </AlertDialog.Title>
      <AlertDialog.Description>
        {#if deleteScope === "all"}
          Toàn bộ {sessions.length} session trong bộ lọc hiện tại và các message của chúng sẽ bị xóa
          vĩnh viễn.
        {:else if deleteScope === "selected"}
          {selectedSessions.length} session đã chọn và các message của chúng sẽ bị xóa vĩnh viễn.
        {:else}
          “{active?.title || "Session"}” và toàn bộ message sẽ bị xóa vĩnh viễn.
        {/if}
        Thao tác này không thể hoàn tác.
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={deleting}>Hủy</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={deleting} onclick={removeSessions}>
        {deleting ? "Đang xóa…" : "Xóa vĩnh viễn"}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
