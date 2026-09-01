<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { profiles, recipes, recipesLoading, openaiProviders, openaiProvidersLoading, refreshAfterRecipeChange, refreshAfterRecipeDelete, refreshProfiles, refreshRecipes, refreshOpenAIProviders, refreshAfterOpenAIChange } from "../sync";
  import { closeRecipeBrowser, deleteRecipe, fetchJob, jobAction, reanalyzeRecipe, reloadRecipe, renameRecipe, type RecipeInfo, createOpenAIProvider, updateOpenAIProvider, deleteOpenAIProvider, type OpenAIProviderInfo } from "../api";
  import RecipeEditorSheet from "./RecipeEditorSheet.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Badge, type BadgeVariant } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { Switch } from "$lib/components/ui/switch";
  import { Textarea } from "$lib/components/ui/textarea";
  import JobStepTracker from "./JobStepTracker.svelte";
  import RecordSessionPanel from "./RecordSessionPanel.svelte";
  import { Browser, CaretDown, CaretRight, Check, CircleNotch, Copy, PencilSimple, Plus, Record as RecordIcon, Repeat, Sliders, Sparkle, Stack, Trash, WarningCircle, X, Globe, Plugs } from "phosphor-svelte";
  import { get } from "svelte/store";

  interface Props {
    highlightSlug?: string | null;
    onHighlighted?: () => void;
    onManageProfiles?: () => void;
  }
  let { highlightSlug = null, onHighlighted, onManageProfiles }: Props = $props();

  let expanded = $state<Record<string, boolean>>({});
  let busySlug = $state<string | null>(null);
  let deleteRecipeTarget = $state<string | null>(null);
  let panelError = $state("");
  let refreshing = $state(false);
  let renamingSlug = $state<string | null>(null);
  let renameValue = $state("");
  let renameBusy = $state(false);
  let editingSlug = $state<string | null>(null);

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

  // ---- Phân tích lại bằng AI ----
  let reanalyzeSlug = $state<string | null>(null);
  let reanalyzeProfileId = $state<string>("");
  let reanalyzeHeaded = $state(false);
  let reanalyzeBusy = $state(false);
  let reanalyzeJobId = $state<string | null>(null);
  let reanalyzeStatus = $state<string>("idle");
  let reanalyzeLog = $state("");
  let reanalyzeLoginVisible = $state(false);
  let reanalyzeLoginBusy = $state(false);
  let reanalyzeStatusKind = $state<"idle" | "busy" | "error" | "success">("idle");
  let reanalyzeJobStatusText = $state("");
  let reanalyzeLogEl = $state<HTMLElement | null>(null);
  let reanalyzePollTimer: ReturnType<typeof setTimeout> | null = null;
  let reanalyzePollAbort: AbortController | null = null;
  let reanalyzePollGen = 0;
  const reanalyzeTerminal = ["ok", "failed", "cancelled", "login_timeout"];
  function reanalyzeReset() {
    reanalyzeJobId = null; reanalyzeStatus = "idle"; reanalyzeLog = "";
    reanalyzeLoginVisible = false; reanalyzeStatusKind = "idle"; reanalyzeJobStatusText = "";
    reanalyzeBusy = false; reanalyzeLoginBusy = false;
    if (reanalyzePollTimer) clearTimeout(reanalyzePollTimer);
    if (reanalyzePollAbort) reanalyzePollAbort.abort();
    reanalyzePollTimer = null; reanalyzePollAbort = null; reanalyzePollGen++;
  }
  function reanalyzeShowStatus(j: { status: string; can_complete_login?: boolean }) {
    const canLogin = j.status === "waiting_login" && j.can_complete_login === true;
    reanalyzeLoginVisible = canLogin;
    reanalyzeStatusKind = j.status === "ok" ? "success" : ["failed", "cancelled", "login_timeout"].includes(j.status) ? "error" : "busy";
    reanalyzeStatus = j.status;
    if (canLogin) reanalyzeJobStatusText = "Chrome đã mở. Hãy đăng nhập rồi xác nhận.";
    else if (j.status === "waiting_login") reanalyzeJobStatusText = "Đang đóng phiên đăng nhập hết hạn…";
    else if (j.status === "resuming") reanalyzeJobStatusText = "Đang lưu session và tiếp tục…";
    else reanalyzeJobStatusText = "Trạng thái: " + j.status;
  }
  function reanalyzeStartPolling(jobId: string) {
    reanalyzeJobId = jobId;
    const gen = ++reanalyzePollGen;
    let ticks = 0;
    const poll = async () => {
      if (gen !== reanalyzePollGen || jobId !== reanalyzeJobId) return;
      if (++ticks > 660) {
        reanalyzeLoginVisible = false; reanalyzeJobStatusText = "Timeout: job quá lâu"; reanalyzeStatusKind = "error"; reanalyzeStatus = "failed";
        return;
      }
      const ctrl = new AbortController(); reanalyzePollAbort = ctrl;
      let terminal = false;
      try {
        if (gen !== reanalyzePollGen || jobId !== reanalyzeJobId) return;
        const j = await fetchJob($apiKey, jobId, ctrl.signal);
        if (gen !== reanalyzePollGen || jobId !== reanalyzeJobId) return;
        reanalyzeLog = (j.log || []).join("\n");
        if (reanalyzeLogEl) requestAnimationFrame(() => { if (reanalyzeLogEl) reanalyzeLogEl.scrollTop = reanalyzeLogEl.scrollHeight; });
        reanalyzeShowStatus(j);
        terminal = reanalyzeTerminal.includes(j.status);
        if (terminal) {
          if (reanalyzePollTimer) clearTimeout(reanalyzePollTimer);
          reanalyzePollTimer = null;
          if (j.status === "ok") { showToast(`Đã phân tích lại ${reanalyzeSlug} thành công`); await refreshAfterRecipeChange(); }
        }
      } catch (e: any) {
        if (gen === reanalyzePollGen && jobId === reanalyzeJobId && e?.name !== "AbortError") {
          reanalyzeJobStatusText = "Poll lỗi: " + e; reanalyzeStatusKind = "error"; reanalyzeStatus = "failed";
        }
      } finally {
        if (reanalyzePollAbort === ctrl) reanalyzePollAbort = null;
        if (!terminal && gen === reanalyzePollGen && jobId === reanalyzeJobId) reanalyzePollTimer = setTimeout(poll, 1000);
      }
    };
    reanalyzePollTimer = setTimeout(poll, 1000);
  }
  async function reanalyzePostAction(action: "login-complete" | "cancel") {
    if (!reanalyzeJobId) return;
    const jobId = reanalyzeJobId; const gen = reanalyzePollGen;
    reanalyzeLoginBusy = true;
    try {
      const data = await jobAction($apiKey, jobId, action);
      if (gen !== reanalyzePollGen || jobId !== reanalyzeJobId) return;
      if (action === "login-complete") { reanalyzeStartPolling(jobId); reanalyzeShowStatus({ status: "resuming" }); }
      else { reanalyzeShowStatus(data); if (reanalyzeTerminal.includes(data.status)) { if (reanalyzePollTimer) clearTimeout(reanalyzePollTimer); reanalyzePollTimer = null; } }
    } catch (e) { if (gen === reanalyzePollGen && jobId === reanalyzeJobId) { reanalyzeJobStatusText = "Lỗi: " + e; reanalyzeStatusKind = "error"; } }
    finally { if (gen === reanalyzePollGen && jobId === reanalyzeJobId) reanalyzeLoginBusy = false; }
  }
  async function confirmReanalyze() {
    if (!reanalyzeSlug) return;
    reanalyzeBusy = true; reanalyzeLog = ""; reanalyzeStatus = "running"; reanalyzeStatusKind = "busy"; reanalyzeJobStatusText = "Đang khởi tạo analyzer…";
    reanalyzeLoginVisible = false;
    try {
      const profileId = reanalyzeProfileId ? Number(reanalyzeProfileId) : undefined;
      const data = await reanalyzeRecipe($apiKey, reanalyzeSlug, { headed: reanalyzeHeaded, profile_id: profileId ?? null });
      reanalyzeJobStatusText = "Đang chạy job " + data.job_id + "…";
      reanalyzeStartPolling(data.job_id);
    } catch (e) { reanalyzeJobStatusText = "Lỗi: " + e; reanalyzeStatusKind = "error"; reanalyzeStatus = "failed"; }
    finally { reanalyzeBusy = false; }
  }
  let reanalyzeHasChosen = $state(false);
  // Giữ lựa chọn cũ nếu vẫn hợp lệ; chỉ lần đầu mới mặc định về profile đầu tiên.
  // Sau khi người dùng đã chọn (kể cả "Không gắn profile"), các lần sau giữ nguyên.
  function openReanalyze(slug: string, _url?: string) {
    reanalyzeReset();
    reanalyzeSlug = slug;
    if (!reanalyzeHasChosen) {
      reanalyzeProfileId = $profiles[0] ? String($profiles[0].id) : "";
      reanalyzeHasChosen = true;
    } else {
      const stillValid = reanalyzeProfileId && $profiles.some((p) => String(p.id) === reanalyzeProfileId);
      if (!stillValid && reanalyzeProfileId !== "") {
        reanalyzeProfileId = $profiles[0] ? String($profiles[0].id) : "";
      }
      // keepEmpty (== "") thì giữ nguyên lựa chọn ẩn danh của người dùng
    }
    reanalyzeHeaded = false;
  }

  // Nếu profile đã chọn bị xóa ở tab Profiles, quay về ẩn danh thay vì giữ id rác.
  $effect(() => {
    if (!reanalyzeProfileId) return;
    if ($profiles.length && !$profiles.some((p) => String(p.id) === reanalyzeProfileId)) {
      reanalyzeProfileId = "";
    }
  });
  // ---- Ghi thao tác thật (record → AI sao chép selector) ----
  let recordSlug = $state<string | null>(null);
  let recordUrl = $state("");
  let recordProfileId = $state<string>("");
  const recordProfileName = $derived($profiles.find((p) => String(p.id) === recordProfileId)?.name ?? "");
  function openRecord(slug: string, url: string) {
    recordSlug = slug;
    recordUrl = url;
    const stillValid = recordProfileId && $profiles.some((p) => String(p.id) === recordProfileId);
    if (!stillValid) recordProfileId = $profiles[0] ? String($profiles[0].id) : "";
  }

  async function copyReanalyzeLog() {
    try { await navigator.clipboard.writeText(reanalyzeLog); showToast("Đã sao chép log"); }
    catch { showToast("Không thể truy cập clipboard"); }
  }

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
  async function confirmDeleteRecipe() {
    const slug = deleteRecipeTarget; if (!slug) return; deleteRecipeTarget = null; busySlug = slug; panelError = "";
    try { await deleteRecipe($apiKey, slug); showToast(`Đã xóa provider ${slug}`); await refreshAfterRecipeDelete(); } catch (e) { fail(e); } finally { busySlug = null; }
  }
  function startRename(slug: string) { renamingSlug = slug; renameValue = slug; }
  function cancelRename() { renamingSlug = null; renameValue = ""; }
  async function confirmRename() {
    const slug = renamingSlug; if (!slug) return;
    const next = renameValue.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(next)) { showToast("Slug chỉ gồm chữ thường, số và dấu -"); return; }
    if (next === slug) { cancelRename(); return; }
    renameBusy = true; panelError = "";
    try {
      await renameRecipe($apiKey, slug, next);
      showToast(`Đã đổi tên ${slug} thành ${next}`);
      if (expanded[slug]) expanded = { ...expanded, [next]: true };
      cancelRename();
      await refreshRecipes();
    } catch (e) { fail(e); } finally { renameBusy = false; }
  }

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

  function healthOf(rec: RecipeInfo, profileCount: number): { label: string; variant: BadgeVariant } {
    if (rec.unhealthy) return { label: "Lỗi sức khỏe", variant: "destructive" };
    if (rec.type === "BrowserRecipe" && profileCount === 0 && rec.trial) {
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
  <Card.Header class="flex-row items-center justify-between gap-4 border-b"><div class="flex items-start gap-3"><div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Browser size={19} /></div><div><Card.Title id="providers-title">Providers</Card.Title><Card.Description>Browser automation & OpenAI-compatible. Quản lý model, domain và đăng nhập.</Card.Description></div></div><Button variant="outline" size="sm" disabled={refreshing} onclick={refresh}><Repeat class={refreshing ? "animate-spin" : ""} /> {refreshing ? "Đang tải" : "Làm mới"}</Button></Card.Header>
  <Card.Content class="p-0">
    {#if panelError}<div class="m-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{panelError}</div>{/if}
    <!-- Browser section -->
    <div class="border-b bg-muted/20 px-4 py-2 text-xs font-medium text-muted-foreground flex items-center gap-2"><Browser size={14}/> Browser Providers — { $recipes.length } provider</div>
    {#if $recipesLoading && !$recipes.length}<div class="flex min-h-24 flex-col items-center justify-center gap-2 p-6 text-muted-foreground" role="status"><CircleNotch class="animate-spin" size={20} /><p class="text-sm">Đang tải providers…</p></div>
    {:else if !$recipes.length}<div class="flex min-h-24 flex-col items-center justify-center p-6 text-center"><Browser class="mb-2 text-muted-foreground" size={24} /><p class="text-sm font-medium">Chưa có Browser provider</p><p class="mt-1 text-xs text-muted-foreground">Dùng “Thêm integration” để phân tích site bằng AI.</p></div>{/if}
    <div class="divide-y">
      {#each $recipes as rec (rec.slug)}
        {@const isBrowser = rec.type === "BrowserRecipe"}{@const serving = profilesServing(rec.domain)}{@const health = healthOf(rec, serving.length)}
        <article id={`recipe-row-${rec.slug}`} class={highlightSlug === rec.slug ? "ring-2 ring-inset ring-primary/60 transition-shadow" : ""}>
          <button class="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[auto_minmax(10rem,1fr)_minmax(8rem,1fr)_auto_auto]" onclick={() => toggle(rec.slug)} aria-expanded={expanded[rec.slug] ?? false}>
            {#if expanded[rec.slug]}<CaretDown />{:else}<CaretRight />{/if}<span class="min-w-0"><strong class="block truncate font-data text-sm">{rec.slug}</strong><span class="block truncate font-data text-xs text-muted-foreground sm:hidden">{rec.domain ?? "—"}</span></span><span class="hidden truncate font-data text-xs text-muted-foreground sm:block">{rec.domain ?? "—"}</span><Badge variant={health.variant}>{health.label}</Badge><span class="hidden text-xs text-muted-foreground sm:inline">{isBrowser ? `${serving.length} profile` : `${rec.models.length} model`}</span>
          </button>
          {#if expanded[rec.slug]}
            <div class="grid gap-4 border-t bg-muted/15 p-4 sm:p-5">
              <dl class="grid gap-2 text-sm sm:grid-cols-[6rem_minmax(0,1fr)]"><dt class="text-muted-foreground">Models</dt><dd class="break-words font-data text-xs">{rec.models.join(", ") || "—"}</dd>{#if rec.url}<dt class="text-muted-foreground">URL</dt><dd class="break-all font-data text-xs">{rec.url}</dd>{/if}</dl>
              {#if renamingSlug === rec.slug}
                <form class="flex flex-wrap items-center gap-2" onsubmit={(e) => { e.preventDefault(); confirmRename(); }}>
                  <Input class="h-8 w-48 font-data" bind:value={renameValue} disabled={renameBusy} aria-label={`Tên mới cho ${rec.slug}`} />
                  <Button type="submit" size="sm" disabled={renameBusy}>{#if renameBusy}<CircleNotch class="animate-spin" />{:else}<Check />{/if} Lưu</Button>
                  <Button type="button" variant="ghost" size="sm" disabled={renameBusy} onclick={cancelRename}><X /> Hủy</Button>
                </form>
              {:else}
                <div class="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onReload(rec.slug)}><Repeat class={busySlug === rec.slug ? "animate-spin" : ""} /> Reload</Button>{#if isBrowser}<Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => openReanalyze(rec.slug)}><Sparkle /> Phân tích lại</Button><Button variant="outline" size="sm" disabled={busySlug === rec.slug} title="Ghi thao tác thật để sửa selector hỏng" onclick={() => openRecord(rec.slug, rec.url || (rec.domain ? `https://${rec.domain}` : ""))}><RecordIcon /> Ghi thao tác</Button><Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => (editingSlug = rec.slug)}><Sliders /> Chỉnh sửa</Button>{/if}<Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => startRename(rec.slug)}><PencilSimple /> Đổi tên</Button>{#if isBrowser}<Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onCloseBrowser(rec.slug)}><X /> Đóng browser</Button>{/if}<Button variant="destructive" size="sm" disabled={busySlug === rec.slug} onclick={() => (deleteRecipeTarget = rec.slug)}><Trash /> Xóa</Button></div>
              {/if}
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

<RecipeEditorSheet slug={editingSlug} onClose={() => (editingSlug = null)} />

<AlertDialog.Root open={deleteRecipeTarget !== null} onOpenChange={(open) => { if (!open) deleteRecipeTarget = null; }}><AlertDialog.Content><AlertDialog.Header><AlertDialog.Title>Xóa provider {deleteRecipeTarget}?</AlertDialog.Title><AlertDialog.Description>Provider sẽ bị gỡ khỏi router. Các model sẽ không còn khả dụng.</AlertDialog.Description></AlertDialog.Header><AlertDialog.Footer><AlertDialog.Cancel>Hủy</AlertDialog.Cancel><AlertDialog.Action variant="destructive" onclick={confirmDeleteRecipe}>Xóa</AlertDialog.Action></AlertDialog.Footer></AlertDialog.Content></AlertDialog.Root>

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

<!-- Dialog Ghi thao tác thật (ghi đè recipe đang có) -->
<Dialog.Root open={recordSlug !== null} onOpenChange={(open) => { if (!open) recordSlug = null; }}>
  <Dialog.Content class="max-h-[85vh] overflow-y-auto sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2"><RecordIcon size={18} /> Ghi thao tác cho {recordSlug}</Dialog.Title>
      <Dialog.Description>Bạn thao tác thật trên trang; AI sao chép đúng các selector bị tác động để ghi đè recipe.yaml (giữ nguyên slug), rồi tự chạy thử.</Dialog.Description>
    </Dialog.Header>
    <div class="grid gap-4 py-2">
      <div class="grid gap-1.5">
        <label for="record-url" class="text-sm font-medium">URL trang chat</label>
        <Input id="record-url" class="h-9 font-data" bind:value={recordUrl} placeholder="https://chat.example.com" />
      </div>
      <div class="grid gap-1.5">
        <label for="record-profile" class="text-sm font-medium">Profile <span class="text-destructive">*</span></label>
        <Select.Root type="single" bind:value={recordProfileId}>
          <Select.Trigger id="record-profile" class="h-9 w-full">{recordProfileName || "Chọn profile…"}</Select.Trigger>
          <Select.Content>
            {#each $profiles as p (p.id)}<Select.Item value={String(p.id)} label={p.name}>{p.name}</Select.Item>{/each}
          </Select.Content>
        </Select.Root>
        <p class="text-xs text-muted-foreground">Phiên ghi chạy trong profile này — đăng nhập giữa chừng cũng được lưu lại.</p>
      </div>
      {#key recordSlug}
        <RecordSessionPanel
          url={recordUrl}
          profileId={recordProfileId ? Number(recordProfileId) : null}
          slug={recordSlug}
          label="Bắt đầu ghi"
          disabled={!recordUrl.trim() || !recordProfileId}
        />
      {/key}
    </div>
  </Dialog.Content>
</Dialog.Root>

<!-- Dialog Phân tích lại bằng AI -->
<Dialog.Root open={reanalyzeSlug !== null} onOpenChange={(open) => { if (!open) { if (reanalyzePollTimer) clearTimeout(reanalyzePollTimer); if (reanalyzePollAbort) reanalyzePollAbort.abort(); reanalyzeSlug = null; reanalyzeReset(); } }}>
  <Dialog.Content class="max-h-[85vh] overflow-y-auto sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2"><Sparkle size={18} /> Phân tích lại {reanalyzeSlug} bằng AI</Dialog.Title>
      <Dialog.Description>AI sẽ mở site, dò lại DOM và ghi đè recipe.yaml (giữ nguyên slug). Dùng khi site đổi giao diện.</Dialog.Description>
    </Dialog.Header>
    {#if !reanalyzeJobId}
      <div class="grid gap-4 py-2">
        <div class="grid gap-1.5">
          <label for="reanalyze-profile" class="text-sm font-medium">Profile</label>
          <Select.Root type="single" bind:value={reanalyzeProfileId}>
            <Select.Trigger id="reanalyze-profile" class="h-9 w-full">{#if reanalyzeProfileId}{$profiles.find((p) => String(p.id) === reanalyzeProfileId)?.name ?? reanalyzeProfileId}{:else}Không gắn profile (chạy ẩn danh){/if}</Select.Trigger>
            <Select.Content>
              <Select.Item value="" label="Không gắn profile">Không gắn profile</Select.Item>
              {#each $profiles as p (p.id)}<Select.Item value={String(p.id)} label={p.name}>{p.name}</Select.Item>{/each}
            </Select.Content>
          </Select.Root>
          <p class="text-xs text-muted-foreground">Nếu site cần đăng nhập, phiên sẽ lưu vào profile này.</p>
        </div>
        <label class="flex cursor-pointer items-center justify-between gap-4 rounded-lg border bg-muted/30 px-3 py-2.5 text-sm">
          <span><strong class="font-medium">Hiện browser khi phân tích</strong><span class="block text-xs text-muted-foreground">Bỏ headless để quan sát.</span></span>
          <Switch bind:checked={reanalyzeHeaded} aria-label="Hiện browser khi phân tích" />
        </label>
        {#if reanalyzeJobStatusText && reanalyzeStatusKind === "error"}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-sm text-destructive" role="alert">{reanalyzeJobStatusText}</div>{/if}
      </div>
      <Dialog.Footer>
        <Button variant="outline" onclick={() => { reanalyzeSlug = null; reanalyzeReset(); }}>Hủy</Button>
        <Button disabled={reanalyzeBusy} onclick={confirmReanalyze}>{#if reanalyzeBusy}<CircleNotch class="animate-spin" />{:else}<Sparkle />{/if} Bắt đầu phân tích</Button>
      </Dialog.Footer>
    {:else}
      <div class="grid gap-3 py-2">
        <JobStepTracker status={reanalyzeStatus} />
        {#if reanalyzeJobStatusText}
          <div class={`flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${reanalyzeStatusKind === "error" ? "bg-destructive/5 text-destructive border-destructive/20" : reanalyzeStatusKind === "success" ? "bg-success/5 text-success border-success/20" : "bg-warning/5 text-warning border-warning/20"}`} role={reanalyzeStatusKind === "error" ? "alert" : "status"}>
            <span class={`size-2 shrink-0 rounded-full ${reanalyzeStatusKind === "error" ? "bg-destructive" : reanalyzeStatusKind === "success" ? "bg-success" : "bg-warning"}`}></span>{reanalyzeJobStatusText}
          </div>
        {/if}
        {#if reanalyzeLoginVisible}
          <div class="flex flex-wrap gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3">
            <Button disabled={reanalyzeLoginBusy} onclick={() => reanalyzePostAction("login-complete")}><Check /> Đã đăng nhập</Button>
            <Button variant="outline" disabled={reanalyzeLoginBusy} onclick={() => reanalyzePostAction("cancel")}><X /> Hủy job</Button>
          </div>
        {/if}
        <div class="overflow-hidden rounded-lg border">
          <div class="flex items-center justify-between gap-2 border-b bg-muted/10 px-3 py-1.5">
            <span class="text-xs font-medium text-muted-foreground">Log chi tiết</span>
            <Button variant="ghost" size="sm" disabled={!reanalyzeLog} onclick={copyReanalyzeLog}><Copy /> Sao chép</Button>
          </div>
          <pre class="m-0 max-h-64 min-h-32 overflow-auto whitespace-pre-wrap break-words bg-[#0a0d0a] p-3 font-data text-[11px] leading-6 text-[#8be8a8]" bind:this={reanalyzeLogEl}>{reanalyzeLog || "Chưa có log…"}</pre>
        </div>
      </div>
      <Dialog.Footer>
        {#if reanalyzeTerminal.includes(reanalyzeStatus)}
          <Button variant="outline" onclick={() => { reanalyzeSlug = null; reanalyzeReset(); }}>Đóng</Button>
        {:else}
          <Button variant="outline" disabled={reanalyzeLoginBusy} onclick={() => reanalyzePostAction("cancel")}><X /> Hủy job</Button>
        {/if}
      </Dialog.Footer>
    {/if}
  </Dialog.Content>
</Dialog.Root>
