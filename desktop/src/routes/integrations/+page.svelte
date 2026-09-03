<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { goto } from "$app/navigation";
import ProvidersPanel from "$lib/components/ProvidersPanel.svelte";
import ProfilesPanel from "$lib/components/ProfilesPanel.svelte";
import CombosPanel from "$lib/components/CombosPanel.svelte";
  import { recipes, openaiProviders, profiles, combos, refreshIntegrations } from "$lib/sync";
  import * as Tabs from "$lib/components/ui/tabs";
import { Badge } from "$lib/components/ui/badge";
import { Browser, Stack } from "phosphor-svelte";
import ShuffleIcon from "phosphor-svelte/lib/ShuffleIcon";

  let loadError = $state("");
  let activeTab = $state("providers");
  let hasChosenDefault = $state(false);
  let highlightSlug = $state<string | null>(null);

  const unhealthyCount = $derived($recipes.filter((r) => r.unhealthy).length);
  const providerCount = $derived($recipes.length + $openaiProviders.length);

  onMount(async () => {
    try { await refreshIntegrations(); }
    catch (error) { loadError = (error as Error).message; }
    finally {
      hasChosenDefault = true;
    }
  });
</script>

<section class="flex h-full flex-col overflow-hidden" aria-labelledby="integrations-title">
  <!-- Fixed page header -->
  <div class="shrink-0 border-b bg-background">
    <div class="mx-auto w-full max-w-7xl px-4 pt-4 sm:px-6 sm:pt-6 lg:px-8">
      <div class="border-b border-foreground/20 pb-5">
        <div class="mb-2 flex items-center gap-2 font-data text-[10px] font-medium tracking-[0.1em] text-primary">
          <span class="h-px w-5 bg-primary" aria-hidden="true"></span>
          CHANNEL DIRECTORY
        </div>
        <h1 id="integrations-title" class="display-face text-3xl font-semibold leading-none tracking-[-0.035em] md:text-[2.3rem]">Integrations</h1>
        <p class="mt-2 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">Biến web chat thành API. <strong class="font-medium text-foreground">Providers</strong> giữ recipe/model (Browser & OpenAI); <strong class="font-medium text-foreground">Profiles</strong> giữ browser và đăng nhập.</p>
      </div>
      {#if loadError}<div class="mt-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">Không tải được integrations: {loadError}</div>{/if}
    </div>
  </div>

  <Tabs.Root bind:value={activeTab} class="flex min-h-0 flex-1 flex-col overflow-hidden">
    <!-- Fixed tab nav (outside scroll) -->
    <div class="shrink-0 border-b bg-background">
      <div class="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <Tabs.List class="w-full max-w-full overflow-x-auto sm:w-fit">
          <Tabs.Trigger value="providers">
            <Browser /> Providers
            {#if providerCount}<Badge variant="secondary">{providerCount}</Badge>{/if}
            {#if unhealthyCount}<Badge variant="destructive">{unhealthyCount}</Badge>{/if}
          </Tabs.Trigger>
          <Tabs.Trigger value="combos">
            <ShuffleIcon /> Combos
            {#if $combos.length}<Badge variant="secondary">{$combos.length}</Badge>{/if}
          </Tabs.Trigger>
          <Tabs.Trigger value="profiles">
            <Stack /> Profiles
            {#if $profiles.length}<Badge variant="secondary">{$profiles.length}</Badge>{/if}
          </Tabs.Trigger>
        </Tabs.List>
      </div>
    </div>

    <!-- Full-height bodies: single page scroll, no inner Card scroll -->
    <div class="min-h-0 flex-1 overflow-y-auto">
      <div class="mx-auto flex min-h-full w-full max-w-7xl flex-col p-4 sm:p-6 lg:p-8">
        <Tabs.Content value="providers" class="mt-0 flex flex-1 flex-col data-[state=inactive]:hidden">
          <ProvidersPanel
            {highlightSlug}
            onHighlighted={() => (highlightSlug = null)}
            onManageProfiles={() => (activeTab = "profiles")}
          />
        </Tabs.Content>
        <Tabs.Content value="combos" class="mt-0 flex flex-1 flex-col data-[state=inactive]:hidden">
          <CombosPanel />
        </Tabs.Content>
        <Tabs.Content value="profiles" class="mt-0 flex flex-1 flex-col data-[state=inactive]:hidden">
          <ProfilesPanel />
        </Tabs.Content>
      </div>
    </div>
  </Tabs.Root>
</section>
