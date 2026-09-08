<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as Select from "$lib/components/ui/select";
  import InlineSelectorPicker from "./InlineSelectorPicker.svelte";
  import { ArrowDown, ArrowUp, Copy, CursorClick, Clock, Keyboard, Trash, PlusCircle } from "phosphor-svelte";

  type StepKind = "click" | "select" | "press" | "wait";
  interface Step { kind: StepKind; arg: string }

  let {
    value = $bindable(""),
    url = "",
    label = "action",
    placeholder = "click:#selector",
    compact = false,
  }: { value: string; url?: string; label?: string; placeholder?: string; compact?: boolean } = $props();

  function parse(v: string): Step[] {
    if (!v.trim()) return [];
    return v.split(";").map(s=>s.trim()).filter(Boolean).map(raw=>{
      const i = raw.indexOf(":");
      if (i===-1) return { kind: "click" as StepKind, arg: raw };
      const k = raw.slice(0,i).trim().toLowerCase() as StepKind;
      const arg = raw.slice(i+1).trim();
      if (k==="click"||k==="select"||k==="press"||k==="wait") return {kind:k,arg};
      return {kind:"click",arg};
    });
  }
  function serialize(steps: Step[]): string {
    return steps.filter(s=>s.arg.trim()).map(s=>`${s.kind}:${s.arg.trim()}`).join(";");
  }

  let steps: Step[] = $state(parse(value));
  let _syncing = false;
  $effect(()=>{
    if (_syncing) return;
    const cur = serialize(steps);
    if (cur !== value) { _syncing=true; value=cur; _syncing=false; }
  });
  $effect(()=>{
    const p = parse(value);
    const cur = serialize(steps);
    const incoming = serialize(p);
    if (incoming!==cur && !_syncing) steps = p.length? p : [];
  });

  function add(kind: StepKind, arg=""){
    const def = kind==="press"?"Enter": kind==="wait"?"400": "";
    steps = [...steps, {kind, arg: arg || def}];
  }
  function remove(i:number){ steps = steps.filter((_,ix)=>ix!==i); }
  function move(i:number, dir:number){
    const j=i+dir; if(j<0||j>=steps.length) return;
    const copy=[...steps]; const tmp=copy[i]; copy[i]=copy[j]; copy[j]=tmp; steps=copy;
  }
  function dup(i:number){ const s=steps[i]; steps=[...steps.slice(0,i+1), {...s}, ...steps.slice(i+1)]; }

  const kindLabel:Record<StepKind,string> = { click:"Bấm", select:"Chọn", press:"Phím", wait:"Chờ" };
</script>

<div class="steps-editor {compact ? 'compact' : ''}">
  {#if steps.length===0}
    <div class="steps-empty">Chưa có bước nào. Thêm một bước bên dưới — ví dụ <span class="font-data">click:#model-btn;click:[data-value='gpt-4'];press:Enter</span></div>
  {/if}
  <div class="steps-list">
    {#each steps as s, i (i)}
      <div class="step-row">
        <span class="step-idx">{i+1}</span>
        <Select.Root type="single" bind:value={steps[i].kind as unknown as string}>
          <Select.Trigger class="h-8 w-[7.2rem] shrink-0 font-medium">{kindLabel[steps[i].kind]}</Select.Trigger>
          <Select.Content>
            <Select.Item value="click" label="Bấm (click)"><CursorClick size={13}/> Bấm</Select.Item>
            <Select.Item value="select" label="Chọn (select)"><CursorClick size={13}/> Chọn</Select.Item>
            <Select.Item value="press" label="Phím (press)"><Keyboard size={13}/> Phím</Select.Item>
            <Select.Item value="wait" label="Chờ (ms)"><Clock size={13}/> Chờ</Select.Item>
          </Select.Content>
        </Select.Root>

        {#if s.kind==="wait"}
          <Input class="h-8 flex-1 font-data" type="number" min="0" placeholder="400" bind:value={steps[i].arg} />
          <span class="unit">ms</span>
        {:else if s.kind==="press"}
          <Input class="h-8 flex-1 font-data" list="press-keys-{i}" placeholder="Enter" bind:value={steps[i].arg} />
          <datalist id="press-keys-{i}">
            <option value="Enter"></option><option value="Escape"></option><option value="Tab"></option><option value="Space"></option>
          </datalist>
        {:else}
          <InlineSelectorPicker {url} bind:value={steps[i].arg} label={label} placeholder={s.kind==="select" ? "select: option value" : "#dropdown"} />
        {/if}

        <div class="step-actions">
          <Button variant="ghost" size="icon-sm" aria-label="Lên" disabled={i===0} onclick={()=>move(i,-1)}><ArrowUp size={12}/></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Xuống" disabled={i===steps.length-1} onclick={()=>move(i,1)}><ArrowDown size={12}/></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Nhân bản" onclick={()=>dup(i)}><Copy size={12}/></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Xóa bước" onclick={()=>remove(i)}><Trash size={12}/></Button>
        </div>
      </div>
    {/each}
  </div>

  <div class="steps-add">
    <Button type="button" variant="outline" size="sm" onclick={()=>add("click")}><CursorClick/> Bấm selector</Button>
    <Button type="button" variant="outline" size="sm" onclick={()=>add("select")}><CursorClick/> Chọn option</Button>
    <Button type="button" variant="outline" size="sm" onclick={()=>add("press","Enter")}><Keyboard/> Nhấn Enter</Button>
    <Button type="button" variant="outline" size="sm" onclick={()=>add("wait","400")}><Clock/> Chờ 400ms</Button>
    <Button type="button" variant="ghost" size="sm" onclick={()=>{ steps=[{kind:"click",arg:"#model-dropdown"},{kind:"click",arg:".model-option"},{kind:"press",arg:"Enter"}]; }}><PlusCircle/> Mẫu: dropdown → chọn → Enter</Button>
  </div>

  <div class="steps-preview font-data">{value || "— chưa có action —"}</div>
</div>

<style>
  .steps-editor{display:grid;gap:.55rem}
  .steps-empty{color:var(--muted-foreground);font-size:.72rem;line-height:1.5;border:1px dashed var(--border);border-radius:.5rem;padding:.5rem .65rem;background:var(--muted)/30}
  .steps-list{display:grid;gap:.4rem}
  .step-row{display:flex;align-items:center;gap:.35rem;min-width:0;padding:.35rem;border:1px solid var(--border);border-radius:.55rem;background:var(--background)}
  .step-idx{width:1.35rem;height:1.35rem;display:grid;place-items:center;border-radius:999px;background:var(--primary);color:var(--primary-foreground);font-size:.65rem;font-weight:700;flex-shrink:0}
  .step-actions{display:flex;gap:.15rem;flex-shrink:0}
  .unit{font-size:.68rem;color:var(--muted-foreground)}
  .steps-add{display:flex;flex-wrap:wrap;gap:.35rem}
  .steps-preview{font-size:.68rem;color:var(--muted-foreground);word-break:break-all;border-top:1px dashed var(--border);padding-top:.35rem}
  .compact .step-row{padding:.3rem}
</style>
