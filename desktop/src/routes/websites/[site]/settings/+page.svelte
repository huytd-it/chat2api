<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { websites, websiteCatalogState, refreshWebsites } from "$lib/websites";
  import { apiKey } from "$lib/stores";
  import AutomationManager from "$lib/components/AutomationManager.svelte";
  import AutomationSetup from "$lib/components/AutomationSetup.svelte";
  const site = $derived($websites.find((item) => item.id === page.params.site));
</script>

<div class="min-h-0 flex-1 overflow-y-auto p-5 md:p-8">
  <div class="mx-auto max-w-5xl">
    {#if site}
      <a class="text-sm text-primary hover:underline" href={`/websites/${site.id}`}>← Về workspace {site.title}</a>
      <h2 class="mb-2 mt-4 text-2xl font-semibold">Cấu hình {site.title}</h2>
      <p class="mb-6 text-sm leading-relaxed text-muted-foreground">Các cấu hình và model ID hiện có được giữ nguyên. Công cụ selector/YAML dùng engine hiện tại; không phải bằng chứng module mới đã được kiểm chứng.</p>
      {#key site.id}
        <AutomationManager {site} onManageProfiles={() => goto("/profiles")} />
        <details class="mt-6 rounded-lg bg-muted/40 p-4">
          <summary class="cursor-pointer text-sm font-medium">Thêm cấu hình cho website</summary>
          <div class="mt-4"><AutomationSetup initialUrl={site.url} onSuccess={() => refreshWebsites($apiKey)} onManageProfiles={() => goto("/profiles")} /></div>
        </details>
      {/key}
    {:else}
      <p class="text-sm text-muted-foreground">{$websiteCatalogState === "loading" ? "Đang nạp website…" : "Không đọc được website. Quay lại danh sách hoặc cập nhật dữ liệu."}</p>
      <a href="/" class="mt-4 inline-block text-primary">Danh sách website</a>
    {/if}
  </div>
</div>
