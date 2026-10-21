<script lang="ts">
  import { ArrowSquareOut, ArrowClockwise, FolderSimple, SidebarSimple, ChatCircle, ImageSquare, Pulse } from "phosphor-svelte";
  import { selectedModel } from "$lib/sync";
  import type { WebsiteInfo, ModelInfo, TestTarget } from "$lib/api";
  import ProviderIcon from "$lib/components/sessions/ProviderIcon.svelte";
  import { Button } from "$lib/components/ui/button";

  let { site, modelOptions, accounts, accountId = $bindable(null), thinkingMode = $bindable("auto"),
    thinkingAvailable, projectLabel, projectAvailable, sending, opening, refreshing, inspectorOpen,
    tab = $bindable("chat"), onOpenProfile, onRefreshModels, onProject, onToggleInspector, onNew,
  }: {
    site: WebsiteInfo; modelOptions: ModelInfo[]; accounts: TestTarget[];
    accountId: number | null; thinkingMode: "auto" | "on" | "off";
    thinkingAvailable: boolean; projectAvailable: boolean; projectLabel: string;
    sending: boolean; opening: boolean; refreshing: boolean; inspectorOpen: boolean;
    tab: "chat" | "image"; onOpenProfile: () => void; onRefreshModels: () => void;
    onProject: () => void; onToggleInspector: () => void; onNew: () => void;
  } = $props();
</script>

<header class="workspace-heading flex-none bg-card px-4 pt-4 md:px-6">
  <div class="flex flex-wrap items-start justify-between gap-3">
    <div class="flex items-center gap-3">
      <div class="grid size-11 place-items-center rounded-xl bg-primary/8 text-primary"><ProviderIcon model={site.slug} size={25} /></div>
      <div><h2 class="text-xl font-semibold tracking-tight">{site.title}</h2><p class="mt-0.5 text-xs text-muted-foreground">{new URL(site.url).hostname} <span class="mx-1.5 text-border">/</span> Workspace</p></div>
    </div>
    <div class="flex items-center gap-1.5">
      <a href={`/websites/${site.id}/agent`} class="rounded-md px-2 py-2 text-xs font-medium text-primary hover:bg-muted">Agent CLI</a>
      <a href={`/websites/${site.id}/settings`} class="rounded-md px-2 py-2 text-xs font-medium text-primary hover:bg-muted" aria-label={`Cấu hình ${site.title}`}>Cấu hình</a>
      <Button variant="outline" size="sm" disabled={!accountId || opening || sending || !modelOptions.length} onclick={onOpenProfile}>
        <ArrowSquareOut /> {opening ? "Đang mở…" : "Mở profile"}
      </Button>
      <Button variant="ghost" size="icon-sm" aria-label="Ẩn hoặc hiện ngữ cảnh" title="Ngữ cảnh & chẩn đoán" aria-pressed={inspectorOpen} onclick={onToggleInspector}><SidebarSimple /></Button>
    </div>
  </div>
  <div class="mt-4 flex flex-wrap items-end gap-x-5 gap-y-3 pb-4">
    <label class="grid min-w-40 max-w-64 flex-1 gap-1 text-[11px] text-muted-foreground">
      Account / profile
      <select class="workspace-select" disabled={sending} value={accountId ?? "auto"} onchange={(event) => accountId = event.currentTarget.value === "auto" ? null : Number(event.currentTarget.value)}>
        <option value="auto">Tự chọn · cho phép failover</option>
        {#each accounts as account (account.account_id)}<option value={account.account_id}>{account.profile_name} · {account.label}</option>{/each}
      </select>
    </label>
    <label class="grid min-w-40 max-w-64 flex-1 gap-1 text-[11px] text-muted-foreground">
      Model
      <select class="workspace-select" bind:value={$selectedModel} disabled={sending || !modelOptions.length}>
        {#if !modelOptions.length}<option value="">Chưa có model khả dụng</option>{/if}
        {#each modelOptions as model (model.id)}<option value={model.id}>{model.id.split("/").slice(1).join("/")}</option>{/each}
      </select>
    </label>
    <Button variant="ghost" size="icon-sm" disabled={!accountId || sending || refreshing || !modelOptions.length} aria-label="Quét lại model theo account" title="Quét lại model của account trên website" onclick={onRefreshModels}><ArrowClockwise class={refreshing ? "animate-spin" : ""} /></Button>
    {#if thinkingAvailable}<label class="grid gap-1 text-[11px] text-muted-foreground">Thinking<select class="workspace-select" bind:value={thinkingMode} disabled={sending}><option value="auto">Auto</option><option value="on">Thinking</option><option value="off">Fast / tắt</option></select></label>{/if}
    {#if projectAvailable}<Button size="sm" variant={projectLabel ? "secondary" : "outline"} disabled={sending} onclick={onProject}><FolderSimple /><span class="max-w-40 truncate">{projectLabel || "Chọn project"}</span></Button>{/if}
  </div>
  <div class="flex items-center gap-5 border-t border-border/70 pt-1" aria-label="Công cụ website">
    <button class="workspace-tab" aria-current={tab === "chat" ? "page" : undefined} disabled={sending} onclick={() => tab = "chat"}><ChatCircle size={16} /> Hội thoại</button>
    {#if site.models.some((model) => model.capability === "image" || model.capability === "both")}
      <button class="workspace-tab" aria-current={tab === "image" ? "page" : undefined} disabled={sending} onclick={() => tab = "image"}><ImageSquare size={16} /> Tạo ảnh</button>
    {/if}
    <button class="workspace-tab" onclick={onToggleInspector}><Pulse size={16} /> Chẩn đoán</button>
    <Button class="ml-auto" size="xs" variant="ghost" disabled={sending} onclick={onNew}>Phiên mới</Button>
  </div>
</header>
