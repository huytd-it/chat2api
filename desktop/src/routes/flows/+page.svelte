<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { apiKey, showToast } from "$lib/stores";
  import { flows, flowsLoading, flowsError, refreshFlows } from "$lib/sync";
  import { deleteFlow, duplicateFlow, type FlowSummary } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Badge } from "$lib/components/ui/badge";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import * as Card from "$lib/components/ui/card";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { CircleNotch, Copy, GitBranch, PencilSimple, Play, Plus, Trash, WarningCircle } from "phosphor-svelte";

  let query = $state("");
  let busySlug = $state<string | null>(null);
  let deleteTarget = $state<FlowSummary | null>(null);
  let dupTarget = $state<FlowSummary | null>(null);
  let dupName = $state("");
  let dupBusy = $state(false);

  const filtered = $derived(
    $flows.filter((f) =>
      !query.trim() ||
      f.slug.includes(query.trim().toLowerCase()) ||
      (f.source_recipe ?? "").includes(query.trim().toLowerCase()),
    ),
  );

  onMount(() => {
    refreshFlows();
  });

  function cleanSlug(raw: string): string | null {
    const next = raw.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(next)) {
      showToast("Slug chỉ gồm chữ thường, số và dấu -");
      return null;
    }
    return next;
  }

  async function onDelete() {
    if (!deleteTarget) return;
    busySlug = deleteTarget.slug;
    try {
      await deleteFlow($apiKey, deleteTarget.slug);
      showToast(`Đã xóa flow ${deleteTarget.slug}`);
      deleteTarget = null;
      await refreshFlows();
    } catch (e) {
      showToast("Xóa flow thất bại: " + (e as Error).message);
    } finally {
      busySlug = null;
    }
  }

  function openDuplicate(target: FlowSummary) {
    dupTarget = target;
    dupName = target.slug + "-copy";
  }

  async function onDuplicate() {
    if (!dupTarget) return;
    const next = cleanSlug(dupName);
    if (!next) return;
    dupBusy = true;
    try {
      const r = await duplicateFlow($apiKey, dupTarget.slug, next);
      showToast(`Đã copy thành ${r.slug}`);
      dupTarget = null;
      await refreshFlows();
      goto(`/flows/${encodeURIComponent(r.slug)}`);
    } catch (e) {
      showToast("Copy flow thất bại: " + (e as Error).message);
    } finally {
      dupBusy = false;
    }
  }
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class="mx-auto flex min-h-full w-full max-w-7xl flex-col gap-4 p-4 sm:p-6 lg:p-8">
    <div class="flex flex-wrap items-center gap-3">
      <div class="flex items-center gap-2">
        <GitBranch size={20} />
        <h1 class="text-lg font-semibold">Flows</h1>
      </div>
      <p class="text-sm text-muted-foreground">
        Mỗi flow là một model — canvas kiểu n8n, chạy bằng executor riêng.
      </p>
      <div class="ml-auto flex items-center gap-2">
        <Input
          class="w-56"
          placeholder="Lọc theo slug…"
          bind:value={query}
        />
        <Button variant="outline" onclick={() => refreshFlows()} disabled={$flowsLoading}>
          {#if $flowsLoading}<CircleNotch size={15} class="animate-spin" />{:else}Tải lại{/if}
        </Button>
      </div>
    </div>

    {#if $flowsLoading && $flows.length === 0}
      <div class="grid gap-2">
        {#each [1, 2, 3] as i (i)}<Skeleton class="h-16 w-full" />{/each}
      </div>
    {:else if $flowsError}
      <Card.Root>
        <Card.Content class="flex items-center gap-2 py-6 text-sm text-destructive">
          <WarningCircle size={16} /> Không nạp được flows.
          <Button variant="outline" size="sm" onclick={() => refreshFlows()}>Thử lại</Button>
        </Card.Content>
      </Card.Root>
    {:else if filtered.length === 0}
      <Card.Root>
        <Card.Content class="py-8 text-center text-sm text-muted-foreground">
          {#if $flows.length === 0}
            Chưa có flow nào. Khởi động server để auto-convert từ recipes hiện có,
            hoặc copy nhanh từ một flow khác.
          {:else}
            Không có flow nào khớp “{query}”.
          {/if}
        </Card.Content>
      </Card.Root>
    {:else}
      <div class="grid gap-2">
        {#each filtered as f (f.slug)}
          <Card.Root class={f.enabled === false ? "opacity-60" : ""}>
            <Card.Content class="flex flex-wrap items-center gap-x-3 gap-y-2 py-3">
              <button
                class="min-w-0 flex-1 text-left"
                onclick={() => goto(`/flows/${encodeURIComponent(f.slug)}`)}
                title="Mở canvas"
              >
                <span class="font-data text-sm font-medium">{f.slug}</span>
                <span class="ml-2 text-xs text-muted-foreground">
                  {f.flow_type} · {f.node_count} nodes · {f.edge_count} edges
                </span>
                {#if f.source_recipe}
                  <span class="ml-2 text-xs text-muted-foreground">từ {f.source_recipe}</span>
                {/if}
              </button>
              <Badge variant={f.enabled === false ? "secondary" : "default"}>
                {f.enabled === false ? "tắt" : "bật"}
              </Badge>
              {#if f.errors?.length}
                <Badge variant="destructive" title={f.errors.join("; ")}>lỗi</Badge>
              {/if}
              {#if f.parse_error}
                <Badge variant="destructive" title={f.parse_error}>hỏng file</Badge>
              {/if}
              <div class="flex items-center gap-1">
                <Button
                  variant="ghost" size="sm"
                  title="Mở canvas"
                  onclick={() => goto(`/flows/${encodeURIComponent(f.slug)}`)}
                >
                  <PencilSimple size={15} />
                </Button>
                <Button variant="ghost" size="sm" title="Copy nhanh" onclick={() => openDuplicate(f)}>
                  <Copy size={15} />
                </Button>
                <Button
                  variant="ghost" size="sm" title="Xóa"
                  disabled={busySlug === f.slug}
                  onclick={() => (deleteTarget = f)}
                >
                  {#if busySlug === f.slug}<CircleNotch size={15} class="animate-spin" />
                  {:else}<Trash size={15} />{/if}
                </Button>
              </div>
            </Card.Content>
          </Card.Root>
        {/each}
      </div>
    {/if}

    <p class="text-xs text-muted-foreground">
      Muốn thêm flow mới? Mở một flow gần giống nhất rồi bấm <Copy size={11} class="inline" /> để copy nhanh —
      1 flow = 1 model, đặt tên flow như tên model.
    </p>
  </div>
</div>

<AlertDialog.Root open={deleteTarget !== null}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>Xóa flow {deleteTarget?.slug}?</AlertDialog.Title>
      <AlertDialog.Description>
        Flow bị xóa khỏi data/flows và gỡ khỏi /v1/models. Model này trong Combos
        (nếu có) sẽ hỏng cho tới khi bạn sửa combo.
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={() => (deleteTarget = null)}>Hủy</AlertDialog.Cancel>
      <AlertDialog.Action onclick={onDelete}>Xóa</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={dupTarget !== null}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>Copy flow {dupTarget?.slug}</AlertDialog.Title>
      <AlertDialog.Description>Đặt tên flow mới (cũng là tên model mới).</AlertDialog.Description>
    </AlertDialog.Header>
    <div class="grid gap-2 py-2">
      <Input placeholder="ten-flow-moi" bind:value={dupName} disabled={dupBusy} />
    </div>
    <AlertDialog.Footer>
      <AlertDialog.Cancel onclick={() => (dupTarget = null)} disabled={dupBusy}>Hủy</AlertDialog.Cancel>
      <Button onclick={onDuplicate} disabled={dupBusy}>
        {#if dupBusy}<CircleNotch size={15} class="animate-spin mr-1" />{/if}Copy
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
