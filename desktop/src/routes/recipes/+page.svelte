<script lang="ts">
  import RecipeCreatePanel from "$lib/components/RecipeCreatePanel.svelte";
  import { goto } from "$app/navigation";

  function goToProvidersAndHighlight(slug: string) {
    goto(`/providers#${encodeURIComponent(slug)}`);
  }
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class="mx-auto flex min-h-full w-full max-w-7xl flex-col p-4 sm:p-6 lg:p-8">
    <RecipeCreatePanel onSuccess={goToProvidersAndHighlight} onManageProfiles={() => goto("/profiles")} />
  </div>
</div>
