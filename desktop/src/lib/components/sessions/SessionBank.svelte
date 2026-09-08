<script lang="ts">
  import { ChatCircleDots, MagnifyingGlass, Plus, PushPin, X } from "phosphor-svelte";
  import type { SessionSummary } from "../../api";
  import { models } from "../../sync";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import { Switch } from "$lib/components/ui/switch";
  import * as Select from "$lib/components/ui/select";
  import { relativeTime } from "./shared";

  let {
    sessions,
    activeId,
    selectedIds,
    loading,
    query = $bindable(),
    modelFilter = $bindable(),
    archived = $bindable(),
    onSearch,
    onFilterChange,
    onNew,
    onOpen,
    onToggle,
    onSelectAll,
    onDeleteSelected,
    onDeleteAll,
    onClose,
  }: {
    sessions: SessionSummary[];
    activeId: string | null;
    selectedIds: string[];
    loading: boolean;
    query: string;
    modelFilter: string;
    archived: boolean;
    onSearch: () => void;
    onFilterChange: () => void;
    onNew: () => void;
    onOpen: (id: string) => void;
    onToggle: (id: string) => void;
    onSelectAll: (checked: boolean) => void;
    onDeleteSelected: () => void;
    onDeleteAll: () => void;
    /** Chỉ hiện ở bề ngang hẹp, nơi rail này là drawer chồng lên console. */
    onClose?: () => void;
  } = $props();

  const allSelected = $derived(
    sessions.length > 0 && sessions.every((item) => selectedIds.includes(item.id)),
  );

  // Select của bits-ui coi chuỗi rỗng là "chưa chọn" nên bộ lọc "mọi model"
  // phải mang một giá trị thật; quy đổi hai chiều ngay tại ranh giới component.
  const ALL = "__all__";
</script>

<aside
  class="flex h-full min-h-0 w-full flex-col border-r border-border bg-card text-card-foreground"
  aria-label="Danh sách sessions"
>
  <header class="flex flex-none items-center justify-between gap-3 border-b border-border px-3 py-3">
    <div class="min-w-0">
      <h2 class="display-face text-base font-semibold leading-none tracking-[-0.02em]">Sessions</h2>
      <p class="mt-1 font-data text-[11px] text-muted-foreground">
        {sessions.length} phiên trong bộ lọc
      </p>
    </div>
    <div class="flex flex-none items-center gap-1">
      <Button size="icon-sm" variant="outline" aria-label="Tạo session mới" title="Session mới" onclick={onNew}>
        <Plus />
      </Button>
      {#if onClose}
        <Button
          size="icon-sm"
          variant="ghost"
          class="lg:hidden"
          aria-label="Đóng danh sách"
          onclick={onClose}
        >
          <X />
        </Button>
      {/if}
    </div>
  </header>

  <div class="grid flex-none gap-2 border-b border-border p-3">
    <div class="relative">
      <MagnifyingGlass
        size={15}
        class="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <Input
        class="pl-8"
        aria-label="Tìm trong hội thoại"
        placeholder="Tìm toàn văn…"
        bind:value={query}
        oninput={onSearch}
      />
    </div>

    <Select.Root
      type="single"
      value={modelFilter || ALL}
      onValueChange={(value) => {
        modelFilter = value === ALL ? "" : value;
        onFilterChange();
      }}
    >
      <Select.Trigger class="w-full font-data text-xs" aria-label="Lọc model">
        {modelFilter || "Mọi model"}
      </Select.Trigger>
      <Select.Content>
        <Select.Item value={ALL} label="Mọi model">Mọi model</Select.Item>
        {#each $models as model (model.id)}
          <Select.Item value={model.id} label={model.id}>{model.id}</Select.Item>
        {/each}
      </Select.Content>
    </Select.Root>

    <label class="flex items-center gap-2 text-xs text-muted-foreground">
      <Switch
        bind:checked={archived}
        onCheckedChange={onFilterChange}
        aria-label="Chỉ xem session đã lưu trữ"
      />
      Đã lưu trữ
    </label>
  </div>

  <div class="flex flex-none items-center gap-2 border-b border-border px-3 py-2">
    <label class="flex min-w-0 flex-1 items-center gap-2 text-[11px] text-muted-foreground">
      <Checkbox
        checked={allSelected}
        indeterminate={selectedIds.length > 0 && !allSelected}
        disabled={!sessions.length}
        onCheckedChange={(checked) => onSelectAll(checked === true)}
        aria-label="Chọn tất cả session"
      />
      <span class="truncate">
        {selectedIds.length ? `${selectedIds.length} đã chọn` : "Chọn tất cả"}
      </span>
    </label>
    <Button size="xs" variant="outline" disabled={!selectedIds.length} onclick={onDeleteSelected}>
      Xóa đã chọn
    </Button>
    <Button size="xs" variant="destructive" disabled={!sessions.length} onclick={onDeleteAll}>
      Xóa tất cả
    </Button>
  </div>

  <div class="min-h-0 flex-1 overflow-y-auto p-1.5" aria-live="polite">
    {#if loading}
      {#each [0, 1, 2, 3, 4] as row (row)}
        <div class="grid gap-2 px-2 py-3" aria-hidden="true">
          <Skeleton class="h-3 w-2/3" />
          <Skeleton class="h-2.5 w-full" />
          <Skeleton class="h-2 w-1/2" />
        </div>
      {/each}
    {:else if sessions.length === 0}
      <div class="flex min-h-45 flex-col items-center justify-center px-6 py-10 text-center">
        <ChatCircleDots size={30} class="mb-2 text-muted-foreground" aria-hidden="true" />
        <p class="text-sm font-medium">Không có tín hiệu</p>
        <p class="mt-1 max-w-[36ch] text-xs text-muted-foreground">
          {query ? "Thử từ khóa ngắn hơn." : "Gửi prompt đầu tiên để ghi một phiên."}
        </p>
      </div>
    {:else}
      <ul class="grid gap-0.5">
        {#each sessions as item (item.id)}
          {@const isActive = activeId === item.id}
          <li
            class="flex items-start gap-2 rounded-lg px-2 transition-colors hover:bg-muted/70
              {isActive ? 'bg-primary/10 hover:bg-primary/15' : ''}
              {!isActive && selectedIds.includes(item.id) ? 'bg-muted/60' : ''}"
          >
            <div class="pt-3.5">
              <Checkbox
                checked={selectedIds.includes(item.id)}
                onCheckedChange={() => onToggle(item.id)}
                aria-label={`Chọn ${item.title || "session"}`}
              />
            </div>
            <button
              type="button"
              class="flex min-w-0 flex-1 items-start gap-2.5 py-2.5 pr-1 text-left outline-none"
              onclick={() => onOpen(item.id)}
            >
              <span
                class="mt-1.5 size-1.5 flex-none rounded-full
                  {item.error_count > 0
                    ? 'bg-destructive'
                    : isActive
                      ? 'bg-primary'
                      : 'bg-muted-foreground/60'}"
                aria-hidden="true"
              ></span>
              <span class="grid min-w-0 flex-1">
                <span class="truncate text-[13px] font-medium">
                  {item.title || "Phiên chưa đặt tên"}
                </span>
                <span class="mt-0.5 truncate text-[11px] text-muted-foreground">
                  {item.first_prompt || "Không có prompt"}
                </span>
                <span class="mt-1.5 flex items-center gap-1.5 font-data text-[10px] text-muted-foreground">
                  <span class="min-w-0 truncate">{item.model_public_id || "—"}</span>
                  {#if item.profile_name}
                    <span
                      class="max-w-[14ch] flex-none truncate rounded bg-muted px-1"
                      title={`Profile ${item.profile_name} · ${item.account_host ?? ""} · ${item.account_label ?? ""}`}
                    >
                      {item.profile_name}{item.account_label ? ` · ${item.account_label}` : ""}
                    </span>
                  {/if}
                  <span class="flex-none">{item.message_count} msg</span>
                  <time class="flex-none" datetime={new Date(item.updated_at).toISOString()}>
                    {relativeTime(item.updated_at)}
                  </time>
                </span>
              </span>
              {#if item.pinned}
                <PushPin size={13} weight="fill" class="mt-1 flex-none text-primary" aria-label="Đã ghim" />
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  {#if archived}
    <div class="flex-none border-t border-border px-3 py-2">
      <Badge variant="secondary" class="w-full justify-center text-[10px]">Đang xem hộp lưu trữ</Badge>
    </div>
  {/if}
</aside>
