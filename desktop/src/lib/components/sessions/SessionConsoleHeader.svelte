<script lang="ts">
  import {
    Archive,
    ArrowSquareOut,
    Check,
    DownloadSimple,
    List,
    PencilSimple,
    PushPin,
    Trash,
  } from "phosphor-svelte";
  import type { SessionDetail } from "../../api";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";

  type ExportFormat = "md" | "html" | "json" | "jsonl";

  let {
    session,
    openingConversation = false,
    onRename,
    onTogglePin,
    onArchive,
    onExport,
    onDelete,
    onOpenConversation,
    onToggleBank,
  }: {
    session: SessionDetail;
    openingConversation?: boolean;
    onRename: (title: string) => void;
    onTogglePin: () => void;
    onArchive: () => void;
    onExport: (format: ExportFormat) => void;
    onDelete: () => void;
    onOpenConversation: () => void;
    /** Mở rail danh sách khi nó đang là drawer (bề ngang hẹp). */
    onToggleBank: () => void;
  } = $props();

  const FORMATS: ExportFormat[] = ["md", "html", "json", "jsonl"];

  let editing = $state(false);
  let draft = $state("");

  function startEdit() {
    draft = session.title;
    editing = true;
  }

  function commit() {
    onRename(draft.trim() || session.title);
    editing = false;
  }
</script>

<header
  class="flex flex-none flex-wrap items-center justify-between gap-3 border-b border-border bg-card px-3 py-2.5 md:px-4"
>
  <div class="flex min-w-0 flex-1 items-center gap-2">
    <Button
      size="icon-sm"
      variant="ghost"
      class="flex-none lg:hidden"
      aria-label="Mở danh sách sessions"
      onclick={onToggleBank}
    >
      <List />
    </Button>

    <div class="min-w-0">
      {#if editing}
        <div class="flex items-center gap-1.5">
          <Input
            class="h-7 max-w-64 text-sm"
            aria-label="Tên session"
            bind:value={draft}
            onkeydown={(event) => {
              if (event.key === "Enter") commit();
              if (event.key === "Escape") editing = false;
            }}
          />
          <Button size="icon-sm" variant="outline" aria-label="Lưu tên" onclick={commit}>
            <Check />
          </Button>
        </div>
      {:else}
        <button
          type="button"
          class="group flex max-w-full items-center gap-1.5 text-left outline-none"
          title="Đổi tên session"
          onclick={startEdit}
        >
          <span class="truncate text-[15px] font-semibold">
            {session.title || "Phiên chưa đặt tên"}
          </span>
          <PencilSimple
            size={13}
            class="flex-none text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"
            aria-hidden="true"
          />
        </button>
      {/if}

      <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-data text-[10px] text-muted-foreground">
        <span class="flex items-center gap-1.5">
          <span class="size-1.5 rounded-full bg-success" aria-hidden="true"></span>
          {session.model_public_id}
        </span>
        <span>{session.kind === "api" ? "API" : "DESKTOP"}</span>
        <span>{session.message_count} MSG</span>
        {#if session.profile_name}
          <span class="rounded bg-muted px-1.5 py-px" title="Profile Chromium đã chạy phiên này">
            {session.profile_name}{session.account_label ? ` · ${session.account_label}` : ""}
          </span>
        {/if}
        {#if session.archived}
          <Badge variant="secondary" class="h-4 px-1.5 text-[9px]">Đã lưu trữ</Badge>
        {/if}
        {#if session.site_conversation_url}
          <Button
            size="xs"
            variant="ghost"
            class="h-5 px-1.5 text-[10px] text-primary"
            disabled={openingConversation}
            title={`Mở ${session.site_conversation_url} trong profile ${session.profile_name ?? ""}`}
            onclick={onOpenConversation}
          >
            <ArrowSquareOut />
            Xem trực tiếp
          </Button>
        {/if}
      </div>
    </div>
  </div>

  <div class="flex flex-none items-center gap-1">
    <Button
      size="sm"
      variant={session.pinned ? "secondary" : "ghost"}
      title="Ghim session"
      onclick={onTogglePin}
    >
      <PushPin weight={session.pinned ? "fill" : "regular"} />
      <span class="hidden md:inline">Ghim</span>
    </Button>

    <Button size="sm" variant="ghost" title="Lưu trữ session" onclick={onArchive}>
      <Archive />
      <span class="hidden md:inline">{session.archived ? "Bỏ lưu trữ" : "Lưu trữ"}</span>
    </Button>

    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button size="sm" variant="ghost" title="Xuất session" {...props}>
            <DownloadSimple />
            <span class="hidden md:inline">Xuất</span>
          </Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" class="min-w-32">
        {#each FORMATS as format (format)}
          <DropdownMenu.Item class="font-data text-xs" onclick={() => onExport(format)}>
            .{format}
          </DropdownMenu.Item>
        {/each}
      </DropdownMenu.Content>
    </DropdownMenu.Root>

    <Button size="sm" variant="ghost" class="text-destructive" title="Xóa session" onclick={onDelete}>
      <Trash />
      <span class="hidden md:inline">Xóa</span>
    </Button>
  </div>
</header>
