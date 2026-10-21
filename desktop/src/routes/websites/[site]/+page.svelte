<script lang="ts">
  import { page } from "$app/state";
  import { websites, websiteCatalogState, websiteCatalogError, refreshWebsites } from "$lib/websites";
  import { apiKey } from "$lib/stores";
  import SessionWorkspace from "$lib/components/SessionWorkspace.svelte";
  import { Button } from "$lib/components/ui/button";

  const site = $derived($websites.find((item) => item.id === page.params.site));
</script>

{#if site}
  {#key site.id}<SessionWorkspace {site} />{/key}
{:else if $websiteCatalogState === "loading"}
  <div class="grid flex-1 place-items-center p-8 text-sm text-muted-foreground" aria-busy="true">Đang mở workspace…</div>
{:else}
  <div class="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
    <h2 class="text-xl font-semibold">{$websiteCatalogState === "error" ? "Không nạp được workspace" : "Không tìm thấy website"}</h2>
    <p class="max-w-lg text-sm text-muted-foreground">{$websiteCatalogError || "Chọn một website trong danh sách để bắt đầu."}</p>
    <Button variant="outline" onclick={() => refreshWebsites($apiKey)}>Thử lại</Button>
    <a href="/" class="text-sm text-primary hover:underline">Về danh sách website</a>
  </div>
{/if}
