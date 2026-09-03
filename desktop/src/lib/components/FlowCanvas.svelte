<script lang="ts">
  import { SvelteFlow, Background, Controls, MiniMap, type Node, type Edge } from "@xyflow/svelte";
  import "@xyflow/svelte/dist/style.css";
  import { flowNodeLabel, FLOW_NODE_TYPES, type FlowDoc, type FlowEdge, type FlowNode } from "../api";
  import FlowNodeCard from "./FlowNodeCard.svelte";
  import { Plus } from "phosphor-svelte";

  interface Props {
    flow: FlowDoc;
    onNodesChange: (nodes: FlowNode[]) => void;
    onEdgesChange: (edges: FlowEdge[]) => void;
    onSelectNode: (id: string | null) => void;
  }
  let { flow, onNodesChange, onEdgesChange, onSelectNode }: Props = $props();

  const nodeTypes = { flowNode: FlowNodeCard };

  function summaryOf(n: FlowNode): string {
    const p = (n.params ?? {}) as Record<string, unknown>;
    const first = (...keys: string[]) => {
      for (const k of keys) {
        const v = p[k];
        if (v !== undefined && v !== null && String(v).trim()) return String(v);
      }
      return "";
    };
    switch (n.type) {
      case "goto-url": return first("url");
      case "fill-input": case "submit-click": case "extract-text":
        return first("selector");
      case "action-sequence": return first("action");
      case "select-model": return first("model_action", "action", "value", "model");
      case "wait-done-signal": return first("type");
      case "wait-media": case "extract-media": return first("media_selector", "copy_selector");
      case "copy-button": return first("selector");
      case "condition": return first("expression", "value");
      case "delay": return p.ms !== undefined ? `${p.ms}ms` : "";
      case "eval-js": return (first("code") as string).slice(0, 60);
      case "set-variable": return first("name");
      default: return "";
    }
  }

  function toSFNodes(nodes: FlowNode[]): Node[] {
    return nodes.map((n) => ({
      id: n.id,
      type: "flowNode",
      position: n.position ?? { x: 0, y: 0 },
      data: { nodeType: n.type, label: n.id, summary: summaryOf(n) },
    }));
  }

  function toSFEdges(edges: FlowEdge[]): Edge[] {
    return edges.map((e, i) => ({
      id: e.id ?? `e-${e.source}-${e.target}-${i}`,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle ?? undefined,
      label: e.label ?? (e.sourceHandle === "true" ? "true" : e.sourceHandle === "false" ? "false" : undefined),
    }));
  }

  let sfNodes = $state<Node[]>([]);
  let sfEdges = $state<Edge[]>([]);

  // Đồng bộ từ flow doc xuống canvas (khi load/lưu/undo ngoài).
  $effect(() => {
    sfNodes = toSFNodes(flow.nodes ?? []);
    sfEdges = toSFEdges(flow.edges ?? []);
  });

  function pushNodes(next: Node[]) {
    sfNodes = next;
    onNodesChange(
      next.map((n) => {
        const orig = (flow.nodes ?? []).find((x) => x.id === n.id);
        return {
          id: n.id,
          type: String((n.data as Record<string, unknown>)?.nodeType ?? orig?.type ?? "default"),
          position: n.position,
          params: orig?.params ?? {},
        } satisfies FlowNode;
      }),
    );
  }

  function pushEdges(next: Edge[]) {
    sfEdges = next;
    onEdgesChange(
      next.map((e) => ({
        id: String(e.id),
        source: String(e.source),
        target: String(e.target),
        sourceHandle: (e.sourceHandle as string | null) ?? null,
      }) satisfies FlowEdge),
    );
  }

  function onConnect(params: { source: string; target: string; sourceHandle?: string | null }) {
    const exists = sfEdges.some(
      (e) => e.source === params.source && e.target === params.target &&
        (e.sourceHandle ?? null) === (params.sourceHandle ?? null),
    );
    if (exists) return;
    pushEdges([
      ...sfEdges,
      {
        id: `e-${params.source}-${params.target}-${sfEdges.length}`,
        source: params.source,
        target: params.target,
        sourceHandle: params.sourceHandle ?? null,
      },
    ]);
  }

  let addType = $state<string>("delay");

  function addNode() {
    const nodes = flow.nodes ?? [];
    const base = addType === "start" || addType === "output" ? addType : addType;
    let id = base;
    let i = 1;
    const ids = new Set(nodes.map((n) => n.id));
    while (ids.has(id)) {
      i += 1;
      id = `${base}-${i}`;
    }
    const lastX = nodes.reduce((m, n) => Math.max(m, n.position?.x ?? 0), 0);
    onNodesChange([...nodes, { id, type: addType, position: { x: lastX + 220, y: 80 }, params: {} }]);
    onSelectNode(id);
  }
</script>

<div class="relative h-full w-full">
  <SvelteFlow
    bind:nodes={sfNodes}
    bind:edges={sfEdges}
    {nodeTypes}
    fitView
    nodesDraggable
    nodesConnectable
    elementsSelectable
    deleteKey={["Backspace", "Delete"]}
    onconnect={onConnect}
    onnodeclick={({ node }) => onSelectNode(String(node.id))}
    onedgeclick={({ edge }) => {
      pushEdges(sfEdges.filter((e) => e.id !== edge.id));
    }}
    onpaneclick={() => onSelectNode(null)}
    onnodedragstop={() => pushNodes(sfNodes)}
    ondelete={({ nodes, edges }) => {
      if (nodes.length) {
        const gone = new Set(nodes.map((n) => String(n.id)));
        onNodesChange((flow.nodes ?? []).filter((n) => !gone.has(n.id)));
        onEdgesChange(
          (flow.edges ?? []).filter((e) => !gone.has(e.source) && !gone.has(e.target)),
        );
        onSelectNode(null);
      } else if (edges.length) {
        const gone = new Set(edges.map((e) => String(e.id)));
        onEdgesChange(
          (flow.edges ?? []).filter((e) => !gone.has(e.id ?? `${e.source}-${e.target}`)),
        );
      }
    }}
  >
    <Background />
    <Controls />
    <MiniMap />
  </SvelteFlow>

  <div class="absolute left-2 top-2 flex items-center gap-1 rounded-lg border bg-card/95 p-1.5 shadow-sm backdrop-blur">
    <select
      class="h-8 rounded-md border border-input bg-background px-2 text-xs"
      bind:value={addType}
      aria-label="Loại node mới"
    >
      {#each FLOW_NODE_TYPES.filter((t) => t !== "start" && t !== "output") as t (t)}
        <option value={t}>{flowNodeLabel(t)}</option>
      {/each}
    </select>
    <button
      class="flex h-8 items-center gap-1 rounded-md bg-primary px-2.5 text-xs font-medium text-primary-foreground hover:bg-primary/90"
      onclick={addNode}
      title="Thêm node"
    >
      <Plus size={13} /> Thêm node
    </button>
  </div>

  <div class="pointer-events-none absolute bottom-2 left-2 rounded-md bg-card/90 px-2 py-1 text-[11px] text-muted-foreground backdrop-blur">
    Kéo thả để di chuyển · kéo từ handle để nối dây · bấm dây để xóa · Del để xóa node
  </div>
</div>

<style>
  :global(.svelte-flow) {
    background: var(--background);
  }
  :global(.svelte-flow__minimap) {
    background: var(--card) !important;
  }
</style>
