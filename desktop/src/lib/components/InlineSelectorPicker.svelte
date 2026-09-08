<script lang="ts">
  import { apiKey, pickerProfileId, showToast } from "../stores";
  import { profiles } from "../sync";
  import { countPickerSelector, capturePicker, startPicker, stopPicker } from "../api";
  import { Button } from "$lib/components/ui/button";
  import * as Select from "$lib/components/ui/select";
  import { Crosshair, CircleNotch, Check, ArrowsOutSimple } from "phosphor-svelte";

  let { value = $bindable(""), url = "", label = "selector", disabled = false }: {
    value: string; url: string; label?: string; disabled?: boolean;
  } = $props();

  let open = $state(false);
  let pickerId: string | null = $state(null);
  let candidates: { sel:string; kind:string; unique:boolean; count:number }[] = $state([]);
  let best = $state("");
  let localVal = $state(value);
  let countInfo: {count:number;unique:boolean}|null = $state(null);
  let busy = $state(false);
  let phase: "idle"|"picking"|"picked" = $state("idle");

  $effect(()=>{ localVal = value; });

  const profileOptions = $derived($profiles);

  async function onStart(){
    if (!url.trim()) { showToast("Nhập URL ở trang đích trước khi pick."); return; }
    const pid = $pickerProfileId==="__anon__" ? null : Number($pickerProfileId);
    if (pid==null){ showToast("Chọn profile phía trên trước khi pick (chọn một lần, dùng xuyên suốt)."); return; }
    busy=true;
    try{
      const r = await startPicker($apiKey, pid, url.trim());
      pickerId = r.picker_id; phase="picking";
      showToast("Đã mở picker — hover để highlight, click để chọn (không trigger action).");
    }catch(e){ showToast((e as Error).message); }
    finally{ busy=false; }
  }
  async function onCapture(){
    if (!pickerId) return;
    busy=true;
    try{
      const r = await capturePicker($apiKey, pickerId);
      candidates = r.candidates ?? [];
      const loc = (r as any).locator || r.best || r.selector || "";
      best = loc; localVal = loc;
      if ((r as any).warning) showToast((r as any).warning);
      if (loc){ try{ countInfo = await countPickerSelector($apiKey, pickerId, loc);}catch{} }
      const frameChain = (r as any).frame?.chain;
      const shadow = (r as any).shadow;
      let extra=""; if(frameChain?.length) extra+=` [frame: ${frameChain.join(" >> ")}]`;
      if(shadow?.closed) extra+=" [closed shadow — không hỗ trợ]"; else if(shadow?.depth) extra+=` [shadow host: ${shadow.hostSelector}]`;
      phase="picked"; showToast((loc?`Đã chọn: ${loc}`:"Đã chọn nhưng không có best candidate")+extra);
    }catch(e){ showToast((e as Error).message); }
    finally{ busy=false; }
  }
  async function onCount(){
    if (!pickerId || !localVal.trim()) return;
    try{ countInfo = await countPickerSelector($apiKey, pickerId, localVal.trim()); }catch(e){ showToast((e as Error).message); }
  }
  function apply(){
    value = localVal.trim(); open=false;
  }
  async function onClose(){
    if (pickerId){ try{ await stopPicker($apiKey, pickerId);}catch{} }
    pickerId=null; phase="idle"; candidates=[]; best=""; countInfo=null; open=false;
  }
  $effect(()=>{ return ()=>{ if(pickerId) stopPicker($apiKey, pickerId).catch(()=>{}); }; });
</script>

<div class="inline-picker {open ? 'open' : ''}">
  <Button type="button" variant="outline" size="sm" disabled={disabled} onclick={()=>open=!open} title="Chọn selector trên browser (inline, không modal)">
    <Crosshair size={13}/>{open ? "Đóng pick" : "Pick"}
  </Button>
  {#if open}
    <div class="inline-picker-panel">
      <div class="ip-head">
        <div class="ip-title">Pick selector — {label}</div>
        <Button variant="ghost" size="icon-sm" aria-label="Đóng" onclick={onClose}><ArrowsOutSimple/></Button>
      </div>
      <div class="ip-profile">
        <span class="ip-label">Profile hiện tại: {$pickerProfileId==="__anon__" ? "— chưa chọn —" : (profileOptions.find(p=>String(p.id)===$pickerProfileId)?.name ?? $pickerProfileId)}</span>
        <div class="flex gap-2 items-center">
          {#if phase==="idle"}
            <Button size="sm" onclick={onStart} disabled={busy}>{#if busy}<CircleNotch class="animate-spin"/>{:else}Mở picker{/if}</Button>
          {:else if phase==="picking"}
            <Button size="sm" onclick={onCapture} disabled={busy}>{#if busy}<CircleNotch class="animate-spin"/>{:else}Đã click — lấy{/if}</Button>
          {:else}
            <Button variant="outline" size="sm" onclick={onStart}>Pick lại</Button>
          {/if}
          <span class="ip-hint">Chọn profile ở header (một lần cho mọi picker).</span>
        </div>
      </div>
      {#if candidates.length}
        <div class="ip-cands">
          <div class="text-xs font-semibold">Ứng viên:</div>
          {#each candidates as c (c.sel)}
            <button class="ip-cand" onclick={()=>{localVal=c.sel; onCount();}}>
              <span class="truncate font-mono text-xs">{c.sel}</span>
              <span class="shrink-0 text-xs text-muted-foreground">{c.kind} {c.unique ? "✓" : `×${c.count}`}</span>
            </button>
          {/each}
          {#if best}<div class="text-xs">Best: <span class="font-mono font-medium">{best}</span></div>{/if}
        </div>
      {/if}
      <label class="ip-field">Selector sẽ điền
        <div class="flex gap-2">
          <input class="flex-1 rounded border px-2 py-1.5 font-mono text-xs" bind:value={localVal} placeholder="#id hoặc [data-testid=...]" />
          <Button variant="outline" size="sm" onclick={onCount}>Đếm</Button>
        </div>
        {#if countInfo}
          <span class="{countInfo.unique ? 'text-green-600' : countInfo.count===0 ? 'text-destructive' : 'text-amber-600'} text-xs">
            Khớp {countInfo.count} element{countInfo.unique ? " — duy nhất ✓" : countInfo.count>1 ? " — không duy nhất" : " — không khớp"}
          </span>
        {/if}
      </label>
      <div class="ip-actions">
        <Button variant="ghost" size="sm" onclick={onClose}>Huỷ</Button>
        <Button size="sm" onclick={apply} disabled={!localVal.trim()}><Check size={13}/> Dùng selector này</Button>
      </div>
    </div>
  {/if}
</div>

<style>
  .inline-picker{position:relative;display:inline-flex;flex-direction:column;gap:.35rem}
  .inline-picker-panel{display:grid;gap:.6rem;padding:.65rem;border:1px solid var(--border);border-radius:.6rem;background:var(--card);min-width:18rem;max-width:28rem;box-shadow:0 8px 24px rgba(0,0,0,.12)}
  .ip-head{display:flex;align-items:center;justify-content:space-between}
  .ip-title{font-size:.78rem;font-weight:600}
  .ip-label{font-size:.68rem;font-weight:600;color:var(--muted-foreground)}
  .ip-profile{display:grid;gap:.35rem}
  .ip-hint{font-size:.68rem;color:var(--muted-foreground);line-height:1.4;margin:0}
  .ip-cands{display:grid;gap:.3rem;padding:.5rem;border:1px solid var(--border);border-radius:.5rem;background:var(--background)}
  .ip-cand{display:flex;justify-content:space-between;gap:.5rem;text-align:left;padding:.25rem .4rem;border-radius:.35rem}
  .ip-cand:hover{background:var(--muted)}
  .ip-field{display:grid;gap:.3rem;font-size:.7rem;font-weight:600}
  .ip-actions{display:flex;justify-content:flex-end;gap:.4rem}
</style>
