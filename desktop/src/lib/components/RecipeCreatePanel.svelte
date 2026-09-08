<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import {
    FLOW_KINDS,
    analyzeRecipeDraft,
    createRecipe,
    flowLabel,
    flowNameOk,
    testRecipe,
    type FlowKind,
    type TrialResult,
  } from "../api";
  import { RecipeForm } from "../recipeForm.svelte";
  import { refreshAfterRecipeChange } from "../sync";
  import { profiles } from "../sync";
  import RecipeFields from "./RecipeFields.svelte";
  import RecordSessionPanel from "./RecordSessionPanel.svelte";
  import TrialReport from "./TrialReport.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Card from "$lib/components/ui/card";
  import * as Select from "$lib/components/ui/select";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import { CaretDown, Check, CircleNotch, Copy, Plus, Record as RecordIcon, Sliders, Sparkle, Stack, WarningCircle, Wrench } from "phosphor-svelte";

  interface Props {
    onSuccess?: (slug: string) => void;
    onManageProfiles?: () => void;
  }
  let { onSuccess, onManageProfiles }: Props = $props();

  const form = new RecipeForm();
  let slug = $state("");
  let advancedOpen = $state(false);

  const ANON_RCP = "__anon__";
  let selectedProfileId = $state(ANON_RCP);
  const selectedProfileName = $derived(
    selectedProfileId === ANON_RCP ? "" : ($profiles.find((p) => String(p.id) === selectedProfileId)?.name ?? "")
  );

  let headedAnalyze = $state(false);
  // rcp-profile: sentinel __anon__ thay cho "" để bits-ui không nhầm "rỗng" (hasValue).
  // Giữ đúng lựa chọn khi danh sách profiles đổi; nếu profile đã chọn bị xóa thì về ẩn danh.
  $effect(() => {
    if (selectedProfileId === ANON_RCP) return;
    if ($profiles.length && !$profiles.some((p) => String(p.id) === selectedProfileId)) {
      selectedProfileId = ANON_RCP;
    }
  });
  let headedTest = $state(false);
  let analyzing = $state(false);
  let creating = $state(false);
  let testing = $state(false);
  /** Flow đem ra chạy thử. `select_model` chỉ chạy tới bước chọn model rồi
   * dừng — hữu ích khi đang dò đúng chuỗi bấm mở dropdown. */
  let testFlow = $state<FlowKind>("text");
  let testResult = $state<TrialResult | null>(null);
  let analyzeError = $state("");
  let analyzeLog = $state<string[]>([]);
  let logOpen = $state(false);
  let copyStatus = $state("");

  function cleanSlug(): string | null {
    const next = slug.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(next)) {
      form.error = "Slug chỉ gồm chữ thường, số và dấu -";
      return null;
    }
    return next;
  }

  function buildSpec() {
    form.error = "";
    const next = cleanSlug();
    if (!next || !form.validate()) return null;
    return form.toSpec(next);
  }

  function resetForm() {
    form.reset();
    slug = "";
    testResult = null;
  }

  async function onAnalyze() {
    const url = form.url.trim();
    if (!url) { showToast("Nhập URL trang chat trước khi phân tích."); return; }
    try { new URL(url); } catch { showToast("URL không hợp lệ."); return; }
    analyzing = true;
    analyzeError = "";
    analyzeLog = [];
    testResult = null;
    try {
      const data = await analyzeRecipeDraft($apiKey, url, {
        headed: headedAnalyze,
        profileId: selectedProfileId !== ANON_RCP ? Number(selectedProfileId) : null,
      });
      analyzeLog = (data.log ?? []) as string[];
      if (data.status === "login_required") {
        analyzeError = (data.hint as string) || "Site yêu cầu đăng nhập. Hãy mở profile và đăng nhập trước.";
        showToast(analyzeError);
        return;
      }
      const recipe = data.recipe as Record<string, unknown> | undefined;
      if (!recipe) {
        analyzeError = (data.hint as string) || "AI không trả về recipe.";
        showToast(analyzeError);
        return;
      }
      form.load(recipe);
      // keep URL in sync if AI returned different url casing
      if (!slug.trim()) {
        const s = (data.slug as string) || (recipe.slug as string) || "";
        if (s) slug = String(s).toLowerCase().replace(/[^a-z0-9-]/g, "-").replace(/^-|-$/g, "") || slug;
      }
      showToast(data.notes ? `AI đã điền form — ${data.notes}` : "AI đã điền form. Kiểm tra lại trước khi tạo.");
      if (analyzeLog.length) logOpen = true;
    } catch (e) {
      analyzeError = (e as Error).message;
      showToast(analyzeError);
    } finally {
      analyzing = false;
    }
  }

  async function onTest() {
    const spec = buildSpec();
    if (!spec) { showToast(form.error); return; }
    testing = true; testResult = null;
    try { testResult = await testRecipe($apiKey, spec, { headed: headedTest, flow: testFlow }); }
    catch (e) { testResult = { ok: false, reply: "", flow: testFlow, error: (e as Error).message }; }
    finally { testing = false; }
  }

  async function onCreate() {
    const spec = buildSpec();
    if (!spec) { showToast(form.error); return; }
    creating = true;
    try {
      await createRecipe($apiKey, spec);
      showToast(`Đã tạo recipe ${spec.slug}`);
      await refreshAfterRecipeChange();
      onSuccess?.(spec.slug);
      resetForm();
    } catch (e) { form.error = (e as Error).message; showToast(form.error); }
    finally { creating = false; }
  }

  async function copyLog() {
    try { await navigator.clipboard.writeText(analyzeLog.join("\n")); copyStatus = "Đã sao chép log."; }
    catch { copyStatus = "Không thể truy cập clipboard."; }
    setTimeout(() => copyStatus = "", 1500);
  }
</script>

<Card.Root class="flex min-h-full flex-1 flex-col overflow-visible" aria-labelledby="recipe-create-title">
  <Card.Header class="shrink-0 border-b">
    <div class="flex items-start gap-3">
      <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Wrench size={19} aria-hidden="true" /></div>
      <div class="min-w-0 flex-1">
        <Card.Title id="recipe-create-title" class="text-base">Tạo recipe — điền tay hoặc AI tự điền</Card.Title>
        <Card.Description class="mt-1 max-w-3xl">Điền URL và toàn bộ selector thủ công <span class="font-medium text-foreground">hoặc</span> nhập URL rồi bấm <span class="font-medium text-foreground">Phân tích bằng AI</span> để hệ thống tự dò DOM và điền sẵn vào form — bạn chỉ cần kiểm tra lại và bấm Tạo.</Card.Description>
      </div>
    </div>
  </Card.Header>

  <Card.Content class="grid gap-5 p-4 sm:p-6">
    <!-- Row profile + headed for AI analyze -->
    {#if $profiles.length}
      <div class="flex flex-wrap items-end gap-3 rounded-xl border bg-muted/20 p-3">
        <div class="grid min-w-52 gap-1.5">
          <label for="rcp-profile" class="text-xs font-medium text-muted-foreground">Profile cho AI (tùy chọn)</label>
          <Select.Root type="single" bind:value={selectedProfileId}>
            <Select.Trigger id="rcp-profile" class="h-9 w-full sm:w-64">
              {selectedProfileName || "Không dùng — ẩn danh"}
            </Select.Trigger>
            <Select.Content>
              <Select.Item value={ANON_RCP} label="Không dùng — ẩn danh">Không dùng — ẩn danh</Select.Item>
              {#each $profiles as p (p.id)}
                <Select.Item value={String(p.id)} label={p.name}>{p.name}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </div>
        <label class="flex items-center gap-2 pb-2 text-sm"><Switch bind:checked={headedAnalyze} aria-label="Hiện browser khi phân tích" /> Hiện browser khi phân tích</label>
        <p class="w-full text-xs leading-relaxed text-muted-foreground">Nếu site cần đăng nhập mà chưa có account, chọn profile đã đăng nhập để AI thấy đúng DOM sau đăng nhập.</p>
      </div>
    {:else}
      <div class="flex flex-wrap items-center gap-3 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning">
        <WarningCircle class="shrink-0" />
        <p class="min-w-0 flex-1">Chưa có profile nào. Bạn vẫn tạo recipe ẩn danh được; nếu site cần đăng nhập, hãy tạo profile trước để AI dùng phiên đăng nhập đó.</p>
        <Button variant="outline" size="sm" onclick={() => onManageProfiles?.()}><Stack /> Tạo profile</Button>
      </div>
    {/if}

    <!-- AI auto-fill bar -->
    <div class="flex flex-col gap-3 rounded-xl border border-primary/15 bg-primary/5 p-3 sm:flex-row sm:items-center sm:justify-between">
      <div class="min-w-0">
        <div class="flex items-center gap-2 text-sm font-semibold"><Sparkle size={16} class="text-primary" aria-hidden="true" /> Phân tích bằng AI</div>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">Nhập URL ở mục <span class="font-medium text-foreground">Trang đích</span> bên dưới rồi bấm phân tích — AI sẽ điền toàn bộ selector, done_signal, new_chat, timing và models.</p>
      </div>
      <Button class="shrink-0" disabled={analyzing || !form.url.trim()} onclick={onAnalyze}>
        {#if analyzing}<CircleNotch class="animate-spin" /> Đang phân tích{:else}<Sparkle /> Phân tích bằng AI{/if}
      </Button>
    </div>

    <!-- Ghi thao tác thật: AI sao chép selector bị tác động -->
    <div class="grid gap-3 rounded-xl border border-primary/15 bg-primary/5 p-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2 text-sm font-semibold"><RecordIcon size={16} class="text-primary" aria-hidden="true" /> Ghi thao tác thật</div>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">
          Khi AI đoán sai DOM: nhập URL ở <span class="font-medium text-foreground">Trang đích</span>, chọn profile bên trên rồi bấm ghi — một cửa sổ Chromium mở ra, bạn gõ prompt / gửi / bấm Copy như dùng thật. AI sao chép đúng các selector bị tác động để sinh recipe và tự chạy thử.
          {#if selectedProfileId === ANON_RCP}<span class="font-medium text-warning"> Cần chọn profile trước.</span>{/if}
        </p>
      </div>
      <RecordSessionPanel
        url={form.url}
        profileId={selectedProfileId !== ANON_RCP ? Number(selectedProfileId) : null}
        disabled={!form.url.trim() || selectedProfileId === ANON_RCP || analyzing}
        onSuccess={(s) => { if (s) onSuccess?.(s); }}
      />
    </div>

    {#if form.error}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{form.error}</div>{/if}
    {#if analyzeError}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{analyzeError}</div>{/if}

    {#if analyzeLog.length}
      <Collapsible.Root bind:open={logOpen} class="overflow-hidden rounded-lg border">
        <div class="flex items-center justify-between gap-2 border-b bg-muted/30 px-3 py-1.5">
          <Collapsible.Trigger class="flex items-center gap-1.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground">
            <CaretDown class={`transition-transform ${logOpen ? "" : "-rotate-90"}`} size={13} aria-hidden="true" /> Log phân tích ({analyzeLog.length})
          </Collapsible.Trigger>
          <Button variant="ghost" size="sm" onclick={copyLog}><Copy /> Sao chép</Button>
        </div>
        <Collapsible.Content>
          <pre class="m-0 whitespace-pre-wrap break-words bg-[#0a0d0a] p-3 font-data text-[11px] leading-5 text-[#8be8a8]">{analyzeLog.join("\n")}</pre>
        </Collapsible.Content>
      </Collapsible.Root>
    {/if}

    <!-- Slug -->
    <div class="grid gap-3 rounded-xl border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,.7fr)] sm:items-end">
      <div>
        <h2 class="text-sm font-semibold">Định danh recipe</h2>
        <p class="mt-1 text-xs leading-relaxed text-muted-foreground">Slug thành <span class="font-data">recipes/&lt;slug&gt;/recipe.yaml</span> và không đổi sau khi tạo.</p>
      </div>
      <label for="rcp-slug" class="grid gap-1.5 text-sm font-medium">Slug <span class="text-destructive">*</span><Input id="rcp-slug" class="font-data" placeholder="my-chat-site" bind:value={slug} /></label>
    </div>

    <!-- Detailed form -->
    <RecipeFields {form} idPrefix="rcp" bind:advancedOpen />

    {#if testResult}<TrialReport result={testResult} />{/if}
  </Card.Content>

  <Card.Footer class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t bg-muted/10 p-4 sm:px-6">
    <div class="flex flex-wrap items-center gap-3">
      <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headedTest} aria-label="Hiện browser khi kiểm tra" /> Hiện browser khi kiểm tra</label>
      <label class="flex items-center gap-2 text-sm">
        Flow
        <!-- Ô nhập chứ không phải select: recipe đặt được flow tên riêng, danh
             sách gợi ý chỉ liệt kê các flow có sẵn. -->
        <input
          bind:value={testFlow}
          list="rc-flow-kinds"
          aria-label="Flow đem ra chạy thử"
          aria-invalid={testFlow !== "" && !flowNameOk(testFlow)}
          spellcheck={false}
          class="h-8 w-44 rounded-md border border-input bg-background px-2 font-data text-sm aria-[invalid=true]:border-destructive"
        />
        <datalist id="rc-flow-kinds">
          {#each FLOW_KINDS as kind (kind)}<option value={kind}>{flowLabel(kind)}</option>{/each}
        </datalist>
      </label>
    </div>
    <div class="flex flex-wrap gap-2">
      <Button type="button" variant="ghost" size="sm" disabled={testing || creating || analyzing} onclick={() => { resetForm(); form.error=""; testResult=null; analyzeError=""; analyzeLog=[]; }}><Sliders /> Đặt lại</Button>
      <Button type="button" variant="outline" size="sm" disabled={testing || creating || analyzing} onclick={onTest}>{#if testing}<CircleNotch class="animate-spin" /> Đang kiểm tra{:else}<Check /> Kiểm tra kết nối{/if}</Button>
      <Button type="button" size="sm" disabled={creating || testing || analyzing} onclick={onCreate}>{#if creating}<CircleNotch class="animate-spin" /> Đang tạo{:else}<Plus /> Tạo recipe{/if}</Button>
    </div>
  </Card.Footer>
</Card.Root>
<div class="sr-only" role="status" aria-live="polite">{copyStatus}</div>
