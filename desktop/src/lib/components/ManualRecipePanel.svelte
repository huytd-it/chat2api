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
  import * as Collapsible from "$lib/components/ui/collapsible";
  import { CaretDown, Check, CircleNotch, Plus, Wrench } from "phosphor-svelte";

  interface Props {
    /** Gọi một lần khi tạo recipe thành công, kèm slug mới. */
    onSuccess?: (slug: string) => void;
  }
  let { onSuccess }: Props = $props();

  let panelOpen = $state(false);
  let advancedOpen = $state(false);

  const form = new RecipeForm();
  let slug = $state("");

  let headedTest = $state(false);
  let creating = $state(false);
  let testing = $state(false);
  let testResult = $state<{ ok: boolean; reply: string; error?: string } | null>(null);

  /** Slug do panel này giữ (màn sửa dùng slug có sẵn), nên nó tự kiểm. */
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
      panelOpen = false;
    } catch (e) { form.error = (e as Error).message; showToast(form.error); }
    finally { creating = false; }
  }
</script>

<Card.Root class="overflow-hidden" aria-labelledby="manual-recipe-title">
  <Collapsible.Root bind:open={panelOpen}>
    <Collapsible.Trigger class="flex w-full items-center justify-between gap-3 border-b px-4 py-3.5 text-left hover:bg-muted/40 sm:px-6">
      <div class="flex items-start gap-3">
        <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Wrench size={19} aria-hidden="true" /></div>
        <div>
          <p id="manual-recipe-title" class="font-semibold">Nâng cao: tạo recipe thủ công</p>
          <p class="text-sm text-muted-foreground">Không dùng AI — tự khai CSS selector. Dùng khi site quá lạ hoặc phân tích tự động đoán sai.</p>
        </div>
      </div>
      <CaretDown class={`shrink-0 transition-transform ${panelOpen ? "" : "-rotate-90"}`} aria-hidden="true" />
    </Collapsible.Trigger>
    <Collapsible.Content>
      <Card.Content class="grid gap-5 p-4 sm:p-6">
        {#if form.error}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{form.error}</div>{/if}

        <div class="grid gap-1.5">
          <label for="mr-slug" class="text-sm font-medium">Slug <span class="text-destructive">*</span></label>
          <Input id="mr-slug" class="font-data" placeholder="my-chat-site" bind:value={slug} />
        </div>

        <RecipeFields {form} idPrefix="mr" bind:advancedOpen />

        {#if testResult}
          <div class={`rounded-lg border p-3 text-sm ${testResult.ok ? "border-success/30 bg-success/5 text-success" : "border-destructive/30 bg-destructive/5 text-destructive"}`} role="status">
            {#if testResult.ok}Kiểm tra thành công — nhận được phản hồi: "{testResult.reply}"
            {:else}Kiểm tra thất bại{testResult.error ? `: ${testResult.error}` : testResult.reply ? ` — phản hồi: "${testResult.reply}"` : " — không nhận được phản hồi hợp lệ."}{/if}
          </div>
        {/if}

        <div class="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headedTest} aria-label="Hiện browser khi kiểm tra" /> Hiện browser khi kiểm tra</label>
          <div class="flex flex-wrap gap-2">
            <Button type="button" variant="outline" disabled={testing || creating} onclick={onTest}>{#if testing}<CircleNotch class="animate-spin" /> Đang kiểm tra{:else}<Check /> Kiểm tra kết nối{/if}</Button>
            <Button type="button" disabled={creating || testing} onclick={onCreate}>{#if creating}<CircleNotch class="animate-spin" /> Đang tạo{:else}<Plus /> Tạo recipe{/if}</Button>
          </div>
        </div>
      </Card.Content>
    </Collapsible.Content>
  </Collapsible.Root>
</Card.Root>
