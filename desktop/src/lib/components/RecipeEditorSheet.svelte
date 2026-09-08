<script lang="ts">
  import { untrack } from "svelte";
  import { apiKey, showToast } from "../stores";
  import {
    FLOW_KINDS,
    fetchRecipeSource,
    flowLabel,
    flowNameOk,
    previewRecipeEdit,
    testRecipeEdit,
    updateRecipe,
    type FlowKind,
    type RecipeEdit,
    type TrialResult,
  } from "../api";
  import { RecipeForm } from "../recipeForm.svelte";
  import { refreshAfterRecipeChange } from "../sync";
  import RecipeFields from "./RecipeFields.svelte";
  import TrialReport from "./TrialReport.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Switch } from "$lib/components/ui/switch";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as Sheet from "$lib/components/ui/sheet";
  import * as Tabs from "$lib/components/ui/tabs";
  import { ArrowClockwise, Check, CircleNotch, FloppyDisk, Sliders, WarningCircle } from "phosphor-svelte";

  interface Props {
    /** Slug đang sửa; `null` là đóng. */
    slug: string | null;
    onClose: () => void;
  }
  let { slug, onClose }: Props = $props();

  const form = new RecipeForm();
  let advancedOpen = $state(true);
  /** Tab đang hiển thị (do Tabs giữ) và dạng bản sửa đang là bản gốc. Hai
   * biến tách nhau vì đổi tab phải đi qua server để dịch — thất bại thì `tab`
   * bật ngược về `mode`. */
  let tab = $state("form");
  let mode = $state<"form" | "yaml">("form");
  let yamlText = $state("");
  let loading = $state(false);
  let loadError = $state("");
  /** File trên đĩa hỏng cú pháp: chỉ tab YAML sửa được nó. */
  let parseError = $state("");
  let switching = $state(false);
  let saving = $state(false);
  let testing = $state(false);
  let headedTest = $state(false);
  /** Flow đem ra chạy thử. `select_model` chỉ chạy tới bước chọn model rồi
   * dừng — hữu ích khi đang dò đúng chuỗi bấm mở dropdown. */
  let testFlow = $state<FlowKind>("text");
  let testResult = $state<TrialResult | null>(null);

  /** Bản sửa hiện tại theo đúng tab đang mở — tab nào mở thì tab đó là bản gốc. */
  function edit(): RecipeEdit | null {
    if (mode === "yaml") return { yaml: yamlText };
    if (!form.validate()) return null;
    return { patch: form.toPatch() };
  }

  async function load(target: string) {
    loading = true; loadError = ""; parseError = ""; testResult = null; form.error = "";
    try {
      const source = await fetchRecipeSource($apiKey, target);
      yamlText = source.yaml;
      parseError = source.parse_error ?? "";
      if (source.data) form.load(source.data);
      // File hỏng thì biểu mẫu không có gì để hiện — mở thẳng tab YAML.
      mode = source.data ? "form" : "yaml";
      tab = mode;
    } catch (e) {
      loadError = (e as Error).message;
    } finally {
      loading = false;
    }
  }

  /** Đổi tab qua server: chỉ server biết dịch giữa biểu mẫu và YAML, nên
   * chuyến đi này cũng là lúc bản sửa được kiểm tra hợp lệ. */
  async function switchMode(next: "form" | "yaml") {
    if (!slug) { mode = next; return; }
    const payload = edit();
    if (!payload) { showToast(form.error); tab = mode; return; }
    switching = true;
    try {
      const preview = await previewRecipeEdit($apiKey, slug, payload);
      if (next === "yaml") yamlText = preview.yaml;
      else { form.load(preview.data); parseError = ""; }
      mode = next;
      form.error = "";
    } catch (e) {
      showToast((e as Error).message);
      tab = mode;
    } finally {
      switching = false;
    }
  }

  // Tabs tự giữ giá trị của nó; việc dịch bản sửa chạy sau khi tab đã đổi.
  // `untrack` để effect chỉ phụ thuộc vào `tab`/`mode`, không phải mọi ô của
  // biểu mẫu mà `switchMode` đọc.
  $effect(() => {
    const next = tab === "yaml" ? "yaml" : "form";
    if (next !== untrack(() => mode)) untrack(() => switchMode(next));
  });

  async function onTest() {
    if (!slug) return;
    const payload = edit();
    if (!payload) { showToast(form.error); return; }
    testing = true; testResult = null;
    try { testResult = await testRecipeEdit($apiKey, slug, payload, { headed: headedTest, flow: testFlow }); }
    catch (e) { testResult = { ok: false, reply: "", flow: testFlow, error: (e as Error).message }; }
    finally { testing = false; }
  }

  async function onSave() {
    if (!slug) return;
    const payload = edit();
    if (!payload) { showToast(form.error); return; }
    saving = true;
    try {
      await updateRecipe($apiKey, slug, payload);
      showToast(`Đã lưu recipe ${slug}`);
      await refreshAfterRecipeChange();
      onClose();
    } catch (e) {
      form.error = (e as Error).message;
      showToast(form.error);
    } finally {
      saving = false;
    }
  }

  let loadedSlug = $state<string | null>(null);
  $effect(() => {
    if (slug && slug !== loadedSlug) {
      loadedSlug = slug;
      load(slug);
    } else if (!slug) {
      loadedSlug = null;
    }
  });

  const busy = $derived(saving || testing || switching);
</script>

<Sheet.Root open={slug !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
   <Sheet.Content side="right" class="w-full gap-0 p-0 sm:!max-w-[92vw] xl:!max-w-[88rem]">
    <Sheet.Header class="border-b p-4 sm:p-5">
      <div class="flex items-start gap-3">
        <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Sliders size={19} aria-hidden="true" /></div>
        <div class="min-w-0">
          <Sheet.Title class="font-data text-base">{slug ?? ""}</Sheet.Title>
          <Sheet.Description>Workbench đầy đủ cho browser automation. Lưu sẽ validate và nạp lại router ngay.</Sheet.Description>
        </div>
      </div>
    </Sheet.Header>

    <div class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
      {#if loading}
        <div class="flex min-h-40 flex-col items-center justify-center gap-2 text-muted-foreground" role="status" aria-live="polite">
          <CircleNotch class="animate-spin" size={24} /><p class="text-sm">Đang đọc recipe…</p>
        </div>
      {:else if loadError}
        <div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
          <WarningCircle class="mt-0.5 shrink-0" />{loadError}
        </div>
      {:else}
        <div class="grid gap-5">
          {#if form.error}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{form.error}</div>{/if}
          {#if parseError}
            <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="alert">
              <WarningCircle class="mt-0.5 shrink-0" />recipe.yaml đang hỏng cú pháp ({parseError}) — sửa ở tab YAML rồi lưu để dùng lại biểu mẫu.
            </div>
          {/if}

          <Tabs.Root bind:value={tab}>
            <Tabs.List class="w-fit">
              <Tabs.Trigger value="form" disabled={switching || !!parseError}>Biểu mẫu</Tabs.Trigger>
              <Tabs.Trigger value="yaml" disabled={switching}>YAML</Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="form" class="mt-4 grid gap-5">
              <RecipeFields {form} idPrefix="re" bind:advancedOpen />
            </Tabs.Content>

            <Tabs.Content value="yaml" class="mt-4 grid gap-2">
              <label for="re-yaml" class="text-sm font-medium">recipe.yaml</label>
              <Textarea id="re-yaml" class="min-h-[26rem] font-data text-xs leading-relaxed" spellcheck={false} bind:value={yamlText} />
              <p class="text-xs text-muted-foreground">Toàn văn file. Giữ được cả những khóa biểu mẫu không có (<span class="font-data">login.accounts</span>, <span class="font-data">response.exclude</span>…).</p>
            </Tabs.Content>
          </Tabs.Root>

          {#if testResult}<TrialReport result={testResult} />{/if}
        </div>
      {/if}
    </div>

    <Sheet.Footer class="flex-row flex-wrap items-center justify-between gap-3 border-t p-4 sm:p-5">
      <div class="flex flex-wrap items-center gap-3">
        <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headedTest} aria-label="Hiện browser khi kiểm tra" /> Hiện browser khi kiểm tra</label>
        <label class="flex items-center gap-2 text-sm">
          Flow
          <!-- Ô nhập chứ không phải select: recipe đặt được flow tên riêng, danh
               sách gợi ý chỉ liệt kê các flow có sẵn. -->
          <input
            bind:value={testFlow}
            list="re-flow-kinds"
            aria-label="Flow đem ra chạy thử"
            aria-invalid={testFlow !== "" && !flowNameOk(testFlow)}
            spellcheck={false}
            class="h-8 w-44 rounded-md border border-input bg-background px-2 font-data text-sm aria-[invalid=true]:border-destructive"
          />
          <datalist id="re-flow-kinds">
            {#each FLOW_KINDS as kind (kind)}<option value={kind}>{flowLabel(kind)}</option>{/each}
          </datalist>
        </label>
      </div>
      <div class="flex flex-wrap gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={loading || busy} onclick={() => slug && load(slug)}><ArrowClockwise /> Đọc lại</Button>
        <Button type="button" variant="outline" size="sm" disabled={loading || busy} onclick={onTest}>{#if testing}<CircleNotch class="animate-spin" /> Đang kiểm tra{:else}<Check /> Kiểm tra{/if}</Button>
        <Button type="button" size="sm" disabled={loading || busy} onclick={onSave}>{#if saving}<CircleNotch class="animate-spin" /> Đang lưu{:else}<FloppyDisk /> Lưu{/if}</Button>
      </div>
    </Sheet.Footer>
  </Sheet.Content>
</Sheet.Root>
