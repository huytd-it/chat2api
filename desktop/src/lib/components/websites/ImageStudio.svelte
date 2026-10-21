<script lang="ts">
  import { ImageSquare, ArrowRight, WarningCircle } from "phosphor-svelte";
  import { generateWebsiteImage, type WebsiteInfo } from "$lib/api";
  import { apiKey, headedBrowser } from "$lib/stores";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  let { site, accountId, onCreated, onBusy }: { site: WebsiteInfo; accountId: number | null; onCreated: (id: string) => void; onBusy: (busy: boolean) => void } = $props();
  let prompt = $state("");
  let busy = $state(false);
  let error = $state("");
  const model = $derived(site.models.find((item) => item.capability === "image" || item.capability === "both")?.id);
  async function generate() {
    if (!model || !prompt.trim() || busy) return;
    busy = true; error = ""; onBusy(true);
    try { const id = await generateWebsiteImage($apiKey, model, prompt.trim(), $headedBrowser, accountId ?? undefined); prompt = ""; onCreated(id); }
    catch (cause) { error = (cause as Error).message; }
    finally { busy = false; onBusy(false); }
  }
</script>
<div class="min-h-0 flex-1 overflow-y-auto px-5 py-8 md:px-10">
  <div class="mx-auto max-w-2xl">
    <ImageSquare size={30} class="text-primary" />
    <h3 class="mt-4 text-xl font-semibold">Tạo ảnh với {site.title}</h3>
    <p class="mt-2 text-sm leading-relaxed text-muted-foreground">Mô tả hình ảnh bạn cần. Kết quả được lưu vào một phiên riêng trong chat2api để xem và tải lại.</p>
    <label for="image-prompt" class="mb-2 mt-7 block text-xs font-medium">Mô tả ảnh</label>
    <Textarea id="image-prompt" rows={6} placeholder="Chủ thể, bố cục, phong cách và những chi tiết quan trọng…" bind:value={prompt} disabled={busy} />
    <div class="mt-4 flex flex-wrap items-center justify-between gap-3"><span class="font-mono text-xs text-muted-foreground">{model}</span><Button disabled={!prompt.trim() || !model || busy} onclick={generate}><ArrowRight />{busy ? "Đang tạo ảnh…" : "Tạo ảnh"}</Button></div>
    <p class="mt-4 text-xs leading-relaxed text-muted-foreground">Việc tạo ảnh có thể mất vài phút và tiêu thụ quota của account. Không tự gửi lại nếu mất kết nối sau submit.</p>
    {#if error}<p role="alert" class="mt-5 flex items-start gap-2 rounded-lg bg-destructive/8 p-4 text-sm text-destructive"><WarningCircle size={18} class="shrink-0" />{error}</p>{/if}
  </div>
</div>
