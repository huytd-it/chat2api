<script lang="ts">
  import {
    BracketsCurlyIcon,
    CheckIcon,
    CopyIcon,
    GitBranchIcon,
    MagnifyingGlassIcon,
  } from "phosphor-svelte";
  import type { SessionMessage } from "../api";
  import { renderMarkdown } from "../markdown";

  let {
    message,
    model,
    markdownMode,
    sending = false,
    copied = false,
    oncopy,
    oninspect,
    onfork,
    onartifact,
    oncopylink,
  }: {
    message: SessionMessage;
    model: string;
    markdownMode: "rendered" | "raw";
    sending?: boolean;
    copied?: boolean;
    oncopy: () => void;
    oninspect?: () => void;
    onfork: () => void;
    onartifact?: (artifactId: number) => void;
    oncopylink?: (url: string) => void;
  } = $props();

  const target = $derived([
    message.request?.profile_name,
    message.request?.account_host,
    message.request?.account_label,
  ].filter(Boolean).join(" · "));
  const conversationUrl = $derived(message.request?.conversation_url ?? "");

  function formatTime(ts: number): string {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
</script>

<article class="recorded-message {message.role}" class:fault={Boolean(message.error)}>
  <header>
    <span class="role-badge">{message.role === "user" ? "IN" : message.role === "assistant" ? "OUT" : message.role.toUpperCase()}</span>
    <span>{message.role === "user" ? "Bạn" : message.role === "assistant" ? model : message.role}</span>
    <time datetime={new Date(message.created_at).toISOString()}>{formatTime(message.created_at)}</time>
    {#if message.ttfb_ms != null}<code>TTFB {message.ttfb_ms} ms</code>{/if}
  </header>

  {#if message.reasoning}
    <details class="message-reasoning">
      <summary>
        <MagnifyingGlassIcon size={14} aria-hidden="true" />
        Quá trình xử lý
      </summary>
      <div>{@html renderMarkdown(message.reasoning)}</div>
    </details>
  {/if}

  {#if message.content || (message.id < 0 && sending)}
    <div class="recorded-content">
      {#if message.role === "assistant"}
        {#if markdownMode === "raw"}
          <pre class="raw-markdown">{message.content_markdown ?? message.content}</pre>
        {:else}
          {@html renderMarkdown(message.content_markdown ?? message.content)}
        {/if}
      {:else}
        {message.content}
      {/if}
      {#if message.id < 0 && sending}<span class="cursor"></span>{/if}
    </div>
  {/if}

  {#if message.artifacts.length}
    <div class="message-artifacts" aria-label="Artifact trong câu trả lời">
      {#each message.artifacts as artifact (artifact.id)}
        <button type="button" onclick={() => onartifact?.(artifact.id)}>
          <span class="artifact-icon"><BracketsCurlyIcon size={16} aria-hidden="true" /></span>
          <span>
            <strong>{artifact.title || artifact.language || `Artifact ${artifact.idx + 1}`}</strong>
            <small>{artifact.kind}{artifact.language ? ` · ${artifact.language}` : ""}</small>
          </span>
        </button>
      {/each}
    </div>
  {/if}

  {#if message.error}<p class="message-error" role="alert">{message.error}</p>{/if}

  <footer aria-label="Thao tác message">
    <button title="Sao chép nội dung" onclick={oncopy}>
      {#if copied}<CheckIcon size={13} aria-hidden="true" />Đã chép{:else}<CopyIcon size={13} aria-hidden="true" />Sao chép{/if}
    </button>
    {#if message.role === "assistant" && oninspect}
      <button title="Xem dữ liệu và thời gian phản hồi" onclick={oninspect}>
        <MagnifyingGlassIcon size={13} aria-hidden="true" />Xem tín hiệu
      </button>
    {/if}
    <button title="Tạo session mới tới message này" onclick={onfork}>
      <GitBranchIcon size={13} aria-hidden="true" />Tạo nhánh
    </button>
    {#if target}<span class="message-target" title="Request này chạy trên profile/account nào">→ {target}</span>{/if}
    {#if conversationUrl}
      <button class="message-link" title={`Chép link: ${conversationUrl}`} onclick={() => oncopylink?.(conversationUrl)}>Chép link</button>
    {/if}
    <code>{message.char_count.toLocaleString()} chars</code>
  </footer>
</article>
