<script lang="ts">
  import { onMount } from "svelte";
  import { combos, combosLoading, models, refreshCombos, refreshModels } from "$lib/sync";
  import { fetchModels, createCombo, updateCombo, deleteCombo, type ComboInfo, type ComboMember } from "$lib/api";
  import { apiKey, showToast } from "$lib/stores";
  import { get } from "svelte/store";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { Badge } from "$lib/components/ui/badge";
  import PlusIcon from "phosphor-svelte/lib/PlusIcon";
  import TrashIcon from "phosphor-svelte/lib/TrashIcon";
  import PencilIcon from "phosphor-svelte/lib/PencilIcon";
  import ArrowUpIcon from "phosphor-svelte/lib/ArrowUpIcon";
  import ArrowDownIcon from "phosphor-svelte/lib/ArrowDownIcon";
  import WarningIcon from "phosphor-svelte/lib/WarningIcon";

  let showCreate = $state(false);
  let editing: ComboInfo | null = $state(null);
  let loading = $state(false);
  let error = $state("");

  // form state
  let formSlug = $state("");
  let formDisplay = $state("");
  let formStrategy = $state("round_robin");
  let formDesc = $state("");
  let formEnabled = $state(true);
  let formMembers: ComboMember[] = $state([]);

  const strategies = [
    { value: "round_robin", label: "Xoay vòng đều", desc: "Mỗi request luân phiên sang model kế tiếp" },
    { value: "random", label: "Ngẫu nhiên", desc: "Chọn ngẫu nhiên một member mỗi lần" },
    { value: "failover", label: "Dự phòng (failover)", desc: "Thử lần lượt, hỏng thì sang member kế tiếp" },
    { value: "sticky_session", label: "Bám session", desc: "Cùng X-Chat2api-Session-Id luôn về cùng model" },
    { value: "weighted", label: "Theo trọng số", desc: "Xoay vòng nhưng theo weight (tỷ lệ)" },
  ];

  function strategyLabel(v: string) {
    return strategies.find(s => s.value === v)?.label ?? v;
  }

  onMount(async () => {
    await Promise.all([refreshCombos(), refreshModels()]);
  });

  function resetForm() {
    formSlug = "";
    formDisplay = "";
    formStrategy = "round_robin";
    formDesc = "";
    formEnabled = true;
    formMembers = [{ model_id: "", weight: 1, priority: 0 }];
    error = "";
  }

  function openCreate() {
    resetForm();
    if ($models.length && formMembers[0]) formMembers[0].model_id = $models[0].id;
    editing = null;
    showCreate = true;
  }

  function openEdit(c: ComboInfo) {
    editing = c;
    formSlug = c.slug;
    formDisplay = c.display_name;
    formStrategy = c.strategy;
    formDesc = c.description;
    formEnabled = c.enabled;
    formMembers = c.members.length ? c.members.map(m => ({ ...m })) : [{ model_id: $models[0]?.id ?? "", weight: 1, priority: 0 }];
    showCreate = true;
  }

  function addMember() {
    const fallback = $models.find(m => !formMembers.some(f => f.model_id === m.id))?.id ?? $models[0]?.id ?? "";
    formMembers = [...formMembers, { model_id: fallback, weight: 1, priority: formMembers.length }];
  }

  function removeMember(idx: number) {
    formMembers = formMembers.filter((_, i) => i !== idx).map((m, i) => ({ ...m, priority: i }));
  }

  function moveMember(idx: number, dir: number) {
    const n = idx + dir;
    if (n < 0 || n >= formMembers.length) return;
    const copy = [...formMembers];
    [copy[idx], copy[n]] = [copy[n], copy[idx]];
    formMembers = copy.map((m, i) => ({ ...m, priority: i }));
  }

  async function submit() {
    error = "";
    const members = formMembers.filter(m => m.model_id.trim()).map((m, i) => ({ model_id: m.model_id.trim(), weight: formStrategy === "weighted" ? Math.max(1, Math.min(100, m.weight || 1)) : 1, priority: i }));
    if (!formSlug.trim()) { error = "Thiếu slug"; return; }
    if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(formSlug.trim().toLowerCase())) { error = "Slug chỉ gồm a-z 0-9 và -"; return; }
    if (members.length < 1) { error = "Cần ít nhất 1 member"; return; }
    const uniq = new Set(members.map(m => m.model_id));
    if (uniq.size !== members.length) { error = "Member bị trùng"; return; }
    loading = true;
    try {
      const key = get(apiKey);
      if (editing) {
        await updateCombo(key, editing.slug, {
          display_name: formDisplay.trim(),
          strategy: formStrategy,
          description: formDesc.trim(),
          enabled: formEnabled,
          members,
        });
        showToast(`Đã cập nhật combo '${editing.slug}'`);
      } else {
        await createCombo(key, {
          slug: formSlug.trim().toLowerCase(),
          display_name: formDisplay.trim(),
          strategy: formStrategy,
          description: formDesc.trim(),
          enabled: formEnabled,
          members,
        });
        showToast(`Đã tạo combo '${formSlug}'`);
      }
      showCreate = false;
      await Promise.all([refreshCombos(), refreshModels()]);
    } catch (e) {
      error = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  async function del(c: ComboInfo) {
    if (!confirm(`Xóa combo 'combo/${c.slug}'?`)) return;
    try {
      await deleteCombo(get(apiKey), c.slug);
      showToast(`Đã xóa combo '${c.slug}'`);
      await refreshCombos();
    } catch (e) {
      showToast("Xóa thất bại: " + (e as Error).message);
    }
  }
</script>

<section class="space-y-4">
  <div class="flex flex-wrap items-center justify-between gap-3 border-b border-foreground/20 pb-4">
    <div>
      <h2 class="display-face text-xl font-semibold leading-none">Combos</h2>
      <p class="mt-1.5 max-w-xl text-xs leading-relaxed text-muted-foreground">
        Model ảo <span class="font-mono font-medium text-foreground">combo/&lt;slug&gt;</span> gộp nhiều model thật với chiến lược xoay vòng.
        Client chỉ cần gọi một model ID duy nhất, server tự phân phối sang các upstream bên trong.
      </p>
    </div>
    <Button size="sm" onclick={openCreate}><PlusIcon size={16} /> Tạo combo</Button>
  </div>

  {#if $combosLoading}
    <div class="py-10 text-center text-sm text-muted-foreground">Đang tải...</div>
  {:else if !$combos.length}
    <div class="rounded-lg border border-dashed border-border p-8 text-center">
      <p class="text-sm font-medium">Chưa có combo nào</p>
      <p class="mx-auto mt-1 max-w-md text-xs text-muted-foreground">Tạo combo để gộp 2+ model (ví dụ <span class="font-mono">qwen-web/qwen-web</span> + <span class="font-mono">gemini-web/gemini-web</span>) với chế độ xoay vòng.</p>
      <Button variant="outline" size="sm" class="mt-4" onclick={openCreate}>Tạo combo đầu tiên</Button>
    </div>
  {:else}
    <div class="overflow-hidden rounded-lg border border-border">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th class="px-3 py-2 text-left font-medium">Model ID</th>
              <th class="px-3 py-2 text-left font-medium">Chiến lược</th>
              <th class="px-3 py-2 text-left font-medium">Members</th>
              <th class="px-3 py-2 text-left font-medium">Trạng thái</th>
              <th class="px-3 py-2 text-right font-medium">Thao tác</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-border">
            {#each $combos as c (c.slug)}
              <tr class="hover:bg-muted/20">
                <td class="px-3 py-2.5">
                  <div class="font-mono text-xs font-medium">combo/{c.slug}</div>
                  {#if c.display_name}<div class="text-xs text-muted-foreground">{c.display_name}</div>{/if}
                  {#if c.description}<div class="max-w-xs truncate text-[11px] text-muted-foreground">{c.description}</div>{/if}
                </td>
                <td class="px-3 py-2.5"><Badge variant="secondary" class="font-data text-[11px]">{strategyLabel(c.strategy)}</Badge></td>
                <td class="px-3 py-2.5">
                  <div class="flex flex-wrap gap-1">
                    {#each c.members as m}
                      <span class="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">
                        {m.model_id}
                        {#if c.strategy === "weighted"}<span class="text-muted-foreground">×{m.weight}</span>{/if}
                      </span>
                    {/each}
                  </div>
                </td>
                <td class="px-3 py-2.5">
                  {#if c.enabled}<Badge variant="success">Bật</Badge>{:else}<Badge variant="outline">Tắt</Badge>{/if}
                </td>
                <td class="px-3 py-2.5 text-right">
                  <div class="inline-flex gap-1">
                    <Button variant="ghost" size="icon" class="size-7" onclick={() => openEdit(c)}><PencilIcon size={14} /></Button>
                    <Button variant="ghost" size="icon" class="size-7 text-destructive" onclick={() => del(c)}><TrashIcon size={14} /></Button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
    <div class="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3 text-xs leading-relaxed text-warning">
      <WarningIcon size={14} class="mt-0.5 shrink-0" />
      <span><strong>Gợi ý:</strong> Dùng <span class="font-mono">round_robin</span> để dàn đều tải, <span class="font-mono">failover</span> để dự phòng khi upstream hay lỗi, <span class="font-mono">sticky_session</span> để cùng một <span class="font-mono">X-Chat2api-Session-Id</span> luôn về cùng model.</span>
    </div>
  {/if}
</section>

<Dialog.Root bind:open={showCreate}>
  <Dialog.Content class="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>{editing ? `Sửa combo/${editing.slug}` : "Tạo combo mới"}</Dialog.Title>
      <Dialog.Description>
        ID dạng <span class="font-mono">combo/&lt;slug&gt;</span>. Slug gộp nhiều model đã có trong <span class="font-mono">/v1/models</span>.
      </Dialog.Description>
    </Dialog.Header>

    <div class="grid gap-4 py-2">
      {#if error}<div class="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>{/if}

      <div class="grid gap-2">
        <Label>Slug *</Label>
        <div class="flex items-center gap-2">
          <span class="font-mono text-sm text-muted-foreground">combo/</span>
          <Input bind:value={formSlug} placeholder="my-combo" disabled={!!editing} class="font-mono" />
        </div>
        {#if editing}<p class="text-[11px] text-muted-foreground">Không đổi slug sau khi tạo (xóa rồi tạo lại nếu cần).</p>{/if}
      </div>

      <div class="grid gap-2">
        <Label>Tên hiển thị</Label>
        <Input bind:value={formDisplay} placeholder="My combo (tùy chọn)" />
      </div>

      <div class="grid gap-2">
        <Label>Chiến lược xoay vòng *</Label>
        <Select.Root type="single" bind:value={formStrategy}>
          <Select.Trigger class="w-full">{strategyLabel(formStrategy)}</Select.Trigger>
          <Select.Content>
            {#each strategies as s}
              <Select.Item value={s.value} label={s.label}>{s.label} — {s.desc}</Select.Item>
            {/each}
          </Select.Content>
        </Select.Root>
        <p class="text-[11px] text-muted-foreground">{strategies.find(s => s.value === formStrategy)?.desc}</p>
      </div>

      <div class="grid gap-2">
        <Label>Mô tả</Label>
        <Input bind:value={formDesc} placeholder="Dùng cho..." />
      </div>

      <label class="flex items-center gap-2 text-sm">
        <input type="checkbox" bind:checked={formEnabled} class="rounded" /> Bật combo
      </label>

      <div class="space-y-2">
        <div class="flex items-center justify-between">
          <Label>Members ({formMembers.length}) *</Label>
          <Button variant="outline" size="sm" onclick={addMember} disabled={!$models.length}><PlusIcon size={14} /> Thêm</Button>
        </div>
        {#if !$models.length}
          <p class="text-xs text-destructive">Chưa có model nào — hãy tạo recipe trước.</p>
        {/if}
        {#each formMembers as m, idx}
          <div class="flex items-center gap-2 rounded-md border border-border p-2">
            <span class="font-mono text-xs text-muted-foreground">#{idx+1}</span>
            <select bind:value={m.model_id} class="flex-1 rounded-md border border-input bg-background px-2 py-1.5 font-mono text-xs">
              {#each $models as model}
                <option value={model.id}>{model.id}</option>
              {/each}
            </select>
            {#if formStrategy === "weighted"}
              <Input type="number" bind:value={m.weight} min={1} max={100} class="w-20" placeholder="w" />
            {/if}
            <div class="flex gap-1">
              <Button variant="ghost" size="icon" class="size-7" disabled={idx===0} onclick={() => moveMember(idx,-1)}><ArrowUpIcon size={14} /></Button>
              <Button variant="ghost" size="icon" class="size-7" disabled={idx===formMembers.length-1} onclick={() => moveMember(idx,1)}><ArrowDownIcon size={14} /></Button>
              <Button variant="ghost" size="icon" class="size-7 text-destructive" disabled={formMembers.length<=1} onclick={() => removeMember(idx)}><TrashIcon size={14} /></Button>
            </div>
          </div>
        {/each}
        <p class="text-[11px] text-muted-foreground">Thứ tự = priority. Kéo lên/xuống để đổi. Với <span class="font-mono">weighted</span> thì trọng số cao được chọn nhiều hơn.</p>
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (showCreate=false)}>Hủy</Button>
      <Button onclick={submit} disabled={loading}>{loading ? "Đang lưu..." : (editing ? "Lưu" : "Tạo")}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
