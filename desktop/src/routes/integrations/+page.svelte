<script lang="ts">
  import { onMount } from "svelte";
  import IntegratePanel from "$lib/components/IntegratePanel.svelte";
  import SitesPanel from "$lib/components/SitesPanel.svelte";
  import ProfilesPanel from "$lib/components/ProfilesPanel.svelte";
  import { refreshIntegrations } from "$lib/sync";
  import { ArrowDown, Browser, Globe, Stack } from "phosphor-svelte";

  let loadError = $state("");
  onMount(async () => {
    try { await refreshIntegrations(); }
    catch (error) { loadError = (error as Error).message; }
  });
</script>

<section class="h-full overflow-y-auto" aria-labelledby="integrations-title">
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-5 p-4 sm:p-6 lg:p-8">
    <header>
      <h1 id="integrations-title" class="text-xl font-semibold tracking-tight">Integrations</h1>
      <p class="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">Biến web chat thành API, theo dõi analyzer, rồi quản lý sites và browser profiles trong một workflow.</p>
    </header>

    <nav class="grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-2 rounded-lg border bg-card p-2 text-xs text-muted-foreground" aria-label="Quy trình integration">
      <a href="#add-integration" class="flex min-w-0 items-center justify-center gap-2 rounded-md px-2 py-2 hover:bg-muted hover:text-foreground"><Globe class="shrink-0" /><span class="hidden truncate sm:inline">Thêm integration</span><span class="sm:hidden">Thêm</span></a><ArrowDown class="-rotate-90" aria-hidden="true" />
      <a href="#sites" class="flex min-w-0 items-center justify-center gap-2 rounded-md px-2 py-2 hover:bg-muted hover:text-foreground"><Browser class="shrink-0" /><span class="hidden truncate sm:inline">Sites & accounts</span><span class="sm:hidden">Sites</span></a><ArrowDown class="-rotate-90" aria-hidden="true" />
      <a href="#profiles" class="flex min-w-0 items-center justify-center gap-2 rounded-md px-2 py-2 hover:bg-muted hover:text-foreground"><Stack class="shrink-0" /><span class="hidden truncate sm:inline">Profiles</span><span class="sm:hidden">Profiles</span></a>
    </nav>

    {#if loadError}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">Không tải được integrations: {loadError}</div>{/if}
    <div id="add-integration" class="scroll-mt-4"><IntegratePanel /></div>
    <div id="sites" class="scroll-mt-4"><SitesPanel /></div>
    <div id="profiles" class="scroll-mt-4"><ProfilesPanel /></div>
  </div>
</section>
