<script lang="ts">
  import { ArrowSquareOut, Check, Copy, X } from "phosphor-svelte";
  import { renderMarkdown } from "../markdown";
  import type { SessionDetail, SessionMessage } from "../api";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Tabs from "$lib/components/ui/tabs";

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
  const target = $derived(
    [message.request?.profile_name, message.request?.account_host, message.request?.account_label]
      .filter(Boolean)
      .join(" · "),
  );
  const conversationUrl = $derived(message.request?.conversation_url ?? "");

  // Kiểu `string` chứ không phải union: Tabs.Root nhận `value` hai chiều kiểu
  // string, ràng buộc hẹp hơn sẽ không bind được.
  let tab = $state("pretty");
  let copied = $state(false);

  const markdown = $derived(message.content_markdown ?? message.content);
  const artifact = $derived(
    message.artifacts.find((item) => item.id === artifactId) ?? message.artifacts[0],
  );
  const responseJson = $derived(
    JSON.stringify(
      {
        id: `chatcmpl-session-${message.id}`,
        object: "chat.completion",
        created: Math.floor(message.created_at / 1000),
        model: session.model_public_id,
        choices: [
          {
            index: 0,
            message: { role: message.role, content: message.content },
            finish_reason: message.finish_reason,
          },
        ],
      },
      null,
      2,
    ),
  );

  const SOURCE_CLASS =
    "m-0 min-h-full overflow-auto rounded-lg border border-border bg-muted p-3 font-data text-[11px] leading-relaxed whitespace-pre-wrap";

  function safeHtmlDocument(raw: string): string {
    const escapedCsp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:;">`;
    const styles = `<style>html{color-scheme:dark}body{margin:20px;background:#0a0d0a;color:#dfe3df;font:15px/1.6 Archivo,system-ui,sans-serif}pre,code{font-family:Consolas,monospace;white-space:pre-wrap}a{color:#57e08a}img{max-width:100%}</style>`;
    return `<!doctype html><meta charset="utf-8">${escapedCsp}${styles}${raw}`;
  }

  async function copyCurrent() {
    const value =
      tab === "json"
        ? responseJson
        : tab === "html"
          ? (message.content_html ?? "")
          : tab === "artifact"
            ? (artifact?.body ?? "")
            : markdown;
    if (!value) return;
    await navigator.clipboard.writeText(value);
    copied = true;
    setTimeout(() => (copied = false), 1400);
  }

  $effect(() => {
    if (artifactId != null && message.artifacts.some((item) => item.id === artifactId)) {
      tab = "artifact";
    }
  });
</script>

<aside
  class="flex h-full min-h-0 w-full flex-col border-l border-border bg-card text-card-foreground"
  aria-label="Trình xem message"
>
  <header class="flex flex-none items-center justify-between gap-3 border-b border-border px-3 py-3">
    <div class="min-w-0">
      <h2 class="display-face text-base font-semibold leading-none tracking-[-0.02em]">
        Trình xem tín hiệu
      </h2>
      <p class="mt-1 font-data text-[11px] text-muted-foreground">
        Message #{message.seq} · {message.char_count.toLocaleString()} ký tự
      </p>
    </div>
    <Button size="icon-sm" variant="ghost" aria-label="Đóng trình xem" onclick={onclose}>
      <X />
    </Button>
  </header>

  <Tabs.Root bind:value={tab} class="flex min-h-0 flex-1 flex-col gap-0 overflow-hidden">
    <div class="flex-none border-b border-border px-3 py-2">
      <Tabs.List class="w-full">
        <Tabs.Trigger value="pretty" class="text-xs">Đọc</Tabs.Trigger>
        <Tabs.Trigger value="markdown" class="text-xs">Markdown</Tabs.Trigger>
        <Tabs.Trigger value="html" class="text-xs" disabled={!message.content_html}>HTML</Tabs.Trigger>
        <Tabs.Trigger value="json" class="text-xs">JSON</Tabs.Trigger>
        {#if message.artifacts.length}
          <Tabs.Trigger value="artifact" class="text-xs">Artifact</Tabs.Trigger>
        {/if}
      </Tabs.List>
    </div>

    <Tabs.Content
      value="pretty"
      class="mt-0 min-h-0 flex-1 overflow-auto p-3.5 data-[state=inactive]:hidden"
    >
      <article class="md-body text-[13px]">{@html renderMarkdown(markdown)}</article>
    </Tabs.Content>

    <Tabs.Content
      value="markdown"
      class="mt-0 min-h-0 flex-1 overflow-auto p-3.5 data-[state=inactive]:hidden"
    >
      <pre class={SOURCE_CLASS}>{markdown}</pre>
    </Tabs.Content>

    <Tabs.Content
      value="html"
      class="mt-0 min-h-0 flex-1 overflow-auto p-3.5 data-[state=inactive]:hidden"
    >
      {#if message.content_html}
        <iframe
          class="h-full min-h-90 w-full rounded-lg border border-border bg-white"
          title="HTML gốc đã sandbox"
          sandbox="allow-same-origin"
          srcdoc={safeHtmlDocument(message.content_html)}
        ></iframe>
      {:else}
        <div
          class="grid min-h-45 place-items-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground"
        >
          Recipe này chưa bật <code class="font-data">response.capture_html</code> khi message được tạo.
        </div>
      {/if}
    </Tabs.Content>

    <Tabs.Content
      value="json"
      class="mt-0 min-h-0 flex-1 overflow-auto p-3.5 data-[state=inactive]:hidden"
    >
      <pre class={SOURCE_CLASS}>{responseJson}</pre>
    </Tabs.Content>

    {#if artifact}
      <Tabs.Content
        value="artifact"
        class="mt-0 flex min-h-0 flex-1 flex-col gap-2 overflow-auto p-3.5 data-[state=inactive]:hidden"
      >
        <header class="flex min-w-0 items-baseline justify-between gap-2.5">
          <strong class="min-w-0 truncate text-xs">
            {artifact.title || artifact.language || `Artifact ${artifact.idx + 1}`}
          </strong>
          <span class="flex-none font-data text-[9px] text-muted-foreground">
            {artifact.kind}{artifact.language ? ` · ${artifact.language}` : ""}
          </span>
        </header>
        <pre class="{SOURCE_CLASS} flex-1"><code>{artifact.body}</code></pre>
      </Tabs.Content>
    {/if}
  </Tabs.Root>

  <!-- Dòng "đã gửi tới đâu" của đúng request này, ngay trên các con số đo. -->
  {#if target || conversationUrl}
    <div
      class="flex flex-none items-center gap-2 border-t border-border px-3 py-2 font-data text-[11px]"
    >
      <span class="flex-none text-muted-foreground">Đã gửi tới</span>
      <strong class="min-w-0 truncate font-medium">{target || "—"}</strong>
      {#if conversationUrl}
        <Button size="xs" variant="outline" class="ml-auto flex-none" title={conversationUrl} onclick={onopen}>
          <ArrowSquareOut />
          Xem trực tiếp
        </Button>
      {/if}
    </div>
  {/if}

  <footer class="flex flex-none items-center justify-between gap-2.5 border-t border-border px-3 py-2.5">
    <div class="flex flex-wrap items-center gap-2 font-data text-[10px] text-muted-foreground">
      <span>TTFB <strong class="text-foreground">{message.ttfb_ms == null ? "—" : `${message.ttfb_ms} ms`}</strong></span>
      <span>Tổng <strong class="text-foreground">{message.duration_ms == null ? "—" : `${message.duration_ms} ms`}</strong></span>
      {#if message.request?.fallback_used}
        <Badge variant="outline" class="h-4 border-warning/40 px-1.5 text-[9px] text-warning">Fallback</Badge>
      {/if}
    </div>
    <Button
      size="sm"
      variant="outline"
      disabled={tab === "html" && !message.content_html}
      onclick={copyCurrent}
    >
      {#if copied}<Check />Đã chép{:else}<Copy />Sao chép{/if}
    </Button>
  </footer>
</aside>
