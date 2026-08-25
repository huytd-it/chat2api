<script lang="ts">
  import { apiKey, headedPlayground } from "../stores";
  import { selectedModel } from "../sync";
  import { streamChat } from "../api";
  import LiveView from "./LiveView.svelte";

  interface Msg {
    role: "user" | "assistant" | "err";
    text: string;
  }

  let messages = $state<Msg[]>([]);
  let prompt = $state("");
  let sending = $state(false);
  let latency = $state("");
  let watchId = $state<string | null>(null);
  let chatEl: HTMLDivElement | undefined;

  const suggestions = [
    { label: "Khám phá model", prompt: "Giải thích ngắn gọn model này có thể làm gì." },
    { label: "Thử sinh code", prompt: "Viết một hàm Python kiểm tra URL hợp lệ." },
  ];

  function scrollToEnd() {
    if (chatEl) chatEl.scrollTop = chatEl.scrollHeight;
  }

  async function send() {
    const text = prompt.trim();
    if (!text || !$selectedModel || sending) return;
    prompt = "";
    sending = true;
    messages.push({ role: "user", text });
    messages.push({ role: "assistant", text: "" });
    // Svelte 5 $state arrays deep-proxy their elements on push; mutating the
    // plain object we just pushed wouldn't be tracked, so read back the
    // reactive element itself and mutate that instead.
    const reply = messages[messages.length - 1];
    scrollToEnd();
    const t0 = performance.now();
    try {
      await streamChat($apiKey, $selectedModel, text, (delta) => {
        reply.text += delta;
        scrollToEnd();
      }, undefined, $headedPlayground, (id) => { watchId = id; });
    } catch (e) {
      reply.role = "err";
      reply.text = String((e as Error).message ?? e);
    } finally {
      sending = false;
      watchId = null;
      latency = Math.round(performance.now() - t0) + " ms";
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function clearChat() {
    messages = [];
    latency = "";
  }

  function useSuggestion(text: string) {
    prompt = text;
  }
</script>

<div class="panel chat-panel">
  <div class="panel-head">
    <div>
      <h1>API playground</h1>
      <p>Kiểm thử phản hồi streaming theo thời gian thực</p>
    </div>
    <span class="latency" aria-live="polite">{latency}</span>
  </div>

  <LiveView {watchId} />

  <div class="chat" aria-live="polite" bind:this={chatEl}>
    {#if messages.length === 0}
      <div class="chat-empty">
        <h2>Kiểm thử model, không cần rời trình duyệt.</h2>
        <p>Chọn model, nhập prompt và xem phản hồi được stream trực tiếp từ provider.</p>
        <div class="suggestions">
          {#each suggestions as s (s.label)}
            <button class="suggestion" onclick={() => useSuggestion(s.prompt)}>{s.label}</button>
          {/each}
        </div>
      </div>
    {:else}
      {#each messages as msg, i (i)}
        <div class="msg {msg.role}">{#if msg.text}{msg.text}{/if}</div>
      {/each}
    {/if}
  </div>

  <div class="composer">
    <div class="composer-row">
      <textarea
        class="prompt-input"
        aria-label="Tin nhắn"
        placeholder="Nhập tin nhắn cho model..."
        bind:value={prompt}
        onkeydown={onKeydown}
      ></textarea>
      <div class="composer-actions">
        <button class="button" disabled={sending || !$selectedModel} onclick={send}>Gửi</button>
        <button class="button secondary" onclick={clearChat}>Xóa chat</button>
      </div>
    </div>
    <div class="composer-meta">
      <span>Enter để gửi, Shift + Enter để xuống dòng</span>
      <span>Streaming SSE</span>
    </div>
  </div>
</div>
