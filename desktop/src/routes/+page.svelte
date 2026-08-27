<script lang="ts">
  import { onMount } from "svelte";
  import { serverStatus } from "$lib/stores";
  import {
    overview,
    recipes,
    accounts,
    refreshOverview,
    refreshRecipes,
    refreshAccounts,
    refreshModels,
  } from "$lib/sync";
  import PageShell from "$lib/components/PageShell.svelte";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import ArrowClockwiseIcon from "phosphor-svelte/lib/ArrowClockwiseIcon";
  import WarningIcon from "phosphor-svelte/lib/WarningIcon";
  import CheckCircleIcon from "phosphor-svelte/lib/CheckCircleIcon";
  import GlobeIcon from "phosphor-svelte/lib/GlobeIcon";

  let refreshing = $state(false);
  let loaded = $state(false);

  onMount(async () => {
    await refreshOverview();
    loaded = true;
  });

  async function refreshAll() {
    refreshing = true;
    try {
      await Promise.all([refreshOverview(), refreshRecipes(), refreshAccounts(), refreshModels()]);
    } finally {
      refreshing = false;
    }
  }

  const unhealthy = $derived($overview?.unhealthy ?? []);
  const openBrowsers = $derived($overview?.open_browsers ?? []);
  // Domain có recipe nhưng chưa có account nào: recipe đó đang chạy ẩn danh.
  const domainsWithoutAccounts = $derived(
    $accounts.filter((d) => d.recipes.length > 0 && d.accounts.length === 0),
  );

  const stats = $derived([
    { label: "Models sẵn sàng", value: $overview?.models },
    { label: "Recipes", value: $overview?.recipes },
    { label: "Accounts", value: $overview?.accounts },
    { label: "Domains", value: $overview?.domains },
    { label: "Browser context", value: $overview?.contexts },
  ]);

  const healthy = $derived(
    $serverStatus.state !== "error" && !unhealthy.length && !domainsWithoutAccounts.length,
  );
</script>

<PageShell
  kicker="Trạng thái"
  title="Overview"
  description="Trạng thái server, kênh đang phục vụ và những thứ cần chú ý."
>
  {#snippet actions()}
    <Button variant="outline" size="sm" onclick={refreshAll} disabled={refreshing}>
      <ArrowClockwiseIcon size={16} class={refreshing ? "animate-spin" : ""} />
      Làm mới
    </Button>
  {/snippet}

  <!-- Health banner -->
  {#if !loaded}
    <Skeleton class="h-16 w-full rounded-xl" />
  {:else if $serverStatus.state === "error"}
    <Alert.Root variant="destructive">
      <WarningIcon size={16} />
      <Alert.Title>Mất kết nối tới server</Alert.Title>
      <Alert.Description>Kiểm tra sidecar còn chạy không, rồi bấm Làm mới.</Alert.Description>
    </Alert.Root>
  {:else if healthy}
    <Alert.Root class="border-success/40 bg-success/10 text-success dark:bg-success/15">
      <CheckCircleIcon size={16} />
      <Alert.Title>Mọi thứ đang khoẻ</Alert.Title>
      <Alert.Description class="text-success/90">
        Không có vấn đề nào. Tất cả recipe đang phục vụ bình thường.
      </Alert.Description>
    </Alert.Root>
  {:else}
    <div class="grid gap-3">
      {#if unhealthy.length}
        <Alert.Root variant="destructive">
          <WarningIcon size={16} />
          <Alert.Title>Recipe cần kiểm tra</Alert.Title>
          <Alert.Description>
            Lỗi liên tiếp: {unhealthy.join(", ")}. Mở
            <a class="font-medium underline underline-offset-2" href="/integrations">Integrations</a>
            để reload hoặc sửa selector.
          </Alert.Description>
        </Alert.Root>
      {/if}
      {#each domainsWithoutAccounts as domain (domain.domain)}
        <Alert.Root class="border-warning/40 bg-warning/10 text-warning dark:bg-warning/15">
          <WarningIcon size={16} />
          <Alert.Title>{domain.domain} chưa có account</Alert.Title>
          <Alert.Description class="text-warning/90">
            {domain.recipes.join(", ")} đang chạy ẩn danh và sẽ hết lượt dùng thử.
          </Alert.Description>
        </Alert.Root>
      {/each}
    </div>
  {/if}

  <!-- Metrics ledger -->
  <section class="border-y border-foreground/20" aria-label="Số liệu hệ thống">
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 enter-stagger">
      {#each stats as stat, index (stat.label)}
        <div class="min-h-24 border-border px-3 py-4 max-lg:border-b lg:border-r lg:last:border-r-0 sm:px-4">
          <div class="font-data text-[9px] tracking-[0.1em] text-muted-foreground">0{index + 1}</div>
          {#if !loaded}
            <Skeleton class="mt-3 h-7 w-12 rounded-sm" />
          {:else}
            <div class="display-face mt-2 text-3xl font-semibold leading-none tabular-nums text-foreground">
              {stat.value ?? "—"}
            </div>
          {/if}
          <div class="mt-2 text-xs text-muted-foreground">{stat.label}</div>
        </div>
      {/each}
    </div>
  </section>

  <div class="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(15rem,0.72fr)]">
    <!-- Running browsers -->
    <section class="border-t-2 border-foreground pt-4">
      <div class="flex items-start justify-between gap-4">
        <div>
          <h3 class="display-face text-xl font-semibold leading-none">Browser đang mở</h3>
          <p class="mt-2 text-xs text-muted-foreground">Cửa sổ được giữ nguyên tới khi bạn tự tắt.</p>
        </div>
        <span class="font-data text-[10px] tracking-[0.08em] text-muted-foreground">RUNTIME / LIVE</span>
      </div>
      {#if openBrowsers.length}
        <ul class="mt-5 divide-y divide-border border-y border-border">
          {#each openBrowsers as slug, index (slug)}
            <li class="grid grid-cols-[2rem_1fr_auto] items-center gap-3 py-3 text-sm">
              <span class="font-data text-[10px] text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
              <span class="font-data font-medium">{slug}</span>
              <span class="flex items-center gap-1.5 text-[11px] text-warning">
                <span class="size-1.5 rounded-full bg-warning"></span> đang mở
              </span>
            </li>
          {/each}
        </ul>
      {:else}
        <div class="mt-5 grid min-h-36 place-items-center border border-dashed border-border bg-card/40 p-6 text-center">
          <div>
            <GlobeIcon size={26} class="mx-auto text-primary" />
            <p class="mt-3 text-sm font-medium">Runtime đang nghỉ</p>
            <p class="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
              Browser đầu tiên sẽ xuất hiện tại đây khi request bắt đầu.
            </p>
          </div>
        </div>
      {/if}
    </section>

    <!-- Shortcuts rail -->
    <aside class="bg-foreground p-5 text-background">
      <div class="font-data text-[9px] tracking-[0.12em] text-background/55">QUICK ROUTES</div>
      <h3 class="display-face mt-2 text-2xl font-semibold leading-none">Đi thẳng tới việc cần làm.</h3>
      <nav class="mt-6 divide-y divide-background/15 border-y border-background/20" aria-label="Lối tắt">
        <a class="group flex items-center justify-between py-3 text-sm font-medium" href="/sessions">
          Mở Sessions <span class="transition-transform group-hover:translate-x-1">→</span>
        </a>
        <a class="group flex items-center justify-between py-3 text-sm font-medium" href="/integrations">
          Thêm web chat <span class="transition-transform group-hover:translate-x-1">→</span>
        </a>
        <a class="group flex items-center justify-between py-3 text-sm font-medium" href="/integrations">
          Quản lý account <span class="transition-transform group-hover:translate-x-1">→</span>
        </a>
        <a class="group flex items-center justify-between py-3 text-sm font-medium" href="/settings">
          Chỉnh runtime <span class="transition-transform group-hover:translate-x-1">→</span>
        </a>
      </nav>
    </aside>
  </div>

  <!-- Channels -->
  <Card.Root>
    <Card.Header>
      <Card.Title>Kênh đang phục vụ</Card.Title>
      <Card.Description>{$recipes.length} recipe đã nạp.</Card.Description>
      <Card.Action>
        <Button variant="outline" size="sm" href="/integrations">Mở Integrations</Button>
      </Card.Action>
    </Card.Header>
    <Card.Content>
      {#if $recipes.length}
        <ul class="grid gap-1">
          {#each $recipes as recipe (recipe.slug)}
            <li class="flex items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-muted/50">
              <span
                class="size-2 shrink-0 rounded-full {recipe.unhealthy ? 'bg-destructive' : 'bg-success'}"
              ></span>
              <span class="font-medium text-foreground">{recipe.slug}</span>
              <Badge variant="outline" class="font-data ml-auto">{recipe.models.join(", ")}</Badge>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="py-4 text-center text-sm text-muted-foreground">
          Chưa có recipe nào. Bắt đầu ở trang Integrations.
        </p>
      {/if}
    </Card.Content>
  </Card.Root>
</PageShell>
