<script lang="ts">
  import { ArrowClockwise, Browser, WarningCircle, X } from "phosphor-svelte";
  import type { TestTarget, TestTargetList } from "../../api";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import * as Select from "$lib/components/ui/select";
  import { SEND_MODES, modelFor, type BatchJob, type RotationMode } from "./shared";

  let {
    targets,
    meta,
    loading,
    selectedIds,
    openedIds,
    targetModels,
    rotationMode = $bindable(),
    maxRequestsPerAccount = $bindable(),
    planLine,
    batchJobs,
    opening,
    onClose,
    onToggle,
    onToggleMany,
    onReload,
    onOpenWindows,
    onPickModel,
    onOpenSession,
  }: {
    targets: TestTarget[];
    meta: Omit<TestTargetList, "targets"> | null;
    loading: boolean;
    selectedIds: number[];
    openedIds: number[];
    targetModels: Record<number, string>;
    rotationMode: RotationMode;
    maxRequestsPerAccount: number;
    planLine: string;
    batchJobs: BatchJob[];
    opening: boolean;
    onClose: () => void;
    onToggle: (accountId: number) => void;
    onToggleMany: (accountIds: number[]) => void;
    onReload: () => void;
    onOpenWindows: () => void;
    onPickModel: (accountId: number, model: string) => void;
    onOpenSession: (sessionId: string) => void;
  } = $props();

  const ALL = "__all__";

  let search = $state("");
  let profileFilter = $state("");
  let domainFilter = $state("");

  const profileNames = $derived([...new Set(targets.map((item) => item.profile_name))].sort());
  const domainNames = $derived([...new Set(targets.map((item) => item.domain))].sort());

  const visibleTargets = $derived(
    targets.filter((item) => {
      if (profileFilter && item.profile_name !== profileFilter) return false;
      if (domainFilter && item.domain !== domainFilter) return false;
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return `${item.profile_name} ${item.host} ${item.label} ${item.recipes.join(" ")}`
        .toLowerCase()
        .includes(q);
    }),
  );

  /** Gom theo profile: đó là đơn vị thật của Chromium (một tiến trình, một
   * trần tab), nên trạng thái "đã mở / còn bao nhiêu tab" phải đọc được ngay. */
  const targetGroups = $derived.by(() => {
    const groups = new Map<string, { name: string; items: TestTarget[] }>();
    for (const item of visibleTargets) {
      const group = groups.get(item.profile_name) ?? { name: item.profile_name, items: [] };
      group.items.push(item);
      groups.set(item.profile_name, group);
    }
    return [...groups.values()];
  });

  const selected = $derived(targets.filter((item) => selectedIds.includes(item.account_id)));
  const selectedProfiles = $derived([...new Set(selected.map((item) => item.profile_name))]);
  const selectedDomains = $derived([...new Set(selected.map((item) => item.domain))]);

  // Trần của server: vượt thì Chromium đóng bớt profile/tab RẢNH, nên phải nói
  // trước thay vì để người dùng thấy tab tự biến mất giữa chừng.
  const overProfileCap = $derived(
    Boolean(meta) && selectedProfiles.length > (meta?.max_profiles ?? 0),
  );
  const crowdedProfiles = $derived(
    selectedProfiles.filter((name) => countSelectedIn(name) > maxTabsOf(name)),
  );

  const allVisibleSelected = $derived(
    visibleTargets.some((item) => item.ready) &&
      visibleTargets.every((item) => !item.ready || selectedIds.includes(item.account_id)),
  );

  function countSelectedIn(name: string): number {
    return selected.filter((item) => item.profile_name === name).length;
  }

  function maxTabsOf(name: string): number {
    return (
      targets.find((item) => item.profile_name === name)?.profile_max_tabs ?? meta?.max_tabs ?? 8
    );
  }

  function groupHead(name: string): TestTarget | undefined {
    return targets.find((item) => item.profile_name === name);
  }

  /** Trạng thái ô tick của một nhóm profile: hết / một phần / không. */
  function groupState(items: TestTarget[]): { all: boolean; some: boolean } {
    const ready = items.filter((item) => item.ready);
    const picked = ready.filter((item) => selectedIds.includes(item.account_id)).length;
    return { all: ready.length > 0 && picked === ready.length, some: picked > 0 };
  }

  const JOB_LABELS: Record<BatchJob["state"], string> = {
    queued: "chờ",
    running: "đang chạy",
    done: "xong",
    error: "lỗi",
  };

  const JOB_TONES: Record<BatchJob["state"], string> = {
    queued: "text-muted-foreground",
    running: "text-warning",
    done: "text-success",
    error: "text-destructive",
  };
</script>

<aside
  class="flex h-full min-h-0 w-full flex-col border-l border-border bg-card text-card-foreground"
  aria-label="Bàn test"
>
  <header class="flex flex-none items-center justify-between gap-3 border-b border-border px-3 py-3">
    <div class="min-w-0">
      <h2 class="display-face text-base font-semibold leading-none tracking-[-0.02em]">Bàn test</h2>
      <p class="mt-1 font-data text-[11px] text-muted-foreground">
        {#if loading && !targets.length}
          Đang nạp…
        {:else}
          {selected.length}/{targets.length} target · {selectedProfiles.length} profile ·
          {selectedDomains.length} domain
        {/if}
      </p>
    </div>
    <Button size="icon-sm" variant="ghost" aria-label="Đóng bàn test" onclick={onClose}>
      <X />
    </Button>
  </header>

  <div class="grid flex-none gap-2 border-b border-border p-3">
    <Input aria-label="Lọc target" placeholder="Lọc profile / domain / account…" bind:value={search} />
    <div class="grid grid-cols-2 gap-2">
      <Select.Root
        type="single"
        value={profileFilter || ALL}
        onValueChange={(value) => (profileFilter = value === ALL ? "" : value)}
      >
        <Select.Trigger class="w-full text-xs" aria-label="Lọc theo profile">
          {profileFilter || "Mọi profile"}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value={ALL} label="Mọi profile">Mọi profile</Select.Item>
          {#each profileNames as name (name)}
            <Select.Item value={name} label={name}>{name}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>

      <Select.Root
        type="single"
        value={domainFilter || ALL}
        onValueChange={(value) => (domainFilter = value === ALL ? "" : value)}
      >
        <Select.Trigger class="w-full text-xs" aria-label="Lọc theo domain">
          {domainFilter || "Mọi domain"}
        </Select.Trigger>
        <Select.Content>
          <Select.Item value={ALL} label="Mọi domain">Mọi domain</Select.Item>
          {#each domainNames as name (name)}
            <Select.Item value={name} label={name}>{name}</Select.Item>
          {/each}
        </Select.Content>
      </Select.Root>
    </div>
  </div>

  <div class="flex flex-none items-center gap-1.5 border-b border-border px-3 py-2">
    <Button
      size="xs"
      variant="outline"
      disabled={!visibleTargets.some((item) => item.ready)}
      onclick={() => onToggleMany(visibleTargets.map((item) => item.account_id))}
    >
      {allVisibleSelected ? "Bỏ chọn hết" : "Chọn tất cả"}
    </Button>
    <Button size="xs" variant="ghost" onclick={onReload}>
      <ArrowClockwise />
      Nạp lại
    </Button>
    <Button
      size="xs"
      class="ml-auto"
      disabled={!selected.length || opening}
      onclick={onOpenWindows}
    >
      <Browser />
      {opening ? "Đang mở…" : "Mở cửa sổ"}
    </Button>
  </div>

  <div class="min-h-0 flex-1 overflow-y-auto p-2">
    {#if meta && !meta.persisted}
      <p class="px-4 py-8 text-center text-xs text-muted-foreground">
        Kho dữ liệu chưa mở nên chưa có profile nào.
      </p>
    {:else if loading && targets.length === 0}
      <p class="px-4 py-8 text-center text-xs text-muted-foreground">Đang nạp ma trận target…</p>
    {:else if targets.length === 0}
      <p class="px-4 py-8 text-center text-xs text-muted-foreground">
        Chưa có account nào gắn với profile. Thêm tại Integrations → Profiles.
      </p>
    {:else if visibleTargets.length === 0}
      <p class="px-4 py-8 text-center text-xs text-muted-foreground">
        Không có target nào khớp bộ lọc.
      </p>
    {:else}
      <div class="grid gap-2">
        {#each targetGroups as group (group.name)}
          {@const head = groupHead(group.name)}
          {@const state = groupState(group.items)}
          <section class="overflow-hidden rounded-lg border border-border">
            <div class="flex items-center gap-2 bg-muted/60 px-2.5 py-2 text-[11px]">
              <Checkbox
                id={`bench-group-${group.name}`}
                checked={state.all}
                indeterminate={state.some && !state.all}
                disabled={!group.items.some((item) => item.ready)}
                onCheckedChange={() => onToggleMany(group.items.map((item) => item.account_id))}
              />
              <label for={`bench-group-${group.name}`} class="min-w-0 truncate font-data font-semibold">
                {group.name}
              </label>
              <span
                class="ml-auto flex-none {head?.profile_open ? 'text-success' : 'text-muted-foreground'}"
              >
                {head?.profile_open ? `${head.profile_tabs} tab` : "chưa mở"}
              </span>
              <span class="flex-none font-data text-muted-foreground">
                {countSelectedIn(group.name)}/{group.items.length}
              </span>
            </div>

            {#each group.items as target (target.account_id)}
              <div
                class="flex items-start gap-2 border-t border-border px-2.5 py-2
                  {selectedIds.includes(target.account_id) ? 'bg-primary/5' : ''}
                  {target.ready ? '' : 'opacity-50'}"
              >
                <div class="pt-0.5">
                  <Checkbox
                    id={`target-${target.account_id}`}
                    disabled={!target.ready}
                    checked={selectedIds.includes(target.account_id)}
                    onCheckedChange={() => onToggle(target.account_id)}
                  />
                </div>
                <div class="grid min-w-0 flex-1 gap-1.5">
                  <label
                    for={`target-${target.account_id}`}
                    class="flex flex-wrap items-center gap-1.5 text-[11px]"
                  >
                    <span class="font-data font-semibold">{target.host}</span>
                    <span class="text-muted-foreground">{target.label}</span>
                    {#if openedIds.includes(target.account_id)}
                      <Badge variant="outline" class="h-4 border-success/40 px-1.5 text-[9px] text-success">
                        đang mở
                      </Badge>
                    {/if}
                    {#if target.busy > 0}
                      <Badge
                        variant="outline"
                        class="h-4 border-warning/40 px-1.5 text-[9px] text-warning"
                        title="Request đang chạy trên account này"
                      >
                        {target.busy} đang chạy
                      </Badge>
                    {/if}
                  </label>

                  {#if target.models.length > 1}
                    <Select.Root
                      type="single"
                      value={modelFor(target, targetModels)}
                      onValueChange={(value) => onPickModel(target.account_id, value)}
                    >
                      <Select.Trigger size="sm" class="w-full font-data text-[11px]" aria-label={`Model cho ${target.host}`}>
                        {modelFor(target, targetModels)}
                      </Select.Trigger>
                      <Select.Content>
                        {#each target.models as id (id)}
                          <Select.Item value={id} label={id}>{id}</Select.Item>
                        {/each}
                      </Select.Content>
                    </Select.Root>
                  {:else if target.models.length === 1}
                    <code class="truncate font-data text-[10px] text-muted-foreground">
                      {target.models[0]}
                    </code>
                  {:else}
                    <span class="text-[10px] text-warning">chưa có recipe cho domain này</span>
                  {/if}
                </div>
              </div>
            {/each}
          </section>
        {/each}
      </div>
    {/if}
  </div>

  {#if overProfileCap || crowdedProfiles.length}
    <div class="grid flex-none gap-1.5 border-t border-border p-2">
      {#if overProfileCap}
        <p class="flex items-start gap-1.5 rounded-lg bg-warning/10 p-2 text-[10px] leading-relaxed text-warning">
          <WarningCircle size={13} class="mt-px flex-none" aria-hidden="true" />
          Đang chọn {selectedProfiles.length} profile nhưng trần POOL_MAX_PROFILES là
          {meta?.max_profiles}. Profile rảnh vượt trần có thể bị đóng — tăng ở Settings → Browser
          rồi khởi động lại server.
        </p>
      {/if}
      {#each crowdedProfiles as name (name)}
        <p class="flex items-start gap-1.5 rounded-lg bg-warning/10 p-2 text-[10px] leading-relaxed text-warning">
          <WarningCircle size={13} class="mt-px flex-none" aria-hidden="true" />
          Profile “{name}” chọn {countSelectedIn(name)} target nhưng trần chỉ {maxTabsOf(name)} tab.
        </p>
      {/each}
    </div>
  {/if}

  <div class="flex-none border-t border-border p-3">
    <span class="mb-1.5 block text-[10px] font-semibold text-muted-foreground">Cách chia prompt</span>
    <div class="flex rounded-lg border border-border p-0.5" role="group" aria-label="Cách chia prompt">
      {#each SEND_MODES as mode (mode.id)}
        <button
          type="button"
          class="h-6.5 flex-1 rounded-md text-[10px] transition-colors
            {rotationMode === mode.id
              ? 'bg-background font-medium text-foreground shadow-xs'
              : 'text-muted-foreground hover:text-foreground'}"
          title={mode.help}
          aria-pressed={rotationMode === mode.id}
          onclick={() => (rotationMode = mode.id)}
        >
          {mode.label}
        </button>
      {/each}
    </div>

    {#if rotationMode !== "broadcast"}
      <label class="mt-2 flex items-center gap-2 text-[10px] text-muted-foreground">
        Tối đa / account
        <Input
          class="h-7 w-20 font-data text-xs"
          type="number"
          min="1"
          max="100"
          bind:value={maxRequestsPerAccount}
        />
      </label>
    {/if}

    <p class="mt-2 font-data text-[10px] text-muted-foreground">{planLine}</p>
  </div>

  {#if batchJobs.length}
    <div class="max-h-56 flex-none overflow-y-auto border-t border-border p-3">
      <span class="mb-1.5 block text-[10px] font-semibold text-muted-foreground">
        Lượt chạy gần nhất
      </span>
      <div class="grid gap-1">
        {#each batchJobs as job (job.sessionId)}
          <button
            type="button"
            class="flex items-center gap-2 rounded-lg border border-border px-2 py-1.5 text-left text-[10px] transition-colors hover:bg-muted"
            title={job.detail || job.prompt}
            onclick={() => onOpenSession(job.sessionId)}
          >
            <span class="flex-none font-data text-muted-foreground">#{job.promptIndex + 1}</span>
            <span class="min-w-0 flex-1 truncate">{job.label}</span>
            <span class="flex-none {JOB_TONES[job.state]}">
              {JOB_LABELS[job.state]}{job.state === "error" && job.detail ? ` · ${job.detail}` : ""}
            </span>
          </button>
        {/each}
      </div>
    </div>
  {/if}
</aside>
