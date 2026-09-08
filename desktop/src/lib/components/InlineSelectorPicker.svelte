<script lang="ts">
  import { onDestroy } from "svelte";
  import { apiKey, pickerProfileId, showToast } from "../stores";
  import { countPickerSelector, capturePicker, startPicker, stopPicker } from "../api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Crosshair, CircleNotch, Check } from "phosphor-svelte";

  let { value = $bindable(""), url = "", label = "selector", disabled = false, id, placeholder = "#id hoặc [data-testid=...]" }: {
    value: string; url: string; label?: string; disabled?: boolean; id?: string; placeholder?: string;
  } = $props();
  let pickerId = $state<string | null>(null);
  let candidates = $state<{ sel: string; kind: string; count: number }[]>([]);
  let frameChain = $state<string[]>([]);
  let expanded = $state(false);
  let busy = $state(false);
  let countInfo = $state<{ selector: string; count: number; unique: boolean } | null>(null);
  let disposed = false;

  async function count() {
    if (!pickerId || !value.trim()) return;
    const session = pickerId, selector = value.trim();
    try {
      const result = await countPickerSelector($apiKey, session, selector);
      if (pickerId === session && value.trim() === selector) countInfo = result;
    } catch (e) { showToast((e as Error).message); }
  }

  async function pick() {
    if (busy) return;
    if (!pickerId && !url.trim()) { showToast("Nhập URL trước khi pick."); return; }
    const profileId = Number($pickerProfileId);
    if (!pickerId && (!Number.isFinite(profileId) || profileId <= 0)) { showToast("Chọn profile phía trên trước khi pick."); return; }
    busy = true;
    const session = pickerId;
    try {
      if (!session) {
        const result = await startPicker($apiKey, profileId, url.trim());
        if (disposed) { await stopPicker($apiKey, result.picker_id); return; }
        pickerId = result.picker_id;
      } else {
        const result = await capturePicker($apiKey, session);
        if (disposed || pickerId !== session) return;
        frameChain = result.frame?.chain ?? [];
        candidates = result.candidates ?? [];
        expanded = false;
        value = result.locator || result.best || result.selector || "";
        countInfo = null;
        if (result.warning) showToast(result.warning);
        await count();
      }
    } catch (e) { if (!disposed && pickerId === session) showToast((e as Error).message); }
    finally { busy = false; }
  }

  async function close() {
    const session = pickerId;
    pickerId = null; candidates = []; countInfo = null; expanded = false;
    if (session) {
      try { await stopPicker($apiKey, session); }
      catch (e) { showToast((e as Error).message); }
    }
  }
  onDestroy(() => {
    disposed = true;
    if (pickerId) stopPicker($apiKey, pickerId).catch(() => {});
  });
</script>

<div class="selector-picker">
  <div class="selector-row">
    <Input {id} {placeholder} {disabled} aria-label={label} class="font-data min-w-0 flex-1" bind:value />
    <Button type="button" variant="outline" size="sm" disabled={disabled || busy} onclick={pick}>
      {#if busy}<CircleNotch size={14} class="animate-spin" />{:else}<Crosshair size={14} />{/if}
      {pickerId ? "Lấy selector" : "Pick"}
    </Button>
  </div>
  {#if pickerId}
    <div class="picker-details">
      <div class="picker-status">
        <span aria-live="polite">{busy ? "Đang lấy selector…" : candidates.length ? "Chọn ứng viên để điền vào ô phía trên." : "Click element trên browser, rồi bấm Lấy selector."}</span>
        <Button type="button" variant="ghost" size="sm" onclick={close}>Đóng</Button>
      </div>
      {#if candidates.length}
        <div class="candidate-list">
          {#each (expanded ? candidates : candidates.slice(0, 3)) as c}
            {@const locator = [...frameChain, c.sel].join(" >> ")}
            <button type="button" class="candidate" class:selected={value === locator} disabled={disabled || busy} title={locator} aria-pressed={value === locator} onclick={() => { value = locator; countInfo = null; void count(); }}>
              <span class="candidate-selector">{c.sel}</span>
              <span class="candidate-meta">{c.kind} · {c.count} khớp {#if value === locator}<Check size={12} />{/if}</span>
            </button>
          {/each}
        </div>
        {#if candidates.length > 3}
          <button type="button" class="show-more" aria-expanded={expanded} onclick={() => expanded = !expanded}>{expanded ? "Thu gọn" : `Xem thêm ${candidates.length - 3} ứng viên`}</button>
        {/if}
      {/if}
      <div class="picker-status">
        <span aria-live="polite">{#if countInfo && countInfo.selector === value.trim()}Khớp {countInfo.count} element{countInfo.unique ? " — duy nhất" : ""}{/if}</span>
        <Button type="button" variant="ghost" size="sm" disabled={disabled || busy || !value.trim()} onclick={count}>Đếm khớp</Button>
      </div>
    </div>
  {/if}
</div>

<style>
  .selector-picker{flex:1;min-width:0;width:100%;display:grid;gap:.3rem}
  .selector-row{display:flex;align-items:center;gap:.375rem;min-width:0}
  .picker-details{min-width:0;border-top:1px solid var(--border);padding-top:.25rem;font-size:.7rem;font-weight:400}
  .picker-status{display:flex;align-items:center;justify-content:space-between;gap:.5rem;color:var(--muted-foreground)}
  .candidate-list{display:grid;gap:.125rem;max-height:12rem;overflow-y:auto}
  .candidate{display:flex;align-items:center;justify-content:space-between;gap:.5rem;min-width:0;width:100%;padding:.35rem .4rem;border-radius:.25rem;text-align:left}
  .candidate:hover,.candidate.selected{background:var(--muted)}
  .candidate:focus-visible,.show-more:focus-visible{outline:2px solid var(--ring);outline-offset:2px}
  .candidate-selector{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--font-mono,monospace)}
  .candidate-meta{display:flex;align-items:center;gap:.25rem;flex-shrink:0;color:var(--muted-foreground);font-size:.65rem}
  .show-more{padding:.35rem .4rem;color:var(--muted-foreground);text-decoration:underline;text-underline-offset:3px}
</style>
