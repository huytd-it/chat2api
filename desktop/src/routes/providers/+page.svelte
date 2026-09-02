<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import ProvidersPanel from "$lib/components/ProvidersPanel.svelte";

  // Highlight slug truyền qua URL hash (?#<slug> hoặc /integrations/providers#<slug>),
  // đặt khi tạo recipe xong ở trang con Recipe.
  let highlightSlug = $state<string | null>(null);

  onMount(() => {
    const slug = decodeURIComponent(window.location.hash.replace(/^#/, ""));
    if (slug) highlightSlug = slug;
  });
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class="mx-auto flex min-h-full w-full max-w-7xl flex-col p-4 sm:p-6 lg:p-8">
    <ProvidersPanel
      {highlightSlug}
      onHighlighted={() => (highlightSlug = null)}
      onManageProfiles={() => goto("/profiles")}
    />
  </div>
</div>
