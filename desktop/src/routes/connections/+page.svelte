<script lang="ts">
  import { goto } from "$app/navigation";
  import AutomationSetup from "$lib/components/AutomationSetup.svelte";
  import { apiKey } from "$lib/stores";
  import { refreshWebsites, websites } from "$lib/websites";
  import { get } from "svelte/store";

  async function created(slug: string) {
    await refreshWebsites(get(apiKey));
    const site = get(websites).find((item) => item.history_slugs.includes(slug));
    if (site) await goto(`/websites/${site.id}/settings`);
  }
</script>

<div class="min-h-0 flex-1 overflow-y-auto p-5 md:p-8">
  <div class="mx-auto max-w-5xl">
    <h2 class="mb-2 text-2xl font-semibold">Kết nối website</h2>
    <p class="mb-6 text-sm text-muted-foreground">Giữ cấu hình tùy chỉnh, model và các thao tác đã ghi. Sau khi lưu, website xuất hiện trong danh sách workspace.</p>
    <AutomationSetup onSuccess={created} onManageProfiles={() => goto("/profiles")} />
  </div>
</div>
