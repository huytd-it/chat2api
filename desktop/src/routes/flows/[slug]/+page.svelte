<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { apiKey, showToast } from "$lib/stores";
  import { refreshAfterFlowChange } from "$lib/sync";
  import {
    fetchFlow, saveFlow, testFlow, flowNodeLabel,
    type FlowDoc, type FlowEdge, type FlowNode, type TrialResult,
  } from "$lib/api";
  import FlowCanvas from "$lib/components/FlowCanvas.svelte";
  import FlowNodePanel from "$lib/components/FlowNodePanel.svelte";
  import TrialReport from "$lib/components/TrialReport.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Switch } from "$lib/components/ui/switch";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as Select from "$lib/components/ui/select";
  import { ArrowLeft, CircleNotch, FloppyDisk, Play } from "phosphor-svelte";

  const slug = $derived(page.params.slug ?? "");

  let flow = $state<FlowDoc | null>(null);
  let loading = $state(true);
  let loadError = $state("");
  let selectedId = $state<string | null>(null);
  let dirty = $state(false);
  let saving = $state(false);
  let saveError = $state("");

  let testing = $state(false);
  let headedTest = $state(false);
  let testPrompt = $state("");
  let testN = $state(1);
  let testResult = $state<TrialResult | null>(null);

  const selectedNode = $derived(
    selectedId ? (flow?.nodes ?? []).find((n) => n.id === selectedId) ?? null : null,
  );

  async function load() {
    loading = true;
    loadError = "";
    testResult = null;
    try {
      flow = await fetchFlow($apiKey, slug);
      selectedId = null;
      dirty = false;
    } catch (e) {
      loadError = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  onMount(load);

  function onNodesChange(nodes: FlowNode[]) {
    if (!flow) return;
    flow = { ...flow, nodes };
    dirty = true;
  }

  function onEdgesChange(edges: FlowEdge[]) {
    if (!flow) return;
    flow = { ...flow, edges };
    dirty = true;
  }

  function onNodeEdit(next: FlowNode) {
    if (!flow) return;
    flow = { ...flow, nodes: (flow.nodes ?? []).map((n) => (n.id === next.id ? next : n)) };
    dirty = true;
  }

  function onNodeDelete(id: string) {
    if (!flow) return;
    flow = {
      ...flow,
      nodes: (flow.nodes ?? []).filter((n) => n.id !== id),
      edges: (flow.edges ?? []).filter((e) => e.source !== id && e.target !== id),
    };
    if (selectedId === id) selectedId = null;
    dirty = true;
  }

  function touchMeta(patch: Partial<FlowDoc>) {
    if (!flow) return;
    flow = { ...flow, ...patch };
    dirty = true;
  }

  async function onSave() {
    if (!flow) return;
    saving = true;
    saveError = "";
    try {
      const r = await saveFlow($apiKey, slug, flow);
      flow = r.flow;
      dirty = false;
      showToast(`Đã lưu flow ${slug}`);
      await refreshAfterFlowChange();
    } catch (e) {
      saveError = (e as Error).message;
      showToast(saveError);
    } finally {
      saving = false;
    }
  }

  async function onTest() {
    testing = true;
    testResult = null;
    try {
      testResult = await testFlow($apiKey, slug, {
        headed: headedTest,
        prompt: testPrompt.trim() || undefined,
        n: testN,
      });
    } catch (e) {
      testResult = { ok: false, reply: "", error: (e as Error).message };
    } finally {
      testing = false;
    }
  }
</script>

<div class="flex min-h-0 flex-1 flex-col overflow-hidden">
  <div class="flex flex-wrap items-center gap-2 border-b px-4 py-2">
    <Button variant="ghost" size="sm" onclick={() => goto("/flows")} title="Về danh sách">
      <ArrowLeft size={15} />
    </Button>
    <span class="font-data text-sm font-semibold">{slug}</span>
    {#if flow}
      <span class="text-xs text-muted-foreground">
        {(flow.flow_type ?? flow.type ?? "text")} · {(flow.nodes ?? []).length} nodes ·
        {(flow.edges ?? []).length} edges
      </span>
      <label class="ml-2 flex items-center gap-1.5 text-xs text-muted-foreground">
        <Switch
          checked={flow.enabled !== false}
          onCheckedChange={(v) => touchMeta({ enabled: Boolean(v) })}
        />
        Bật
      </label>
      {#if dirty}<span class="text-xs text-warning">chưa lưu</span>{/if}
    {/if}
    <div class="ml-auto flex items-center gap-2">
      {#if saveError}<span class="text-xs text-destructive">{saveError}</span>{/if}
      <Button size="sm" onclick={onSave} disabled={!flow || saving || !dirty}>
        {#if saving}<CircleNotch size={15} class="animate-spin mr-1" />
        {:else}<FloppyDisk size={15} class="mr-1" />{/if}Lưu
      </Button>
    </div>
  </div>

  {#if loading}
    <div class="flex flex-1 items-center justify-center text-sm text-muted-foreground">
      <CircleNotch size={18} class="animate-spin mr-2" /> Đang nạp flow…
    </div>
  {:else if loadError || !flow}
    <div class="flex flex-1 flex-col items-center justify-center gap-2 text-sm">
      <span class="text-destructive">{loadError || "Không tìm thấy flow"}</span>
      <Button variant="outline" size="sm" onclick={load}>Tải lại</Button>
    </div>
  {:else}
    <div class="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1fr_340px]">
      <div class="min-h-[50vh] lg:min-h-0">
        <FlowCanvas
          {flow}
          {onNodesChange}
          {onEdgesChange}
          onSelectNode={(id) => (selectedId = id)}
        />
      </div>
      <aside class="flex min-h-0 flex-col gap-3 overflow-y-auto border-t p-3 lg:border-l lg:border-t-0">
        <div class="grid gap-2 rounded-lg border p-2.5">
          <div class="text-xs font-semibold">Thông tin flow</div>
          <div class="grid grid-cols-2 gap-2">
            <div class="grid gap-1">
              <Label>Kiểu</Label>
              <Select.Root
                type="single"
                value={String(flow.flow_type ?? flow.type ?? "text")}
                onValueChange={(v) => v && touchMeta({ flow_type: String(v) })}
              >
                <Select.Trigger>{flow.flow_type ?? flow.type ?? "text"}</Select.Trigger>
                <Select.Content>
                  <Select.Item value="text">text</Select.Item>
                  <Select.Item value="image">image</Select.Item>
                  <Select.Item value="video">video</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
            <div class="grid gap-1">
              <Label>Capability</Label>
              <Select.Root
                type="single"
                value={String(flow.capability ?? "chat")}
                onValueChange={(v) => v && touchMeta({ capability: String(v) })}
              >
                <Select.Trigger>{flow.capability ?? "chat"}</Select.Trigger>
                <Select.Content>
                  <Select.Item value="chat">chat</Select.Item>
                  <Select.Item value="image">image</Select.Item>
                  <Select.Item value="video">video</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
          </div>
          <div class="grid gap-1">
            <Label>Tên hiển thị</Label>
            <Input
              value={String((flow.meta as Record<string, unknown> | undefined)?.display_name ?? "")}
              oninput={(e) => touchMeta({
                meta: { ...((flow?.meta as Record<string, unknown>) ?? {}), display_name: e.currentTarget.value },
              })}
            />
          </div>
        </div>

        {#if selectedNode}
          <div class="rounded-lg border p-2.5">
            <FlowNodePanel node={selectedNode} onChange={onNodeEdit} onDelete={onNodeDelete} />
          </div>
        {:else}
          <p class="rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
            Bấm một node trên canvas để sửa tham số. Kéo từ handle phải để nối dây —
            node {flowNodeLabel("condition")} nối ra hai nhánh true/false.
          </p>
        {/if}

        <div class="grid gap-2 rounded-lg border p-2.5">
          <div class="flex items-center gap-2">
            <div class="text-xs font-semibold">Chạy thử</div>
            <label class="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
              <Switch checked={headedTest} onCheckedChange={(v) => (headedTest = Boolean(v))} />
              Hiện browser
            </label>
          </div>
          <Textarea
            rows={2}
            placeholder="Prompt thử (để trống dùng mặc định)"
            bind:value={testPrompt}
          />
          <div class="flex items-center gap-2">
            <Button size="sm" onclick={onTest} disabled={testing || dirty}>
              {#if testing}<CircleNotch size={14} class="animate-spin mr-1" />
              {:else}<Play size={14} class="mr-1" />{/if}Chạy thử
            </Button>
            {#if dirty}<span class="text-[11px] text-warning">Lưu trước khi chạy thử</span>{/if}
          </div>
          {#if testResult}<TrialReport result={testResult} />{/if}
        </div>
      </aside>
    </div>
  {/if}
</div>
