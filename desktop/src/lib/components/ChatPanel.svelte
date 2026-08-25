<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, headedPlayground } from "../stores";
  import { models, selectedModel } from "../sync";
  import { streamChat, type ChatMessage } from "../api";
  import { renderMarkdown } from "../markdown";
  import LiveView from "./LiveView.svelte";

  interface Msg {
    role: "user" | "assistant" | "err";
    text: string;
    ts: number;
    streaming?: boolean;
    stopped?: boolean;
  }

  let messages = $state<Msg[]>([]);
  let prompt = $state("");
  let sending = $state(false);
  let elapsed = $state(0);
  let latency = $state("");
  let watchId = $state<string | null>(null);
  let copiedIndex = $state<number | null>(null);
  let chatEl: HTMLDivElement | undefined;
  let promptEl: HTMLTextAreaElement | undefined;
  let stickToBottom = $state(true);

  let abortCtrl: AbortController | null = null;
  let ticker: ReturnType<typeof setInterval> | null = null;

  const suggestions = [
    { label: "Khám phá model", prompt: "Giới thiệu ngắn gọn bạn có thể làm gì." },
    { label: "Thử sinh code", prompt: "Viết một hàm Python kiểm tra URL hợp lệ." },
    { label: "Dịch văn bản", prompt: 'Dịch sang tiếng Anh: "Cầu thủ ghi bàn ở phút 89."' },
  ];

  // Svelte 5 $state deep-proxy: đọc lại phần tử vừa push để mutation được track.
  function pushMessage(msg: Msg): Msg {
    messages.push(msg);
    return messages[messages.length - 1];
  }

  function fmtTime(ts: number): string {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function scrollToEnd(force = false) {
    if (!chatEl) return;
    if (!force && !stickToBottom) return;
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function onChatScroll() {
    if (!chatEl) return;
    stickToBottom = chatEl.scrollHeight - chatEl.scrollTop - chatEl.clientHeight < 80;
  }

  function autoGrow() {
    if (!promptEl) return;
    promptEl.style.height = "auto";
    promptEl.style.height = Math.min(promptEl.scrollHeight, 200) + "px";
  }

  function startTicker() {
    elapsed = 0;
    ticker = setInterval(() => (elapsed += 1), 1000);
  }

  function stopTicker() {
    if (ticker !== null) {
      clearInterval(ticker);
      ticker = null;
    }
  }

  async function send() {
    const text = prompt.trim();
    if (!text || !$selectedModel || sending) return;
    prompt = "";
    autoGrow();
    latency = "";
    stickToBottom = true;

    pushMessage({ role: "user", text, ts: Date.now() });
    pushMessage({ role: "assistant", text: "", ts: Date.now(), streaming: true });
    const reply = messages[messages.length - 1];

    sending = true;
    startTicker();
    scrollToEnd(true);
    const t0 = performance.now();

    // Gửi toàn bộ hội thoại (bỏ bubble lỗi) như một chat app thật.
    const history: ChatMessage[] = messages
      .filter((m) => m.role !== "err" && !m.streaming)
      .map((m): ChatMessage => ({
        role: m.role === "user" ? "user" : "assistant",
        content: m.text,
      }));

    abortCtrl = new AbortController();
    try {
      await streamChat($apiKey, $selectedModel, history, (delta) => {
        reply.text += delta;
        scrollToEnd();
      }, abortCtrl.signal, $headedPlayground, (id) => { watchId = id; });
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        reply.stopped = true;
        if (!reply.text) reply.text = "_Đã dừng sinh phản hồi._";
      } else {
        reply.role = "err";
        reply.text = String((e as Error).message ?? e);
      }
    } finally {
      sending = false;
      stopTicker();
      abortCtrl = null;
      watchId = null;
      reply.streaming = false;
      latency = Math.round(performance.now() - t0) + " ms";
      scrollToEnd();
    }
  }

  function stop() {
    abortCtrl?.abort();
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function clearChat() {
    if (sending) stop();
    messages = [];
    latency = "";
    elapsed = 0;
    stickToBottom = true;
  }

  async function copyMsg(i: number) {
    const msg = messages[i];
    if (!msg?.text) return;
    try {
      await navigator.clipboard.writeText(msg.text);
      copiedIndex = i;
      setTimeout(() => (copiedIndex = null), 1400);
    } catch { /* clipboard bị chặn — bỏ qua */ }
  }

  onMount(() => {
    promptEl?.focus();
    return () => stopTicker();
  });
</script>

<div class="panel chat-panel">
  <div class="panel-head">
    <div>
      <h1>API playground</h1>
      <p>
        {#if $selectedModel}
          Đang chat với <span class="model-chip">{$selectedModel}</span> · lịch sử hội thoại được gửi kèm
        {:else}
          Chọn model ở sidebar để bắt đầu
        {/if}
      </p>
    </div>
    <div class="head-status">
      {#if sending}
        <span class="running-pill" title="Request đang chạy">
          <span class="spin-dot"></span>
          {elapsed}s
        </span>
      {:else if latency}
        <span class="latency" aria-live="polite">{latency}</span>
      {/if}
    </div>
  </div>

  <LiveView {watchId} />

  <div
    class="chat"
    aria-live="polite"
    bind:this={chatEl}
    onscroll={onChatScroll}
  >
    {#if messages.length === 0}
      <div class="chat-empty">
        <h2>Kiểm thử model,<br>không cần rời ứng dụng.</h2>
        <p>Nhập prompt và xem phản hồi stream trực tiếp từ provider. Toàn bộ hội thoại được gửi kèm từng lượt.</p>
        <div class="suggestions">
          {#each suggestions as s (s.label)}
            <button class="suggestion" onclick={() => { prompt = s.prompt; autoGrow(); promptEl?.focus(); }}>
              {s.label}
            </button>
          {/each}
        </div>
      </div>
    {:else}
      {#each messages as msg, i (i)}
        <div class="msg-row {msg.role}">
          <div class="avatar" aria-hidden="true">
            {#if msg.role === "user"}B{:else if msg.role === "err"}!{:else}A{/if}
          </div>
          <div class="msg-body">
            <div
              class="msg {msg.role}"
              class:streaming={msg.streaming && !msg.text}
            >
              {#if msg.role === "assistant"}
                {@html renderMarkdown(msg.text)}
              {:else}
                {msg.text}
              {/if}
              {#if msg.streaming}
                <span class="cursor" aria-hidden="true"></span>
              {/if}
              {#if msg.stopped}
                <span class="stopped-note">· đã dừng</span>
              {/if}
            </div>
            <div class="msg-meta">
              <span>{fmtTime(msg.ts)}</span>
              {#if msg.role === "assistant" && msg.text && !msg.streaming}
                <button
                  class="copy-btn"
                  title="Sao chép phản hồi"
                  onclick={() => copyMsg(i)}
                >{copiedIndex === i ? "Đã chép ✓" : "Sao chép"}</button>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    {/if}
  </div>

  <div class="composer">
    <div class="composer-row">
      <textarea
        class="prompt-input"
        aria-label="Tin nhắn"
        placeholder={$selectedModel ? "Nhập tin nhắn cho model..." : "Chưa có model — chọn ở sidebar"}
        rows="1"
        bind:value={prompt}
        bind:this={promptEl}
        onkeydown={onKeydown}
        oninput={autoGrow}
      ></textarea>
      <div class="composer-actions">
        {#if sending}
          <button class="button danger" onclick={stop}>Dừng</button>
        {:else}
          <button class="button" disabled={!$selectedModel || !prompt.trim()} onclick={send}>Gửi</button>
        {/if}
        <button class="button secondary" disabled={messages.length === 0} onclick={clearChat}>Xóa chat</button>
      </div>
    </div>
    <div class="composer-meta">
      <span>{$models.length} model khả dụng</span>
      <span>{sending ? `Đang stream... ${elapsed}s` : "Enter để gửi · Shift+Enter xuống dòng"}</span>
    </div>
  </div>
</div>
