<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { profiles } from "../sync";
  import { countPickerSelector, capturePicker, startPicker, stopPicker } from "../api";
  import { Button } from "$lib/components/ui/button";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { Crosshair, Check, CircleNotch } from "phosphor-svelte";

  let { value = $bindable(""), url = "", label = "selector", disabled = false }: {
    value: string;
    url: string;
    label?: string;
    disabled?: boolean;
  } = $props();

  let open = $state(false);
  let pickerId = $state<string | null>(null);
  let selectedProfileId = $state<string>("__anon__"); // picker bắt buộc có profile
  let candidates = $state<{ sel: string; kind: string; unique: boolean; count: number }[]>([]);
  let best = $state("");
  let manualSel = $state("");
  let countInfo = $state<{ count: number; unique: boolean } | null>(null);
  let busy = $state(false);
  let phase: "idle"|"picking"|"picked" = $state("idle");

  const profileOptions = $derived($profiles);

  async function onStart() {
    if (!url.trim()) { showToast("Nhập URL ở trên trước khi pick."); return; }
    const pid = selectedProfileId === "__anon__" ? null : Number(selectedProfileId);
    if (pid == null) { showToast("Chọn profile để mở headed browser."); return; }
    busy = true;
    try {
      const r = await startPicker($apiKey, pid, url.trim());
      pickerId = r.picker_id;
      phase = "picking";
      showToast("Đã mở picker — hover để highlight, click để chọn (không trigger action).");
    } catch (e) { showToast((e as Error).message); }
    finally { busy = false; }
  }

  async function onCapture() {
    if (!pickerId) return;
    busy = true;
    try {
      const r = await capturePicker($apiKey, pickerId);
      candidates = r.candidates ?? [];
      const loc = (r as any).locator || r.best || r.selector || "";
      best = loc;
      manualSel = loc;
      if ((r as any).warning) showToast((r as any).warning);
      // live count — use locator which may contain frame chain
      if (loc) {
        try { countInfo = await countPickerSelector($apiKey, pickerId, loc); } catch {}
      }
      // surface frame/shadow info
      const frameChain = (r as any).frame?.chain;
      const shadow = (r as any).shadow;
      let extra = "";
      if (frameChain?.length) extra += ` [frame: ${frameChain.join(" >> ")}]`;
      if (shadow?.closed) extra += " [closed shadow — khong ho tro]";
      else if (shadow?.depth) extra += ` [shadow host: ${shadow.hostSelector}]`;
      phase = "picked";
      showToast((loc ? `Đã chọn: ${loc}` : "Đã chọn nhưng không có best candidate") + extra);
    } catch (e) { showToast((e as Error).message); }
    finally { busy = false; }
  }

  async function onCount() {
    if (!pickerId || !manualSel.trim()) return;
    try {
      countInfo = await countPickerSelector($apiKey, pickerId, manualSel.trim());
    } catch (e) { showToast((e as Error).message); }
  }

  function apply() {
    value = manualSel.trim();
    onClose();
  }

  async function onClose() {
    if (pickerId) { try{ await stopPicker($apiKey, pickerId);}catch{} }
    pickerId = null;
    phase = "idle";
    candidates = [];
    best = "";
    countInfo = null;
    open = false;
  }

  // cleanup on unmount
  $effect(() => {
    return () => { if (pickerId) stopPicker($apiKey, pickerId).catch(()=>{}); };
  });
</script>

<Dialog.Root bind:open onOpenChange={(o)=>{ if(!o) onClose(); }}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button variant="outline" size="sm" {...props} disabled={disabled} title="Chọn selector trên browser">
        <Crosshair size={14}/> Pick
      </Button>
    {/snippet}
  </Dialog.Trigger>
  <Dialog.Content class="max-w-lg">
    <Dialog.Header>
      <Dialog.Title>Pick selector — {label}</Dialog.Title>
      <Dialog.Description>Chọn profile rồi mở picker, hover/click trên browser headed. Click không trigger action.</Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-3 py-2">
      <div class="flex gap-2 items-end">
        <div class="grid gap-1 flex-1">
          <span class="text-xs font-medium">Profile (bắt buộc headed)</span>
          <Select.Root type="single" bind:value={selectedProfileId}>
            <Select.Trigger class="h-9">{profileOptions.find(p=>String(p.id)===selectedProfileId)?.name ?? "Chọn profile"}</Select.Trigger>
            <Select.Content>
              {#each profileOptions as p (p.id)}
                <Select.Item value={String(p.id)} label={p.name}>{p.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>
        {#if phase==="idle"}
          <Button onclick={onStart} disabled={busy}>{#if busy}<CircleNotch class="animate-spin"/>{:else}Mở picker{/if}</Button>
        {:else if phase==="picking"}
          <Button onclick={onCapture} disabled={busy}>{#if busy}<CircleNotch class="animate-spin"/>{:else}Đã click — lấy selector{/if}</Button>
        {:else}
          <Button variant="outline" onclick={onStart}>Pick lại</Button>
        {/if}
      </div>

      {#if candidates.length}
        <div class="rounded border p-2 grid gap-1">
          <div class="text-xs font-semibold">Ứng viên (verify trên DOM lúc pick):</div>
          {#each candidates as c (c.sel)}
            <button class="text-left text-xs font-mono px-2 py-1 rounded hover:bg-muted flex justify-between gap-2" onclick={()=>{manualSel=c.sel; onCount();}}>
              <span class="truncate">{c.sel}</span>
              <span class="shrink-0 text-muted-foreground">{c.kind} {c.unique ? "✓" : `×${c.count}`}</span>
            </button>
          {/each}
          {#if best}<div class="text-xs">Best: <span class="font-mono font-medium">{best}</span></div>{/if}
        </div>
      {/if}

      <label class="grid gap-1 text-xs font-medium">Selector sẽ điền vào form
        <div class="flex gap-2">
          <input class="flex-1 rounded border px-2 py-1.5 font-mono text-sm" bind:value={manualSel} placeholder="#id hoặc [data-testid=...]" />
          <Button variant="outline" size="sm" onclick={onCount}>Đếm</Button>
        </div>
        {#if countInfo}
          <span class="{countInfo.unique ? 'text-green-600' : countInfo.count===0 ? 'text-destructive' : 'text-amber-600'}">
            Khớp {countInfo.count} element{countInfo.unique ? " — duy nhất ✓" : countInfo.count>1 ? " — không duy nhất, sẽ warn" : " — không khớp"}
          </span>
        {/if}
      </label>
    </div>

    <Dialog.Footer>
      <Button variant="ghost" onclick={onClose}>Huỷ</Button>
      <Button onclick={apply} disabled={!manualSel.trim()}><Check size={14}/> Dùng selector này</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
