<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { profiles, recipes, recipesLoading, openaiProviders, openaiProvidersLoading, refreshAfterRecipeChange, refreshProfiles, refreshRecipes, refreshOpenAIProviders, refreshAfterOpenAIChange } from "../sync";
  import { goto } from "$app/navigation";
  import { closeRecipeBrowser, reloadRecipe, type RecipeInfo, createOpenAIProvider, updateOpenAIProvider, deleteOpenAIProvider, type OpenAIProviderInfo } from "../api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Badge, type BadgeVariant } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { Switch } from "$lib/components/ui/switch";
  import { Browser, CaretDown, CaretRight, Check, CircleNotch, PencilSimple, Plus, Repeat, Stack, Trash, WarningCircle, X, Globe } from "phosphor-svelte";

  interface Props {
    highlightSlug?: string | null;
    onHighlighted?: () => void;
    onManageProfiles?: () => void;
  }
  let { highlightSlug = null, onHighlighted, onManageProfiles }: Props = $props();

  let expanded = $state<Record<string, boolean>>({});
  let busySlug = $state<string | null>(null);
  let panelError = $state("");
  let refreshing = $state(false);

  // ---- OpenAI provider state ----
  let showOpenAIDialog = $state(false);
  let editingOpenAI: OpenAIProviderInfo | null = $state(null);
  let oaSlug = $state("");
  let oaBaseUrl = $state("");
  let oaApiKey = $state("");
  let oaApiKeyEnv = $state("");
  let oaModels: { id: string; capability: string }[] = $state([{ id: "gpt-4o-mini", capability: "chat" }]);
  let oaStream = $state(true);
  let oaBusy = $state(false);
  let oaError = $state("");
  let deleteOpenAITarget = $state<string | null>(null);

  function profilesServing(domain: string | undefined) {
    if (!domain) return [];
    const wanted = domain.toLowerCase().replace(/^www\./, "");
    return $profiles
      .map((profile) => ({
        profile,
        accounts: profile.accounts.filter(
          (account) => account.host.toLowerCase().replace(/^www\./, "") === wanted && !account.disabled),
      }))
      .filter((item) => item.accounts.length > 0);
  }

  function toggle(slug: string) { expanded = { ...expanded, [slug]: !expanded[slug] }; }
  function fail(e: unknown) { panelError = (e as Error).message; showToast(panelError); }
  async function refresh() { refreshing = true; panelError = ""; try { await Promise.all([refreshRecipes(), refreshProfiles(), refreshOpenAIProviders()]); } catch (e) { fail(e); } finally { refreshing = false; } }
  async function onReload(slug: string) { busySlug = slug; panelError = ""; try { await reloadRecipe($apiKey, slug); await refreshAfterRecipeChange(); } catch (e) { fail(e); } finally { busySlug = null; } }
  async function onCloseBrowser(slug: string) { busySlug = slug; panelError = ""; try { const closed = await closeRecipeBrowser($apiKey, slug); showToast(closed ? `Đã tắt browser của ${slug}` : `Browser của ${slug} chưa mở`); } catch (e) { fail(e); } finally { busySlug = null; } }
  // ---- OpenAI dialog ----
  function openOpenAICreate() {
    editingOpenAI = null;
    oaSlug = "";
    oaBaseUrl = "https://api.openai.com/v1";
    oaApiKey = "";
    oaApiKeyEnv = "";
    oaModels = [{ id: "gpt-4o-mini", capability: "chat" }];
    oaStream = true;
    oaError = "";
    showOpenAIDialog = true;
  }
  function openOpenAIEdit(p: OpenAIProviderInfo) {
    editingOpenAI = p;
    oaSlug = p.slug;
    oaBaseUrl = p.base_url;
    oaApiKey = "";
    oaApiKeyEnv = p.api_key_env || "";
    oaModels = p.models.length ? p.models.map(m=>({...m})) : [{ id: "gpt-4o-mini", capability: "chat" }];
    oaStream = p.stream;
    oaError = "";
    showOpenAIDialog = true;
  }
  function addOAModel() { oaModels = [...oaModels, { id: "", capability: "chat" }]; }
  function removeOAModel(idx: number) { oaModels = oaModels.filter((_,i)=>i!==idx); }
  async function submitOpenAI() {
    oaError = "";
    const slug = oaSlug.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(slug)) { oaError = "Slug chỉ gồm chữ thường, số và dấu -"; return; }
    if (!oaBaseUrl.trim()) { oaError = "Thiếu base_url"; return; }
    try { const u = new URL(oaBaseUrl.trim()); if (!["http:","https:"].includes(u.protocol)) throw new Error(); } catch { oaError = "base_url phải là http/https URL"; return; }
    const models = oaModels.map(m=>({ id: m.id.trim(), capability: m.capability })).filter(m=>m.id);
    if (!models.length) { oaError = "Cần ít nhất 1 model"; return; }
    const seen = new Set(models.map(m=>m.id));
    if (seen.size !== models.length) { oaError = "Model id bị trùng"; return; }
    oaBusy = true;
    try {
      if (editingOpenAI) {
        const payload: any = { base_url: oaBaseUrl.trim(), models, stream: oaStream };
        if (oaApiKey.trim()) payload.api_key = oaApiKey.trim();
        if (oaApiKeyEnv.trim()) payload.api_key_env = oaApiKeyEnv.trim();
        else if (oaApiKeyEnv === "" && editingOpenAI.api_key_env) payload.api_key_env = "";
        await updateOpenAIProvider($apiKey, slug, payload);
        showToast(`Đã cập nhật provider ${slug}`);
      } else {
        await createOpenAIProvider($apiKey, { slug, base_url: oaBaseUrl.trim(), api_key: oaApiKey.trim() || undefined, api_key_env: oaApiKeyEnv.trim() || undefined, models, stream: oaStream });
        showToast(`Đã tạo provider ${slug}`);
      }
      showOpenAIDialog = false;
      await refreshAfterOpenAIChange();
    } catch (e) { oaError = (e as Error).message; }
    finally { oaBusy = false; }
  }
  async function confirmDeleteOpenAI() {
    const slug = deleteOpenAITarget; if (!slug) return; deleteOpenAITarget = null; busySlug = slug;
    try { await deleteOpenAIProvider($apiKey, slug); showToast(`Đã xóa provider ${slug}`); await refreshAfterOpenAIChange(); } catch (e) { fail(e); } finally { busySlug = null; }
  }

  function isBrowserRec(rec: RecipeInfo): boolean {
    // FlowRunner kế thừa BrowserRecipe — flows ghi đè recipes cùng slug nên
    // provider trong /admin/recipes có thể là FlowRunner.
    return rec.type === "BrowserRecipe" || rec.type === "FlowRunner";
  }

  function healthOf(rec: RecipeInfo, profileCount: number): { label: string; variant: BadgeVariant } {
    if (rec.unhealthy) return { label: "Lỗi sức khỏe", variant: "destructive" };
    if (isBrowserRec(rec) && profileCount === 0 && rec.trial) {
      return { label: `Dùng thử: ${rec.trial.used}/${rec.trial.limit}`, variant: "warning" };
    }
    return { label: "Sẵn sàng", variant: "success" };
  }

  $effect(() => {
    if (!highlightSlug) return;
    expanded = { ...expanded, [highlightSlug]: true };
    const el = document.getElementById(`recipe-row-${highlightSlug}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    const timer = setTimeout(() => onHighlighted?.(), 2500);
    return () => clearTimeout(timer);
  });
</script>

<!-- Browser Providers Card -->
<Card.Root class="overflow-hidden" aria-labelledby="providers-title">
  <Card.Header class="flex-row items-center justify-between gap-4 border-b"><div class="flex items-start gap-3"><div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Browser size={19} /></div><div><Card.Title id="providers-title">Providers</Card.Title><Card.Description>Browser flows & OpenAI-compatible. Quản lý model, domain và đăng nhập — sửa flow trong trang Flows.</Card.Description></div></div><Button variant="outline" size="sm" disabled={refreshing} onclick={refresh}><Repeat class={refreshing ? "animate-spin" : ""} /> {refreshing ? "Đang tải" : "Làm mới"}</Button></Card.Header>
  <Card.Content class="p-0">
    {#if panelError}<div class="m-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{panelError}</div>{/if}
    <!-- Browser section -->
    <div class="border-b bg-muted/20 px-4 py-2 text-xs font-medium text-muted-foreground flex items-center gap-2"><Browser size={14}/> Browser Providers — { $recipes.length } provider</div>
    {#if $recipesLoading && !$recipes.length}<div class="flex min-h-24 flex-col items-center justify-center gap-2 p-6 text-muted-foreground" role="status"><CircleNotch class="animate-spin" size={20} /><p class="text-sm">Đang tải providers…</p></div>
    {:else if !$recipes.length}<div class="flex min-h-24 flex-col items-center justify-center p-6 text-center"><Browser class="mb-2 text-muted-foreground" size={24} /><p class="text-sm font-medium">Chưa có Browser provider</p><p class="mt-1 text-xs text-muted-foreground">Khởi động server để auto-convert từ recipes hiện có thành flows.</p></div>{/if}
    <div class="divide-y">
      {#each $recipes as rec (rec.slug)}
        {@const isBrowser = isBrowserRec(rec)}{@const serving = profilesServing(rec.domain)}{@const health = healthOf(rec, serving.length)}
        <article id={`recipe-row-${rec.slug}`} class={highlightSlug === rec.slug ? "ring-2 ring-inset ring-primary/60 transition-shadow" : ""}>
          <button class="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[auto_minmax(10rem,1fr)_minmax(8rem,1fr)_auto_auto]" onclick={() => toggle(rec.slug)} aria-expanded={expanded[rec.slug] ?? false}>
            {#if expanded[rec.slug]}<CaretDown />{:else}<CaretRight />{/if}<span class="min-w-0"><strong class="block truncate font-data text-sm">{rec.slug}</strong><span class="block truncate font-data text-xs text-muted-foreground sm:hidden">{rec.domain ?? "—"}</span></span><span class="hidden truncate font-data text-xs text-muted-foreground sm:block">{rec.domain ?? "—"}</span><Badge variant={health.variant}>{health.label}</Badge><span class="hidden text-xs text-muted-foreground sm:inline">{isBrowser ? `${serving.length} profile` : `${rec.models.length} model`}</span>
          </button>
          {#if expanded[rec.slug]}
            <div class="grid gap-4 border-t bg-muted/15 p-4 sm:p-5">
              <dl class="grid gap-2 text-sm sm:grid-cols-[6rem_minmax(0,1fr)]"><dt class="text-muted-foreground">Models</dt><dd class="break-words font-data text-xs">{rec.models.join(", ") || "—"}</dd>{#if rec.url}<dt class="text-muted-foreground">URL</dt><dd class="break-all font-data text-xs">{rec.url}</dd>{/if}</dl>
              <div class="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onReload(rec.slug)}><Repeat class={busySlug === rec.slug ? "animate-spin" : ""} /> Reload</Button><Button variant="default" size="sm" onclick={() => goto(`/flows/${encodeURIComponent(rec.slug)}`)}><PencilSimple /> Mở Flow</Button>{#if isBrowser}<Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onCloseBrowser(rec.slug)}><X /> Đóng browser</Button>{/if}</div>
              <p class="text-[11px] text-muted-foreground">Sửa selector, copy flow, chạy thử — làm trong Flows. Recipe YAML cũ đã ẩn.</p>
              {#if isBrowser}
                <div class="border-t pt-4">
                  <div class="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <h4 class="text-sm font-medium">Chạy trên</h4>
                      <p class="font-data text-xs text-muted-foreground">{rec.domain}</p>
                    </div>
                    <Button variant="outline" size="sm" onclick={() => onManageProfiles?.()}><Stack /> Quản lý ở Profiles</Button>
                  </div>
                  {#if serving.length}
                    <ul class="grid gap-1.5">
                      {#each serving as item (item.profile.id)}
                        <li class="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm">
                          <span class={`size-2 shrink-0 rounded-full ${item.profile.open ? "bg-success" : "bg-muted-foreground"}`}></span>
                          <strong class="font-data">{item.profile.name}</strong>
                          {#each item.accounts as account (account.id)}<Badge variant="outline" class="font-data">{account.label}</Badge>{/each}
                          <span class="ml-auto text-xs text-muted-foreground">{item.profile.open ? `đang chạy · ${item.profile.tabs} tab` : "rảnh"}</span>
                        </li>
                      {/each}
                    </ul>
                    <p class="mt-2 text-xs text-muted-foreground">Request được chia cho {serving.length} profile — càng nhiều profile thì càng nhiều request song song.</p>
                  {:else}
                    <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Chưa profile nào đăng nhập {rec.domain} — provider đang chạy ẩn danh.</div>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        </article>
      {/each}
    </div>
    <!-- OpenAI section -->
    <div class="border-y bg-muted/20 px-4 py-2 text-xs font-medium text-muted-foreground flex items-center justify-between">
      <span class="flex items-center gap-2"><Globe size={14}/> OpenAI Providers — { $openaiProviders.length } provider</span>
      <Button size="sm" variant="outline" onclick={openOpenAICreate}><Plus size={14}/> Thêm OpenAI</Button>
    </div>
    {#if $openaiProvidersLoading && !$openaiProviders.length}<div class="flex min-h-24 items-center justify-center gap-2 p-6 text-muted-foreground"><CircleNotch class="animate-spin" size={18}/><span class="text-sm">Đang tải…</span></div>
    {:else if !$openaiProviders.length}<div class="flex flex-col items-center justify-center gap-2 p-6 text-center"><Globe size={22} class="text-muted-foreground"/><p class="text-sm font-medium">Chưa có OpenAI provider</p><p class="text-xs text-muted-foreground">Thêm endpoint OpenAI-compatible (OpenAI, Azure, local LLM, …) để dùng qua cùng API.</p><Button size="sm" class="mt-2" onclick={openOpenAICreate}><Plus/> Thêm provider đầu tiên</Button></div>
    {:else}
      <div class="divide-y">
        {#each $openaiProviders as p (p.slug)}
          <article class="grid gap-3 px-4 py-3">
            <div class="flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-2"><strong class="font-data text-sm">{p.slug}</strong><Badge variant={p.ready ? "success" : "warning"}>{p.ready ? "Sẵn sàng" : "Thiếu key"}</Badge><Badge variant="secondary" class="font-data text-[11px]">OpenAI</Badge><Badge variant={p.stream ? "outline" : "secondary"}>{p.stream ? "stream" : "non-stream"}</Badge></div>
                <p class="mt-1 break-all font-data text-xs text-muted-foreground">{p.base_url}</p>
                <p class="mt-1 font-data text-xs">Models: {p.models.map(m=>m.id).join(", ")}</p>
              </div>
              <div class="flex gap-1.5 shrink-0">
                <Button size="sm" variant="outline" onclick={()=>openOpenAIEdit(p)}><PencilSimple/> Sửa</Button>
                <Button size="sm" variant="destructive" disabled={busySlug===p.slug} onclick={()=>deleteOpenAITarget=p.slug}><Trash/> Xóa</Button>
              </div>
            </div>
            {#if p.has_key}<p class="text-[11px] text-muted-foreground">Has API key {#if p.api_key_env}<span class="font-data">({p.api_key_env})</span>{/if}</p>{/if}
          </article>
        {/each}
      </div>
    {/if}
  </Card.Content>
 </Card.Root>

<AlertDialog.Root open={deleteOpenAITarget !== null} onOpenChange={(open) => { if (!open) deleteOpenAITarget = null; }}><AlertDialog.Content><AlertDialog.Header><AlertDialog.Title>Xóa OpenAI provider {deleteOpenAITarget}?</AlertDialog.Title><AlertDialog.Description>File yaml sẽ bị xóa và provider không còn khả dụng.</AlertDialog.Description></AlertDialog.Header><AlertDialog.Footer><AlertDialog.Cancel>Hủy</AlertDialog.Cancel><AlertDialog.Action variant="destructive" onclick={confirmDeleteOpenAI}>Xóa</AlertDialog.Action></AlertDialog.Footer></AlertDialog.Content></AlertDialog.Root>

<!-- OpenAI dialog -->
<Dialog.Root bind:open={showOpenAIDialog}>
  <Dialog.Content class="max-h-[85vh] overflow-y-auto sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2"><Globe size={18}/> {editingOpenAI ? `Sửa ${editingOpenAI.slug}` : "Thêm OpenAI Provider"}</Dialog.Title>
      <Dialog.Description>
        OpenAI-compatible endpoint. Model id sẽ thành <span class="font-mono">{"{slug}/{model}"}</span>.
      </Dialog.Description>
    </Dialog.Header>
    <div class="grid gap-4 py-2">
      {#if oaError}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-sm text-destructive">{oaError}</div>{/if}
      <div class="grid gap-1.5">
        <Label>Slug *</Label>
        <Input class="font-data" placeholder="my-openai" bind:value={oaSlug} disabled={!!editingOpenAI} />
        {#if editingOpenAI}<p class="text-[11px] text-muted-foreground">Không đổi slug khi sửa — xóa và tạo lại nếu cần.</p>{/if}
      </div>
      <div class="grid gap-1.5">
        <Label>Base URL *</Label>
        <Input class="font-data" placeholder="https://api.openai.com/v1" bind:value={oaBaseUrl} />
      </div>
      <div class="grid gap-1.5">
        <Label>API Key</Label>
        <Input type="password" placeholder={editingOpenAI ? "Để trống = giữ nguyên" : "sk-..."} bind:value={oaApiKey} />
        <p class="text-[11px] text-muted-foreground">Hoặc dùng biến môi trường bên dưới.</p>
      </div>
      <div class="grid gap-1.5">
        <Label>API Key Env (tùy chọn)</Label>
        <Input class="font-data" placeholder="OPENAI_API_KEY" bind:value={oaApiKeyEnv} />
      </div>
      <label class="flex items-center justify-between rounded-lg border bg-muted/30 px-3 py-2.5 text-sm">
        <span class="font-medium">Stream</span>
        <Switch bind:checked={oaStream} />
      </label>
      <div class="grid gap-2">
        <div class="flex items-center justify-between">
          <Label>Models *</Label>
          <Button variant="outline" size="sm" onclick={addOAModel}><Plus size={14}/> Thêm</Button>
        </div>
        {#each oaModels as m, idx}
          <div class="flex gap-2 items-center">
            <Input class="flex-1 font-data" placeholder="gpt-4o-mini" bind:value={m.id} />
            <Select.Root type="single" bind:value={m.capability}>
              <Select.Trigger class="w-28">{m.capability}</Select.Trigger>
              <Select.Content>
                <Select.Item value="chat" label="chat">chat</Select.Item>
                <Select.Item value="image" label="image">image</Select.Item>
                <Select.Item value="both" label="both">both</Select.Item>
              </Select.Content>
            </Select.Root>
            <Button variant="ghost" size="icon" class="size-7" disabled={oaModels.length<=1} onclick={()=>removeOAModel(idx)}><Trash size={14}/></Button>
          </div>
        {/each}
      </div>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={()=>showOpenAIDialog=false}>Hủy</Button>
      <Button onclick={submitOpenAI} disabled={oaBusy}>{#if oaBusy}<CircleNotch class="animate-spin"/>{:else}<Check/>{/if} {editingOpenAI ? "Lưu" : "Tạo"}</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
