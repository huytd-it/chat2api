<script lang="ts">
  import { ArrowRight, Link, LinkBreak, Plus, Stop, Target, TestTube, X } from "phosphor-svelte";
  import type { ChatTarget, TestTarget } from "../../api";
  import { headedBrowser } from "../../stores";
  import { models, selectedModel } from "../../sync";
  import { Button } from "$lib/components/ui/button";
  import { Switch } from "$lib/components/ui/switch";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as Select from "$lib/components/ui/select";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { TEST_PROMPTS, type RotationMode } from "./shared";

  let {
    prompt = $bindable(),
    extraPrompts = $bindable(),
    keepContext = $bindable(true),
    hasActive = false,
    selected,
    targetCount,
    benchOpen,
    sending,
    elapsed,
    liveTarget,
    planLine,
    promptCount,
    rotationMode,
    onSend,
    onStop,
    onToggleBench,
    onOpenBench,
    onHeadedChange,
    onRemoveTarget,
  }: {
    prompt: string;
    extraPrompts: string[];
    keepContext?: boolean;
    /** Có session đang mở không — chưa có thì toggle giữ context vô nghĩa. */
    hasActive?: boolean;
    selected: TestTarget[];
    targetCount: number;
    benchOpen: boolean;
    sending: boolean;
    elapsed: number;
    liveTarget: ChatTarget | null;
    planLine: string;
    promptCount: number;
    rotationMode: RotationMode;
    onSend: () => void;
    onStop: () => void;
    onToggleBench: () => void;
    onOpenBench: () => void;
    onHeadedChange: () => void;
    onRemoveTarget: (accountId: number) => void;
  } = $props();

  let promptEl = $state<HTMLTextAreaElement | null>(null);
  // IME tiếng Việt: Enter trong lúc đang ghép ký tự là "chốt chữ", không phải
  // "gửi" — nên chỉ gửi khi bộ gõ đã nhả.
  let composing = $state(false);

  const profileCount = $derived(new Set(selected.map((item) => item.profile_name)).size);
  const domainCount = $derived(new Set(selected.map((item) => item.domain)).size);

  export function focusPrompt() {
    promptEl?.focus();
  }

  function autoGrow() {
    if (!promptEl) return;
    promptEl.style.height = "auto";
    promptEl.style.height = `${Math.min(promptEl.scrollHeight, 180)}px`;
  }

  // Workspace xóa trắng `prompt` ngay khi gửi, nên chiều cao phải co lại theo
  // giá trị chứ không chỉ theo sự kiện gõ phím.
  $effect(() => {
    prompt;
    autoGrow();
  });

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !composing) {
      event.preventDefault();
      onSend();
    }
  }

  function updateExtra(index: number, value: string) {
    extraPrompts = extraPrompts.map((item, position) => (position === index ? value : item));
  }

  function removeExtra(index: number) {
    extraPrompts = extraPrompts.filter((_, position) => position !== index);
  }

  /** Chèn prompt mẫu vào ô nhập — nối tiếp nếu đã gõ dở, không gửi ngay. */
  function pickTestPrompt(text: string) {
    prompt = prompt.trim() ? prompt.replace(/\s+$/, "") + "\n\n" + text : text;
    promptEl?.focus();
    autoGrow();
  }
</script>

<div class="flex-none border-t border-border bg-card px-3 py-3 md:px-6">
  <Textarea
    class="max-h-45 min-h-11 resize-none"
    aria-label="Tin nhắn mới"
    placeholder={selected.length
      ? `Prompt 1 — chạy trên ${selected.length} target đã chọn…`
      : $selectedModel
        ? "Phát tín hiệu tới model…"
        : "Chưa có model khả dụng"}
    rows={1}
    bind:value={prompt}
    bind:ref={promptEl}
    oninput={autoGrow}
    onkeydown={onKeydown}
    oncompositionstart={() => (composing = true)}
    oncompositionend={() => (composing = false)}
  />

  {#each extraPrompts as item, index (index)}
    <div class="relative mt-2">
      <Textarea
        class="resize-none pr-9"
        aria-label={`Prompt ${index + 2}`}
        placeholder={`Prompt ${index + 2}`}
        rows={2}
        value={item}
        oninput={(event) => updateExtra(index, event.currentTarget.value)}
      />
      <Button
        size="icon-xs"
        variant="ghost"
        class="absolute top-1.5 right-1.5"
        aria-label={`Xóa prompt ${index + 2}`}
        onclick={() => removeExtra(index)}
      >
        <X />
      </Button>
    </div>
  {/each}

  <div class="mt-2.5 flex flex-wrap items-center gap-2">
    {#if selected.length}
      <Button
        size="sm"
        variant="outline"
        class="font-data text-[11px]"
        title="Mỗi target chạy model riêng — chỉnh trong Bàn test"
        onclick={onOpenBench}
      >
        {selected.length} target · {profileCount} profile · {domainCount} domain
      </Button>
    {:else}
      <Select.Root type="single" bind:value={$selectedModel}>
        <Select.Trigger class="w-full max-w-56 font-data text-xs" aria-label="Model">
          {$selectedModel || "Chưa có model"}
        </Select.Trigger>
        <Select.Content>
          {#each $models as model (model.id)}
            <Select.Item value={model.id} label={model.id}>{model.id}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    {/if}

    <label
      class="flex items-center gap-2 text-[11px] text-muted-foreground"
      title="Chạy recipe trong cửa sổ Chromium hiện ra thay vì chạy ẩn"
    >
      <Switch bind:checked={$headedBrowser} onCheckedChange={onHeadedChange} aria-label="Hiện cửa sổ Chromium" />
      Hiện cửa sổ
    </label>

    <Button
      size="sm"
      variant={benchOpen || selected.length ? "secondary" : "outline"}
      class="text-[11px]"
      title="Chọn profile / domain / account để chạy thử"
      aria-expanded={benchOpen}
      onclick={onToggleBench}
    >
      <Target />
      Bàn test{selected.length ? ` · ${selected.length}` : targetCount ? ` · ${targetCount} sẵn` : ""}
    </Button>

    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button size="sm" variant="outline" class="text-[11px]" title="Chèn một prompt kiểm tra có sẵn vào ô nhập" {...props}>
            <TestTube />
            Prompt mẫu
          </Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="start" class="max-w-80">
        <DropdownMenu.Label class="font-data text-[10px] text-muted-foreground">
          PROMPT KIỂM TRA DÙNG CHUNG
        </DropdownMenu.Label>
        {#each TEST_PROMPTS as item (item.id)}
          <DropdownMenu.Item
            class="flex-col items-start gap-0.5 whitespace-normal"
            title={item.hint}
            onclick={() => pickTestPrompt(item.text)}
          >
            <span class="text-xs font-medium">{item.label}</span>
            <span class="line-clamp-2 text-[11px] text-muted-foreground">{item.text}</span>
          </DropdownMenu.Item>
        {/each}
      </DropdownMenu.Content>
    </DropdownMenu.Root>

    {#if !selected.length}
      <Button
        size="sm"
        variant={keepContext ? "secondary" : "outline"}
        class="text-[11px]"
        disabled={!hasActive}
        title={hasActive
          ? keepContext
            ? "Đang giữ context: lượt gửi tới sẽ nối vào session đang mở"
            : "Đã tách context: lượt gửi tới sẽ tạo session mới"
          : "Mở một session để dùng tiếp tục chat trong cùng phiên"}
        aria-pressed={keepContext}
        onclick={() => (keepContext = !keepContext)}
      >
        {#if keepContext}<Link />{:else}<LinkBreak />{/if}
        {keepContext ? "Giữ context" : "Tách phiên"}
      </Button>
    {/if}

    {#if selected.length}
      <Button size="sm" variant="ghost" class="text-[11px]" title="Thêm một prompt nữa" onclick={() => (extraPrompts = [...extraPrompts, ""])}>
        <Plus />
        Prompt
      </Button>
    {/if}

    <div class="ml-auto flex items-center gap-2">
      {#if sending}
        {#if liveTarget?.label}
          <span
            class="max-w-[30ch] truncate font-data text-[10px] text-muted-foreground"
            title="Server đã chọn profile/account này cho request đang chạy"
          >
            → {liveTarget.label}
          </span>
        {/if}
        <Button size="sm" variant="destructive" onclick={onStop}>
          <Stop weight="fill" />
          Dừng · {elapsed}s
        </Button>
      {:else}
        <Button
          size="sm"
          disabled={!prompt.trim() || (!selected.length && !$selectedModel)}
          onclick={onSend}
        >
          <ArrowRight />
          {selected.length && promptCount
            ? `Gửi · ${promptCount * (rotationMode === "broadcast" ? selected.length : 1)} req`
            : "Gửi"}
        </Button>
      {/if}
    </div>
  </div>

  {#if selected.length && !benchOpen}
    <div class="mt-2 flex gap-1.5 overflow-x-auto pb-1" aria-label="Target đã chọn">
      {#each selected as target (target.account_id)}
        <button
          type="button"
          class="flex flex-none items-center gap-1.5 rounded-full border border-border bg-muted px-2.5 py-1 text-[10px] text-muted-foreground transition-colors hover:border-destructive/40 hover:text-foreground"
          title="Bỏ chọn target này"
          onclick={() => onRemoveTarget(target.account_id)}
        >
          <strong class="font-semibold text-foreground">{target.profile_name}</strong>
          <span class="font-data">{target.host}</span>
          <span>{target.label}</span>
          <X size={10} aria-hidden="true" />
        </button>
      {/each}
    </div>
  {/if}

  <p class="mt-2 text-[10px] text-muted-foreground">
    {#if selected.length}
      {planLine} · Enter để gửi
    {:else if hasActive}
      {keepContext ? "Đang nối vào session đang mở" : "Lượt tới sẽ tạo session mới"} · Enter gửi · Shift+Enter xuống dòng
    {:else}
      Enter gửi · Shift+Enter xuống dòng · bản ghi được chốt khi stream kết thúc
    {/if}
  </p>
</div>
