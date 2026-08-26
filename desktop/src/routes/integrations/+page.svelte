<script lang="ts">
  import { onMount } from "svelte";
  import IntegratePanel from "$lib/components/IntegratePanel.svelte";
  import SitesPanel from "$lib/components/SitesPanel.svelte";
  import ProfilesPanel from "$lib/components/ProfilesPanel.svelte";
  import { recipes, profiles, refreshIntegrations } from "$lib/sync";
  import * as Tabs from "$lib/components/ui/tabs";
  import { Badge } from "$lib/components/ui/badge";
  import { Browser, Globe, Stack } from "phosphor-svelte";

  let loadError = $state("");
  let activeTab = $state("integrate");
  let hasChosenDefault = $state(false);
  let highlightSlug = $state<string | null>(null);

  const unhealthyCount = $derived($recipes.filter((r) => r.unhealthy).length);

  onMount(async () => {
    try { await refreshIntegrations(); }
    catch (error) { loadError = (error as Error).message; }
    finally {
      if (!hasChosenDefault) {
        activeTab = $recipes.length ? "sites" : "integrate";
        hasChosenDefault = true;
      }
    }
  });

  function goToSitesAndHighlight(slug: string) {
    activeTab = "sites";
    highlightSlug = slug;
  }
</script>

<section class="flex h-full flex-col" aria-labelledby="integrations-title">
  <div class="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 overflow-hidden p-4 sm:p-6 lg:p-8">
    <header>
      <h1 id="integrations-title" class="text-xl font-semibold tracking-tight">Integrations</h1>
      <p class="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">Biến web chat thành API. <strong class="font-medium text-foreground">Sites</strong> giữ recipe và model; <strong class="font-medium text-foreground">Profiles</strong> giữ browser và đăng nhập.</p>
    </header>

    {#if loadError}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">Không tải được integrations: {loadError}</div>{/if}

    <Tabs.Root bind:value={activeTab} class="flex min-h-0 flex-1 flex-col">
      <Tabs.List class="w-full max-w-full overflow-x-auto sm:w-fit">
        <Tabs.Trigger value="integrate"><Globe /> Thêm tích hợp</Tabs.Trigger>
        <Tabs.Trigger value="sites">
          <Browser /> Sites
          {#if $recipes.length}<Badge variant="secondary">{$recipes.length}</Badge>{/if}
          {#if unhealthyCount}<Badge variant="destructive">{unhealthyCount}</Badge>{/if}
        </Tabs.Trigger>
        <Tabs.Trigger value="profiles">
          <Stack /> Profiles
          {#if $profiles.length}<Badge variant="secondary">{$profiles.length}</Badge>{/if}
        </Tabs.Trigger>
      </Tabs.List>

      <Tabs.Content value="integrate" class="mt-3 min-h-0 flex-1 overflow-y-auto">
        <IntegratePanel onSuccess={goToSitesAndHighlight} />
      </Tabs.Content>
      <Tabs.Content value="sites" class="mt-3 min-h-0 flex-1 overflow-y-auto">
        <SitesPanel
          {highlightSlug}
          onHighlighted={() => (highlightSlug = null)}
          onManageProfiles={() => (activeTab = "profiles")}
        />
      </Tabs.Content>
      <Tabs.Content value="profiles" class="mt-3 min-h-0 flex-1 overflow-y-auto">
        <ProfilesPanel />
      </Tabs.Content>
    </Tabs.Root>
  </div>
</section>
