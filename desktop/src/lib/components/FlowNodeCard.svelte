<script lang="ts">
  import { Handle, Position, type NodeProps } from "@xyflow/svelte";
  import { flowNodeLabel } from "../api";

  let { data, selected }: NodeProps = $props();

  const ntype = $derived(String((data as Record<string, unknown>)?.nodeType ?? "default"));
  const label = $derived(String((data as Record<string, unknown>)?.label ?? flowNodeLabel(ntype)));
  const summary = $derived(String((data as Record<string, unknown>)?.summary ?? ""));
  const isStart = $derived(ntype === "start");
  const isOutput = $derived(ntype === "output");
  const isCondition = $derived(ntype === "condition");
</script>

<div
  class={`min-w-44 max-w-60 rounded-[10px] border bg-card text-card-foreground shadow-sm transition-colors ${
    selected ? "border-primary ring-2 ring-primary/30" : "border-border"
  }`}
>
  {#if !isStart}
    <Handle type="target" position={Position.Left} />
  {/if}
  <div class="border-b border-border px-2.5 py-1.5">
    <div class="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
      {flowNodeLabel(ntype)}
    </div>
    <div class="truncate text-[13px] font-medium">{label}</div>
  </div>
  {#if summary}
    <div class="truncate px-2.5 py-1 font-data text-[11px] text-muted-foreground" title={summary}>
      {summary}
    </div>
  {/if}
  {#if !isOutput}
    {#if isCondition}
      <Handle id="true" type="source" position={Position.Right} style="top: 38%;" />
      <Handle id="false" type="source" position={Position.Right} style="top: 62%;" />
    {:else}
      <Handle type="source" position={Position.Right} />
    {/if}
  {/if}
</div>
