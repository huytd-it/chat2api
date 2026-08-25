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
    forkSession,
    streamChat,
    updateSession,
    type ChatMessage,
    type SessionDetail,
    type SessionMessage,
    type SessionSummary,
  } from "../api";
  import { renderMarkdown } from "../markdown";
  import LiveView from "./LiveView.svelte";
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
  let sending = $state(false);
  let elapsed = $state(0);
  let watchId = $state<string | null>(null);
  let copiedId = $state<number | null>(null);
  let editingTitle = $state(false);
  let titleDraft = $state("");
  let tagDraft = $state("");
  let listTimer: ReturnType<typeof setTimeout> | null = null;
  let ticker: ReturnType<typeof setInterval> | null = null;
  let abortCtrl: AbortController | null = null;
  let traceEl = $state<HTMLDivElement | undefined>();
  let promptEl: HTMLTextAreaElement | undefined;

  const visibleMessages = $derived(active?.messages ?? []);

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
        (id) => (watchId = id),
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
      watchId = null;
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

<section class="view sessions-workbench" class:inspector-open={Boolean(inspected)}>
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

  <main class="session-console panel">
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

      <LiveView {watchId} />

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
                <button onclick={() => (inspected = message)}>Xem tín hiệu</button>
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
        placeholder={$selectedModel ? "Phát tín hiệu tới model…" : "Chưa có model khả dụng"}
        rows="1"
        bind:value={prompt}
        bind:this={promptEl}
        oninput={autoGrow}
        onkeydown={onComposerKeydown}
      ></textarea>
      <div class="session-composer-controls">
        <select aria-label="Model" bind:value={$selectedModel}>
          {#each $models as model (model.id)}<option value={model.id}>{model.id}</option>{/each}
        </select>
        <label class="mini-toggle" title="Hiện browser khi recipe chạy">
          <input type="checkbox" bind:checked={$headedBrowser} /><span></span>Browser
        </label>
        {#if sending}
          <button class="button danger" onclick={() => abortCtrl?.abort()}>Dừng · {elapsed}s</button>
        {:else}
          <button class="button" disabled={!prompt.trim() || !$selectedModel} onclick={send}>Gửi</button>
        {/if}
      </div>
      <p>Enter gửi · Shift+Enter xuống dòng · bản ghi được chốt khi stream kết thúc</p>
    </div>
  </main>

  {#if inspected && active}
    <MessageInspector message={inspected} session={active} onclose={() => (inspected = null)} />
  {/if}
</section>
