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

<PageShell title="Overview" description="Trạng thái server, kênh đang phục vụ và những thứ cần chú ý.">
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

  <!-- Metrics -->
  <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
    {#each stats as stat (stat.label)}
      <Card.Root class="gap-0 py-4">
        <Card.Content class="px-4">
          {#if !loaded}
            <Skeleton class="h-8 w-12" />
          {:else}
            <div class="font-data text-2xl font-semibold tabular-nums text-foreground">
              {stat.value ?? "—"}
            </div>
          {/if}
          <div class="mt-1 text-xs text-muted-foreground">{stat.label}</div>
        </Card.Content>
      </Card.Root>
    {/each}
  </div>

  <div class="grid gap-4 lg:grid-cols-2">
    <!-- Running browsers -->
    <Card.Root>
      <Card.Header>
        <Card.Title>Browser đang mở</Card.Title>
        <Card.Description>Cửa sổ được giữ nguyên tới khi bạn tự tắt.</Card.Description>
      </Card.Header>
      <Card.Content>
        {#if openBrowsers.length}
          <ul class="grid gap-2">
            {#each openBrowsers as slug (slug)}
              <li class="flex items-center gap-2 text-sm">
                <span class="size-2 rounded-full bg-warning"></span>
                <span class="font-data">{slug}</span>
              </li>
            {/each}
          </ul>
        {:else}
          <div class="flex flex-col items-center gap-2 py-6 text-center">
            <GlobeIcon size={28} class="text-muted-foreground/60" />
            <p class="text-sm text-muted-foreground">
              Chưa có browser nào mở. Cửa sổ sẽ mở ở request đầu tiên.
            </p>
          </div>
        {/if}
      </Card.Content>
    </Card.Root>

    <!-- Shortcuts -->
    <Card.Root>
      <Card.Header>
        <Card.Title>Lối tắt</Card.Title>
        <Card.Description>Những việc hay làm nhất.</Card.Description>
      </Card.Header>
      <Card.Content class="flex flex-wrap gap-2">
        <Button variant="outline" size="sm" href="/sessions">Mở Sessions</Button>
        <Button variant="outline" size="sm" href="/integrations">Thêm web chat mới</Button>
        <Button variant="outline" size="sm" href="/integrations">Quản lý account</Button>
        <Button variant="outline" size="sm" href="/settings">Chỉnh delay</Button>
      </Card.Content>
    </Card.Root>
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
