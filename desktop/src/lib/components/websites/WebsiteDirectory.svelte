<script lang="ts">
  import { goto } from "$app/navigation";
  import { Plus, ArrowClockwise, MagnifyingGlass, X, Globe } from "phosphor-svelte";
  import { apiKey, serverStatus } from "$lib/stores";
  import { addWebsite } from "$lib/api";
  import { websites, websiteCatalogState, websiteCatalogError, refreshWebsites } from "$lib/websites";
  import ProviderIcon from "$lib/components/sessions/ProviderIcon.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";

  let query = $state("");
  let adding = $state(false);
  let domain = $state("");
  let saving = $state(false);
  let error = $state("");
  let initialized = $state(false);
  const visible = $derived($websites.filter(site => `${site.title} ${site.url}`.toLowerCase().includes(query.toLowerCase())));
  $effect(() => {
    if ($serverStatus.state === "ok" && !initialized) {
      initialized = true;
      void refreshWebsites($apiKey);
    }
  });
  async function register() {
    if (!domain.trim() || saving) return;
    saving = true; error = "";
    try {
      const result = await addWebsite($apiKey, domain.trim());
      await refreshWebsites($apiKey);
      await goto(`/websites/${result.id}/agent`);
    } catch (cause) { error = (cause as Error).message; }
    finally { saving = false; }
  }
</script>

<div class="min-h-0 flex-1 overflow-y-auto">
  <div class="mx-auto max-w-5xl px-5 py-8 md:px-10 md:py-12">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div><h2 class="text-3xl font-semibold tracking-tight">Web chats</h2><p class="mt-2 text-sm text-muted-foreground">Chọn một website để làm việc.</p></div>
      <Button onclick={() => adding = !adding} aria-expanded={adding}><Plus /> Thêm web chat</Button>
    </div>
    {#if adding}
      <form class="mt-6 rounded-xl bg-card p-5" onsubmit={event => {event.preventDefault(); void register();}}>
        <div class="flex items-center justify-between"><label for="website-domain" class="text-sm font-medium">Domain website</label><Button type="button" variant="ghost" size="icon-sm" aria-label="Đóng thêm website" disabled={saving} onclick={() => adding = false}><X /></Button></div>
        <div class="mt-3 flex flex-wrap gap-3"><Input id="website-domain" class="min-w-40 flex-1" placeholder="chat.example.com" bind:value={domain} disabled={saving} required maxlength={2048} autocapitalize="none" spellcheck={false} /><Button type="submit" disabled={!domain.trim() || saving}>{saving ? "Đang lưu…" : "Thêm domain"}</Button></div>
        <p class="mt-3 text-xs leading-relaxed text-muted-foreground">Chỉ lưu domain. Sau đó dùng agent CLI để tạo automation theo ý bạn; không tự mở browser hay chạy AI.</p>
        {#if error}<p role="alert" class="mt-3 text-sm text-destructive">{error}</p>{/if}
      </form>
    {/if}
    <div class="mt-8 flex items-center gap-3">
      <div class="relative min-w-0 flex-1 sm:max-w-72"><MagnifyingGlass size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><Input class="pl-9" aria-label="Tìm website" placeholder="Tìm website…" bind:value={query} /></div>
      <Button variant="ghost" size="icon-sm" aria-label="Cập nhật website" disabled={$websiteCatalogState === "loading"} onclick={() => refreshWebsites($apiKey)}><ArrowClockwise /></Button>
    </div>
    {#if $websiteCatalogState === "error" || $serverStatus.state === "error"}
      <div role="alert" class="mt-6 rounded-lg bg-destructive/8 p-5 text-sm"><p class="font-medium">Không nạp được website</p><p class="mt-2 text-muted-foreground">{$websiteCatalogError || "Kiểm tra kết nối backend và API key trong Cài đặt."}</p><Button class="mt-4" variant="outline" onclick={() => refreshWebsites($apiKey)}>Thử lại</Button></div>
    {:else if !$websites.length && $websiteCatalogState === "loading"}
      <p class="py-16 text-sm text-muted-foreground" role="status">Đang nạp website…</p>
    {:else}
      <div class="mt-7 grid grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5" aria-label="Danh sách web chat">
        {#each visible as site (site.id)}
          <a href={`/websites/${site.id}`} class="group flex min-w-0 flex-col items-center rounded-xl px-2 py-5 text-center transition-colors hover:bg-card focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
            <span class="relative grid size-16 place-items-center rounded-2xl bg-card text-foreground transition-colors group-hover:bg-primary/8"><ProviderIcon model={site.slug} size={31} />{#if site.unhealthy}<span class="absolute right-1 top-1 size-2 rounded-full bg-warning" title="Cần kiểm tra automation"></span>{/if}</span>
            <span class="mt-3 max-w-full truncate text-sm font-medium">{site.title}</span>
            <span class="mt-1 max-w-full truncate text-[11px] text-muted-foreground">{new URL(site.url).hostname}</span>
            {#if !site.models.length}<span class="mt-1 text-[11px] text-muted-foreground">Chưa có automation</span>{/if}
          </a>
        {:else}
          <div class="col-span-full py-12 text-center text-sm text-muted-foreground"><Globe size={26} class="mx-auto mb-3" />Không tìm thấy website phù hợp.</div>
        {/each}
      </div>
      <p class="mt-10 text-xs leading-relaxed text-muted-foreground">Thêm domain trước. Nhờ agent CLI xây dựng các thao tác bạn cần sau.</p>
    {/if}
  </div>
</div>
