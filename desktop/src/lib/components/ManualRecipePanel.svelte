<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { createRecipe, testRecipe } from "../api";
  import { RecipeForm } from "../recipeForm.svelte";
  import { refreshAfterRecipeChange } from "../sync";
  import RecipeFields from "./RecipeFields.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Card from "$lib/components/ui/card";
  import * as Sheet from "$lib/components/ui/sheet";
  import { Check, CircleNotch, Plus, Sliders, Wrench } from "phosphor-svelte";

  interface Props {
    /** Gọi một lần khi tạo recipe thành công, kèm slug mới. */
    onSuccess?: (slug: string) => void;
  }
  let { onSuccess }: Props = $props();

  let open = $state(false);
  let advancedOpen = $state(false);

  const form = new RecipeForm();
  let slug = $state("");

  let headedTest = $state(false);
  let creating = $state(false);
  let testing = $state(false);
  let testResult = $state<{ ok: boolean; reply: string; error?: string } | null>(null);

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

  function handleOpenChange(next: boolean) {
    open = next;
    if (!next) {
      // giữ lại dữ liệu để người dùng không mất công nhập lại,
      // chỉ xóa báo lỗi / kết quả test khi đóng
      form.error = "";
    }
  }

  async function onTest() {
    const spec = buildSpec();
    if (!spec) { showToast(form.error); return; }
    testing = true; testResult = null;
    try { testResult = await testRecipe($apiKey, spec, headedTest); }
    catch (e) { testResult = { ok: false, reply: "", error: (e as Error).message }; }
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
      open = false;
    } catch (e) { form.error = (e as Error).message; showToast(form.error); }
    finally { creating = false; }
  }
</script>

<Card.Root class="overflow-hidden" aria-labelledby="manual-recipe-title">
  <Card.Header class="flex-row items-start justify-between gap-4">
    <div class="flex items-start gap-3">
      <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Wrench size={19} aria-hidden="true" /></div>
      <div>
        <Card.Title id="manual-recipe-title" class="text-base">Recipe workbench</Card.Title>
        <Card.Description class="mt-1 max-w-2xl">Khai báo đầy đủ luồng browser, models, tín hiệu hoàn tất, session và account routing trong một panel riêng — không còn lỗi tràn form trong tab.</Card.Description>
      </div>
    </div>
  </Card.Header>
  <Card.Content class="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 py-4">
    <p class="text-xs leading-relaxed text-muted-foreground">Mở workbench dạng panel trượt — toàn bộ <span class="font-data">RecipeFields</span> hiển thị rộng rãi, có kiểm tra kết nối trước khi tạo.</p>
    <Button onclick={() => (open = true)}><Sliders /> Tạo recipe thủ công</Button>
  </Card.Content>
  <Card.Footer class="border-t bg-muted/10 px-4 py-3 text-xs text-muted-foreground sm:px-6">
    Slug + URL là bắt buộc. Mọi cấu hình khác có preset hợp lý — mở panel để tinh chỉnh.
  </Card.Footer>
</Card.Root>

<Sheet.Root bind:open onOpenChange={handleOpenChange}>
  <Sheet.Content side="right" class="w-full gap-0 p-0 sm:!max-w-[92vw] xl:!max-w-[88rem]">
    <Sheet.Header class="border-b p-4 sm:p-5">
      <div class="flex items-start gap-3">
        <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Wrench size={19} aria-hidden="true" /></div>
        <div class="min-w-0">
          <Sheet.Title class="font-data text-base">Tạo browser recipe</Sheet.Title>
          <Sheet.Description>Mọi cấu hình nằm trên cùng một panel. Bắt đầu bằng slug và URL, sau đó mô tả chính xác thứ tự browser sẽ chọn model, nhập prompt, gửi và thu kết quả.</Sheet.Description>
        </div>
      </div>
    </Sheet.Header>

    <div class="min-h-0 flex-1 overflow-y-auto p-4 sm:p-5">
      <div class="grid gap-5">
        {#if form.error}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{form.error}</div>{/if}

        <div class="grid gap-3 rounded-xl border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_minmax(16rem,.7fr)] sm:items-end">
          <div>
            <h2 class="text-sm font-semibold">Định danh recipe</h2>
            <p class="mt-1 text-xs leading-relaxed text-muted-foreground">Slug sẽ thành <span class="font-data">recipes/&lt;slug&gt;/recipe.yaml</span> và không đổi sau khi tạo.</p>
          </div>
          <label for="mr-slug" class="grid gap-1.5 text-sm font-medium">Slug <span class="text-destructive">*</span><Input id="mr-slug" class="font-data" placeholder="my-chat-site" bind:value={slug} /></label>
        </div>

        <RecipeFields {form} idPrefix="mr" bind:advancedOpen />

        {#if testResult}
          <div class={`rounded-lg border p-3 text-sm ${testResult.ok ? "border-success/30 bg-success/5 text-success" : "border-destructive/30 bg-destructive/5 text-destructive"}`} role="status">
            {#if testResult.ok}Kiểm tra thành công — nhận được phản hồi: "{testResult.reply}"
            {:else}Kiểm tra thất bại{testResult.error ? `: ${testResult.error}` : testResult.reply ? ` — phản hồi: "${testResult.reply}"` : " — không nhận được phản hồi hợp lệ."}{/if}
          </div>
        {/if}
      </div>
    </div>

    <Sheet.Footer class="flex-row flex-wrap items-center justify-between gap-3 border-t p-4 sm:p-5">
      <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headedTest} aria-label="Hiện browser khi kiểm tra" /> Hiện browser khi kiểm tra</label>
      <div class="flex flex-wrap gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={testing || creating} onclick={() => { resetForm(); form.error=""; testResult=null; }}>Đặt lại</Button>
        <Button type="button" variant="outline" size="sm" disabled={testing || creating} onclick={onTest}>{#if testing}<CircleNotch class="animate-spin" /> Đang kiểm tra{:else}<Check /> Kiểm tra kết nối{/if}</Button>
        <Button type="button" size="sm" disabled={creating || testing} onclick={onCreate}>{#if creating}<CircleNotch class="animate-spin" /> Đang tạo{:else}<Plus /> Tạo recipe{/if}</Button>
      </div>
    </Sheet.Footer>
  </Sheet.Content>
</Sheet.Root>
