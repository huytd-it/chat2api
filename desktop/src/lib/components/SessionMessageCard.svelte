<script lang="ts">
  import {
    BracketsCurlyIcon,
    CheckIcon,
    CopyIcon,
    GitBranchIcon,
    LinkSimpleIcon,
    MagnifyingGlassIcon,
  } from "phosphor-svelte";
  import type { SessionMessage } from "../api";
  import { renderMarkdown } from "../markdown";
  import { Button } from "$lib/components/ui/button";

  let {
    message,
    model,
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
    sending?: boolean;
    copied?: boolean;
    oncopy: () => void;
    oninspect?: () => void;
    onfork: () => void;
    onartifact?: (artifactId: number) => void;
    oncopylink?: (url: string) => void;
  } = $props();

  const isUser = $derived(message.role === "user");
  const streaming = $derived(message.id < 0 && sending);

  const target = $derived(
    [message.request?.profile_name, message.request?.account_host, message.request?.account_label]
      .filter(Boolean)
      .join(" · "),
  );
  const conversationUrl = $derived(message.request?.conversation_url ?? "");

  function formatTime(ts: number): string {
    return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
</script>

<article
  class="group/message mb-6 flex max-w-[min(50rem,85%)] flex-col {isUser
    ? 'items-end self-end'
    : 'items-start self-start'}"
>
  <header
    class="mb-1.5 flex w-full items-center gap-2 text-[11px] text-muted-foreground {isUser
      ? 'flex-row-reverse'
      : ''}"
  >
    <span
      class="inline-flex h-4.5 flex-none items-center rounded px-1.5 font-data text-[9px] font-semibold {isUser
        ? 'bg-primary/15 text-primary'
        : 'bg-muted'}"
    >
      {message.role === "user" ? "IN" : message.role === "assistant" ? "OUT" : message.role.toUpperCase()}
    </span>
    <span class="min-w-0 truncate">
      {message.role === "user" ? "Bạn" : message.role === "assistant" ? model : message.role}
    </span>
    <time
      class="font-data text-[10px] {isUser ? 'mr-auto' : 'ml-auto'}"
      datetime={new Date(message.created_at).toISOString()}
    >
      {formatTime(message.created_at)}
    </time>
    {#if message.ttfb_ms != null}
      <code class="flex-none font-data text-[10px]">TTFB {message.ttfb_ms} ms</code>
    {/if}
  </header>

  {#if message.reasoning}
    <details
      class="mb-2 w-[min(42rem,100%)] overflow-hidden rounded-lg border border-border bg-muted/50 text-muted-foreground"
    >
      <summary
        class="flex min-h-8 cursor-pointer list-none items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-semibold marker:content-none"
      >
        <MagnifyingGlassIcon size={13} aria-hidden="true" />
        Quá trình xử lý
      </summary>
      <div class="md-body max-h-65 overflow-auto border-t border-border px-3 py-2.5 text-xs text-foreground">
        {@html renderMarkdown(message.reasoning)}
      </div>
    </details>
  {/if}

  {#if message.content || streaming}
    <div
      class="md-body max-w-full rounded-xl border border-border px-3.5 py-3 text-sm {isUser
        ? 'bg-primary/8'
        : 'bg-card'}"
    >
      {@html renderMarkdown(message.content_markdown ?? message.content)}
      {#if streaming}
        <span class="ml-0.5 inline-block h-3.5 w-0.5 translate-y-0.5 animate-pulse bg-primary"></span>
      {/if}
    </div>
  {/if}

  {#if message.artifacts.length}
    <div class="mt-1.5 grid w-[min(35rem,100%)] gap-1.5" aria-label="Artifact trong câu trả lời">
      {#each message.artifacts as artifact (artifact.id)}
        <button
          type="button"
          class="flex min-w-0 items-center gap-2.5 rounded-lg border border-border bg-card px-2.5 py-2 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
          onclick={() => onartifact?.(artifact.id)}
        >
          <span class="grid size-7 flex-none place-items-center rounded-md bg-muted text-primary">
            <BracketsCurlyIcon size={16} aria-hidden="true" />
          </span>
          <span class="grid min-w-0">
            <strong class="truncate text-[11px] font-semibold">
              {artifact.title || artifact.language || `Artifact ${artifact.idx + 1}`}
            </strong>
            <small class="truncate font-data text-[9px] text-muted-foreground">
              {artifact.kind}{artifact.language ? ` · ${artifact.language}` : ""}
            </small>
          </span>
        </button>
      {/each}
    </div>
  {/if}

  {#if message.error}
    <p class="mt-1.5 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive" role="alert">
      {message.error}
    </p>
  {/if}

  <footer
    class="mt-1 flex w-full flex-wrap items-center gap-1 opacity-60 transition-opacity group-hover/message:opacity-100 group-focus-within/message:opacity-100 {isUser
      ? 'flex-row-reverse'
      : ''}"
  >
    <Button size="xs" variant="ghost" class="text-muted-foreground" title="Sao chép nội dung" onclick={oncopy}>
      {#if copied}<CheckIcon aria-hidden="true" />Đã chép{:else}<CopyIcon aria-hidden="true" />Sao chép{/if}
    </Button>

    {#if message.role === "assistant" && oninspect}
      <Button
        size="xs"
        variant="ghost"
        class="text-muted-foreground"
        title="Xem dữ liệu và thời gian phản hồi"
        onclick={oninspect}
      >
        <MagnifyingGlassIcon aria-hidden="true" />
        Xem tín hiệu
      </Button>
    {/if}

    <Button
      size="xs"
      variant="ghost"
      class="text-muted-foreground"
      title="Tạo session mới tới message này"
      onclick={onfork}
    >
      <GitBranchIcon aria-hidden="true" />
      Tạo nhánh
    </Button>

    {#if conversationUrl}
      <Button
        size="xs"
        variant="ghost"
        class="text-primary"
        title={`Chép link: ${conversationUrl}`}
        onclick={() => oncopylink?.(conversationUrl)}
      >
        <LinkSimpleIcon aria-hidden="true" />
        Chép link
      </Button>
    {/if}

    <!-- "→ profile · host · account": câu trả lời cho "request này đi tới đâu". -->
    {#if target}
      <span
        class="max-w-[34ch] truncate font-data text-[10px] text-muted-foreground {isUser ? 'mr-auto' : 'ml-auto'}"
        title="Request này chạy trên profile/account nào"
      >
        → {target}
      </span>
    {/if}

    <code class="flex-none font-data text-[10px] text-muted-foreground">
      {message.char_count.toLocaleString()} chars
    </code>
  </footer>
</article>
