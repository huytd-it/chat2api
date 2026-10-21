<script lang="ts">
  import { ArrowRight, ArrowClockwise, MagnifyingGlass, Globe, WarningCircle } from "phosphor-svelte";
  import { apiKey, serverStatus } from "$lib/stores";
  import { fetchTestTargets, type TestTarget } from "$lib/api";
  import { websites, websiteCatalogState, websiteCatalogError, refreshWebsites, belongsToWebsite } from "$lib/websites";
  import ProviderIcon from "$lib/components/sessions/ProviderIcon.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";

  let targets = $state<TestTarget[]>([]);
  let targetError = $state("");
  let loadingTargets = $state(true);
  let query = $state("");
  let initialized = $state(false);
  const visible = $derived($websites.filter((site) =>
    `${site.title} ${site.url}`.toLowerCase().includes(query.toLowerCase())));

  async function reload() {
    loadingTargets = true;
    const catalog = refreshWebsites($apiKey);
    try {
      targets = (await fetchTestTargets($apiKey)).targets;
      targetError = "";
    } catch (error) { targetError = (error as Error).message; }
    finally { loadingTargets = false; }
    await catalog;
  }
  // A packaged desktop starts the sidecar and frontend together. Do not
  // permanently retain an initial connection-refused error while health is
  // still booting and the layout later loads the catalog successfully.
  $effect(() => {
    if ($serverStatus.state === "ok" && !initialized) {
      initialized = true;
      void reload();
    }
  });
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class="mx-auto max-w-6xl px-5 py-7 md:px-10 md:py-10">
    <div class="flex flex-wrap items-start justify-between gap-5">
      <div>
        <h2 class="text-3xl font-semibold tracking-tight">Không gian làm việc</h2>
        <p class="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
          Mỗi website, một workspace. Chọn nơi bạn muốn làm việc — account,
          hội thoại và công cụ sẽ đi cùng website đó.
        </p>
      </div>
      <Button variant="outline" disabled={$websiteCatalogState === "loading" || loadingTargets} onclick={reload}>
        <ArrowClockwise /> Cập nhật
      </Button>
    </div>

    <div class="mt-8 flex flex-wrap items-center gap-4">
      <div class="relative min-w-52 flex-1 md:max-w-80">
        <MagnifyingGlass size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <Input class="bg-card pl-9" aria-label="Tìm website" placeholder="Tìm website…" bind:value={query} />
      </div>
      <span class="text-xs text-muted-foreground">{$websites.length} module · dữ liệu từ server</span>
      <a href="/profiles" class="ml-auto text-xs font-medium text-primary hover:underline">Quản lý account & profile</a>
    </div>

    {#if $websiteCatalogState === "error" || $serverStatus.state === "error"}
      <div role="alert" class="mt-6 rounded-lg bg-destructive/8 p-5 text-sm">
        <p class="font-medium">Không nạp được website</p>
        <p class="mt-1 text-muted-foreground">{$websiteCatalogError || "Backend chưa sẵn sàng hoặc không thể kết nối."}</p>
        <p class="mt-2 text-xs text-muted-foreground">Kiểm tra API key trong Cài đặt và kết nối backend, rồi cập nhật lại.</p>
        <Button variant="outline" class="mt-4" onclick={reload}>Thử lại</Button>
      </div>
    {:else if $websiteCatalogState === "loading" && !$websites.length}
      <div class="mt-6 space-y-2" aria-label="Đang nạp website" aria-busy="true">
        {#each [1, 2, 3, 4] as item (item)}<div class="h-20 animate-pulse rounded-lg bg-muted"></div>{/each}
      </div>
    {:else}
      {#if targetError}<p role="alert" class="mt-4 text-xs text-warning">Chưa đọc được account: {targetError}</p>{/if}
      <div class="mt-5 overflow-hidden rounded-xl bg-card">
        <div class="hidden grid-cols-[minmax(0,1fr)_130px_140px_24px] gap-4 border-b border-border px-5 py-3 text-xs text-muted-foreground md:grid">
          <span>Website</span><span>Account đã cấu hình</span><span>Automation</span><span></span>
        </div>
        {#each visible as site (site.id)}
          {@const accounts = targets.filter((target) => belongsToWebsite(target, site))}
          <a href={`/websites/${site.id}`} class="group grid grid-cols-[minmax(0,1fr)_24px] items-center gap-4 border-b border-border/60 px-5 py-5 transition-colors last:border-0 hover:bg-muted/60 focus-visible:outline-2 focus-visible:outline-primary md:grid-cols-[minmax(0,1fr)_130px_140px_24px]">
            <div class="flex min-w-0 items-center gap-4">
              <span class="grid size-10 shrink-0 place-items-center rounded-lg bg-muted text-foreground"><ProviderIcon model={site.slug} size={23} /></span>
              <div class="min-w-0"><h3 class="text-sm font-semibold">{site.title}</h3><p class="mt-1 truncate text-xs text-muted-foreground">{new URL(site.url).hostname}</p>
                <p class="mt-2 text-xs text-muted-foreground md:hidden">{loadingTargets || targetError ? "Account: chưa đọc được" : `${accounts.length} account đã cấu hình`} · {site.models.length ? `${site.models.length} model` : "Chưa kết nối automation"}</p>
              </div>
            </div>
            <div class="hidden text-sm md:block">{loadingTargets || targetError ? "—" : accounts.length}<span class="ml-1.5 text-xs text-muted-foreground"> account</span></div>
            <div class="hidden md:block">
              {#if site.unhealthy}<span class="inline-flex items-center gap-1.5 text-xs text-warning"><WarningCircle size={14} /> Cần kiểm tra</span>
              {:else if site.models.length}<span class="text-xs text-foreground">{site.models.length} model đã nạp</span>
              {:else}<span class="text-xs text-muted-foreground">Chờ tích hợp</span>{/if}
            </div>
            <ArrowRight size={17} class="text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
          </a>
        {:else}
          <div class="px-6 py-14 text-center"><Globe size={28} class="mx-auto mb-3 text-muted-foreground" /><p class="text-sm">Không tìm thấy website phù hợp.</p></div>
        {/each}
      </div>
      <div class="mt-6 flex flex-wrap gap-x-8 gap-y-3 text-xs leading-relaxed text-muted-foreground">
        <p>Account đã cấu hình không đồng nghĩa phiên đăng nhập còn hiệu lực.</p>
        <a href="/overview" class="text-primary hover:underline">Xem sức khỏe hệ thống</a>
        <a href="/integrations" class="text-primary hover:underline">Kết nối website khác</a>
      </div>
    {/if}
  </div>
</div>
