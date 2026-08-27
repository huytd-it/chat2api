<script lang="ts">
  import { renderMarkdown } from "../markdown";
  import type { SessionDetail, SessionMessage } from "../api";

  let {
    message,
    session,
    artifactId = null,
    onclose,
    onopen,
  }: {
    message: SessionMessage;
    session: SessionDetail;
    artifactId?: number | null;
    onclose: () => void;
    /** Mở lại hội thoại trong đúng profile đã chạy request này. */
    onopen?: () => void;
  } = $props();

  /** 'profile · host · account' của ĐÚNG request sinh ra message này — không
   * phải của session: một session có thể trải qua nhiều account. */
  const target = $derived([
    message.request?.profile_name,
    message.request?.account_host,
    message.request?.account_label,
  ].filter(Boolean).join(" · "));
  const conversationUrl = $derived(message.request?.conversation_url ?? "");

  type Tab = "pretty" | "markdown" | "html" | "json" | "artifact";
  let tab = $state<Tab>("pretty");
  let copied = $state(false);

  const markdown = $derived(message.content_markdown ?? message.content);
  const artifact = $derived(message.artifacts.find((item) => item.id === artifactId) ?? message.artifacts[0]);
  const responseJson = $derived(JSON.stringify({
    id: `chatcmpl-session-${message.id}`,
    object: "chat.completion",
    created: Math.floor(message.created_at / 1000),
    model: session.model_public_id,
    choices: [{
      index: 0,
      message: { role: message.role, content: message.content },
      finish_reason: message.finish_reason,
    }],
  }, null, 2));

  function safeHtmlDocument(raw: string): string {
    const escapedCsp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:;">`;
    const styles = `<style>html{color-scheme:dark}body{margin:20px;background:#0a0d0a;color:#dfe3df;font:15px/1.6 Archivo,system-ui,sans-serif}pre,code{font-family:Consolas,monospace;white-space:pre-wrap}a{color:#57e08a}img{max-width:100%}</style>`;
    return `<!doctype html><meta charset="utf-8">${escapedCsp}${styles}${raw}`;
  }

  async function copyCurrent() {
    const value = tab === "json" ? responseJson : tab === "html"
      ? (message.content_html ?? "") : tab === "artifact" ? (artifact?.body ?? "") : markdown;
    if (!value) return;
    await navigator.clipboard.writeText(value);
    copied = true;
    setTimeout(() => (copied = false), 1400);
  }

  $effect(() => {
    if (artifactId != null && message.artifacts.some((item) => item.id === artifactId)) tab = "artifact";
  });
</script>

<aside class="message-inspector" aria-label="Trình xem message">
  <header class="inspector-head">
    <div>
      <h2>Trình xem tín hiệu</h2>
      <p>Message <span>#{message.seq}</span> · {message.char_count.toLocaleString()} ký tự</p>
    </div>
    <button class="icon-button" aria-label="Đóng trình xem" title="Đóng" onclick={onclose}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" /></svg>
    </button>
  </header>

  <div class="inspector-tabs" role="tablist" aria-label="Biểu diễn message">
    {#each ["pretty", "markdown", "html", "json", ...(message.artifacts.length ? ["artifact"] : [])] as name}
      <button
        role="tab"
        aria-selected={tab === name}
        disabled={name === "html" && !message.content_html}
        onclick={() => (tab = name as Tab)}
      >{name}</button>
    {/each}
  </div>

  <div class="inspector-body">
    {#if tab === "pretty"}
      <article class="inspector-pretty">{@html renderMarkdown(markdown)}</article>
    {:else if tab === "markdown"}
      <pre class="inspector-source">{markdown}</pre>
    {:else if tab === "html"}
      {#if message.content_html}
        <iframe
          class="html-frame"
          title="HTML gốc đã sandbox"
          sandbox="allow-same-origin"
          srcdoc={safeHtmlDocument(message.content_html)}
        ></iframe>
      {:else}
        <div class="inspector-empty">
          Recipe này chưa bật <code>response.capture_html</code> khi message được tạo.
        </div>
      {/if}
    {:else if tab === "json"}
      <pre class="inspector-source">{responseJson}</pre>
    {:else if artifact}
      <section class="inspector-artifact">
        <header>
          <strong>{artifact.title || artifact.language || `Artifact ${artifact.idx + 1}`}</strong>
          <span>{artifact.kind}{artifact.language ? ` · ${artifact.language}` : ""}</span>
        </header>
        <pre class="inspector-source"><code>{artifact.body}</code></pre>
      </section>
    {/if}
  </div>

  {#if target || conversationUrl}
    <div class="inspector-target">
      <span class="target-label">Đã gửi tới</span>
      <strong>{target || "—"}</strong>
      {#if conversationUrl}
        <button class="tool-button" title={conversationUrl} onclick={onopen}>Xem trực tiếp</button>
      {/if}
    </div>
  {/if}

  <footer class="inspector-foot">
    <div class="signal-facts">
      <span>TTFB <strong>{message.ttfb_ms == null ? "—" : `${message.ttfb_ms} ms`}</strong></span>
      <span>Tổng <strong>{message.duration_ms == null ? "—" : `${message.duration_ms} ms`}</strong></span>
      {#if message.request?.fallback_used}<span class="amber-fact">Fallback</span>{/if}
    </div>
    <button class="tool-button" disabled={tab === "html" && !message.content_html} onclick={copyCurrent}>
      {copied ? "Đã chép" : "Sao chép"}
    </button>
  </footer>
</aside>
