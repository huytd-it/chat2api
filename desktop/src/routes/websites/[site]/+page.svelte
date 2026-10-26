<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { websites, websiteCatalogState, refreshWebsites } from "$lib/websites";
  import { apiKey } from "$lib/stores";
  import AutomationManager from "$lib/components/AutomationManager.svelte";
  import AutomationSetup from "$lib/components/AutomationSetup.svelte";
  const site = $derived($websites.find((item) => item.id === page.params.site));
  const chatModel = $derived(site?.models.find(model => model.capability !== "image" && model.capability !== "video"));
</script>

<div class="min-h-0 flex-1 overflow-y-auto p-5 md:p-8">
  <div class="mx-auto max-w-5xl">
    {#if site}
      <a class="text-sm text-primary hover:underline" href="/">Về Web chats</a>
      <h2 class="mb-2 mt-4 text-2xl font-semibold">Cấu hình {site.title}</h2>
      <p class="mb-4 text-sm leading-relaxed text-muted-foreground">{new URL(site.url).hostname} · Cấu hình và model ID hiện có của automation này. Hội thoại và tác vụ được quản lý ở màn session dùng chung.</p>
      <div class="mb-6 flex flex-wrap gap-4 text-sm">
        <a href="/sessions" class="font-medium text-primary hover:underline">Lịch sử & session</a>
        {#if chatModel}<a href={`/sessions?model=${encodeURIComponent(chatModel.id)}`} class="text-primary hover:underline">Chat với {site.title}</a>{/if}
        <a href={`/websites/${site.id}/agent`} class="text-primary hover:underline">Tạo automation bằng agent CLI</a>
      </div>
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
