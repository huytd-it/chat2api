<script lang="ts">
  import { ImageSquare, ArrowRight, WarningCircle } from "phosphor-svelte";
  import { generateWebsiteImage, openTestTarget, type ModelInfo, type TestTarget } from "$lib/api";
  import { apiKey, headedBrowser } from "$lib/stores";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  let { models, targets, initialModel = "", onCreated, onBusy }: { models: ModelInfo[]; targets: TestTarget[]; initialModel?: string; onCreated: (id: string) => void; onBusy: (busy: boolean) => void } = $props();
  let prompt = $state("");
  let busy = $state(false);
  let error = $state("");
  let model = $state("");
  let accountId = $state<number | null>(null);
  let opening = $state(false);
  const accounts = $derived(targets.filter(target => target.ready && target.models.includes(model)));
  $effect(() => { if (!busy && !models.some(item => item.id === model)) model = models.find(item => item.id === initialModel)?.id || models[0]?.id || ""; });
  $effect(() => { if (!busy && accountId && !accounts.some(item => item.account_id === accountId)) accountId = null; });
  async function openProfile() {
    if (!model || !accountId || opening || busy) return;
    opening = true; error = "";
    try { await openTestTarget($apiKey, model, accountId); }
    catch (cause) { error = (cause as Error).message; }
    finally { opening = false; }
  }
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
    <h3 class="mt-4 text-xl font-semibold">Tạo ảnh</h3>
    <p class="mt-2 text-sm leading-relaxed text-muted-foreground">Mô tả hình ảnh bạn cần. Kết quả được lưu vào một phiên riêng trong chat2api để xem và tải lại.</p>
    <div class="mt-5 grid gap-4 sm:grid-cols-2">
      <label class="grid gap-1.5 text-xs text-muted-foreground">Model tạo ảnh<select class="workspace-select" bind:value={model} disabled={busy}>{#each models as item (item.id)}<option value={item.id}>{item.id}</option>{/each}</select></label>
      <label class="grid gap-1.5 text-xs text-muted-foreground">Account tạo ảnh<select class="workspace-select" value={accountId ?? "auto"} disabled={busy} onchange={event => accountId = event.currentTarget.value === "auto" ? null : Number(event.currentTarget.value)}><option value="auto">Tự chọn account</option>{#each accounts as account (account.account_id)}<option value={account.account_id}>{account.profile_name} · {account.label}</option>{/each}</select></label>
    </div>
    <div class="mt-3 flex flex-wrap items-center gap-4"><label class="flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" bind:checked={$headedBrowser} disabled={busy} />Hiện browser</label><Button variant="ghost" size="sm" disabled={!accountId || busy || opening} onclick={openProfile}>{opening ? "Đang mở…" : "Mở profile tạo ảnh"}</Button></div>
    <label for="image-prompt" class="mb-2 mt-7 block text-xs font-medium">Mô tả ảnh</label>
    <Textarea id="image-prompt" rows={6} placeholder="Chủ thể, bố cục, phong cách và những chi tiết quan trọng…" bind:value={prompt} disabled={busy} />
    <div class="mt-4 flex flex-wrap items-center justify-between gap-3"><span class="font-mono text-xs text-muted-foreground">{model}</span><Button disabled={!prompt.trim() || !model || busy} onclick={generate}><ArrowRight />{busy ? "Đang tạo ảnh…" : "Tạo ảnh"}</Button></div>
    <p class="mt-4 text-xs leading-relaxed text-muted-foreground">Việc tạo ảnh có thể mất vài phút và tiêu thụ quota của account. Không tự gửi lại nếu mất kết nối sau submit.</p>
    {#if error}<p role="alert" class="mt-5 flex items-start gap-2 rounded-lg bg-destructive/8 p-4 text-sm text-destructive"><WarningCircle size={18} class="shrink-0" />{error}</p>{/if}
  </div>
</div>
