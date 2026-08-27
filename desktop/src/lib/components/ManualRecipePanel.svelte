<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { createRecipe, testRecipe, type ManualRecipeSpec } from "../api";
  import { refreshAfterRecipeChange } from "../sync";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Select from "$lib/components/ui/select";
  import * as Card from "$lib/components/ui/card";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import { CaretDown, Check, CircleNotch, Plus, PlusCircle, Trash, Wrench } from "phosphor-svelte";

  interface Props {
    /** Gọi một lần khi tạo recipe thành công, kèm slug mới. */
    onSuccess?: (slug: string) => void;
  }
  let { onSuccess }: Props = $props();

  let panelOpen = $state(false);

  let slug = $state("");
  let url = $state("");
  let inputSelector = $state("");
  let inputMode = $state<"fill" | "type">("fill");
  let submitMode = $state<"enter" | "click">("enter");
  let submitSelector = $state("");
  let lastMessageSelector = $state("");
  let doneType = $state<"stable_text" | "selector_appear" | "selector_disappear" | "copy_button">("stable_text");
  let doneSelector = $state("");
  // Số nhập bằng <input type="number"> nhưng giữ ở dạng string: `type` của
  // Input là prop động (không phải literal trong markup của nó) nên Svelte
  // KHÔNG tự ép kiểu number cho bind:value — ép tay ở buildSpec() để tránh
  // rơi vào tình huống ô trống trở thành "" thay vì undefined.
  let quietMs = $state("");
  let timeoutMs = $state("");
  let copyScope = $state<"after" | "inside" | "page">("after");
  let copyFallbackMs = $state("");
  let newChatMode = $state<"none" | "selector" | "url">("none");
  let newChatSelector = $state("");
  let newChatUrl = $state("");
  let keepContext = $state(true);
  let anonTrialLimit = $state("");
  let models = $state<string[]>([""]);
  let advancedOpen = $state(false);
  let readyDelayMs = $state("");
  let inputDelayMs = $state("");
  let readyTimeoutMs = $state("");

  let headedTest = $state(false);
  let creating = $state(false);
  let testing = $state(false);
  let formError = $state("");
  let testResult = $state<{ ok: boolean; reply: string; error?: string } | null>(null);

  const doneTypeLabel: Record<string, string> = {
    stable_text: "Text đứng yên",
    selector_appear: "Selector xuất hiện",
    selector_disappear: "Selector biến mất",
    copy_button: "Nút Copy hiện ra",
  };

  function addModel() { models = [...models, ""]; }
  function removeModel(i: number) { models = models.filter((_, idx) => idx !== i); }

  function resetForm() {
    slug = ""; url = ""; inputSelector = ""; inputMode = "fill"; submitMode = "enter"; submitSelector = "";
    lastMessageSelector = ""; doneType = "stable_text"; doneSelector = ""; quietMs = ""; timeoutMs = "";
    copyScope = "after"; copyFallbackMs = ""; newChatMode = "none"; newChatSelector = ""; newChatUrl = "";
    keepContext = true; anonTrialLimit = ""; models = [""]; readyDelayMs = ""; inputDelayMs = "";
    readyTimeoutMs = ""; testResult = null; formError = "";
  }

  /** "" -> undefined; số hợp lệ -> number; chuỗi hỏng -> NaN (buildSpec bắt lỗi). */
  function toInt(raw: string): number | undefined {
    const s = raw.trim();
    if (!s) return undefined;
    const n = Number(s);
    return Number.isFinite(n) ? Math.trunc(n) : NaN;
  }

  function buildSpec(): ManualRecipeSpec | null {
    formError = "";
    const cleanSlug = slug.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(cleanSlug)) { formError = "Slug chỉ gồm chữ thường, số và dấu -"; return null; }
    const cleanUrl = url.trim();
    if (!cleanUrl) { formError = "Nhập URL trang chat."; return null; }
    try { new URL(cleanUrl); } catch { formError = "URL không hợp lệ."; return null; }
    if (!inputSelector.trim()) { formError = "Nhập CSS selector của ô nhập tin nhắn."; return null; }
    if (submitMode === "click" && !submitSelector.trim()) { formError = "Nhập CSS selector của nút gửi."; return null; }
    if (!lastMessageSelector.trim()) { formError = "Nhập CSS selector của khối tin nhắn AI."; return null; }
    if ((doneType === "selector_appear" || doneType === "selector_disappear") && !doneSelector.trim()) {
      formError = "Nhập CSS selector cho tín hiệu hoàn tất."; return null;
    }
    const modelIds = models.map((m) => m.trim()).filter(Boolean);
    if (!modelIds.length) { formError = "Cần ít nhất một model id."; return null; }
    if (newChatMode === "selector" && !newChatSelector.trim()) { formError = "Nhập selector nút tạo chat mới."; return null; }
    if (newChatMode === "url" && !newChatUrl.trim()) { formError = "Nhập URL mở chat mới."; return null; }

    const nums = {
      quiet: toInt(quietMs), timeout: toInt(timeoutMs), fallback: toInt(copyFallbackMs),
      anon: toInt(anonTrialLimit), readyDelay: toInt(readyDelayMs), inputDelay: toInt(inputDelayMs),
      readyTimeout: toInt(readyTimeoutMs),
    };
    for (const [key, value] of Object.entries(nums)) {
      if (value !== undefined && Number.isNaN(value)) { formError = `Trường "${key}" phải là số nguyên >= 0.`; return null; }
    }

    const spec: ManualRecipeSpec = {
      slug: cleanSlug,
      url: cleanUrl,
      prompt: {
        input_selector: inputSelector.trim(),
        input_mode: inputMode,
        submit: submitMode === "enter" ? "Enter" : `click:${submitSelector.trim()}`,
      },
      response: {
        last_message_selector: lastMessageSelector.trim(),
        done_signal: {
          type: doneType,
          ...(doneSelector.trim() ? { selector: doneSelector.trim() } : {}),
          ...(nums.quiet !== undefined ? { quiet_ms: nums.quiet } : {}),
          ...(nums.timeout !== undefined ? { timeout_ms: nums.timeout } : {}),
          ...(doneType === "copy_button" ? { scope: copyScope } : {}),
          ...(doneType === "copy_button" && nums.fallback !== undefined ? { fallback_quiet_ms: nums.fallback } : {}),
        },
      },
      models: modelIds.map((id) => ({ id })),
      keep_context: keepContext,
      ...(nums.anon !== undefined ? { anon_trial_limit: nums.anon } : {}),
    };
    if (newChatMode === "selector") spec.new_chat = { selector: newChatSelector.trim() };
    else if (newChatMode === "url") spec.new_chat = { url: newChatUrl.trim() };
    if (nums.readyDelay !== undefined || nums.inputDelay !== undefined || nums.readyTimeout !== undefined) {
      spec.timing = {
        ...(nums.readyDelay !== undefined ? { ready_delay_ms: nums.readyDelay } : {}),
        ...(nums.inputDelay !== undefined ? { input_delay_ms: nums.inputDelay } : {}),
        ...(nums.readyTimeout !== undefined ? { ready_timeout_ms: nums.readyTimeout } : {}),
      };
    }
    return spec;
  }

  async function onTest() {
    const spec = buildSpec();
    if (!spec) { showToast(formError); return; }
    testing = true; testResult = null;
    try { testResult = await testRecipe($apiKey, spec, headedTest); }
    catch (e) { testResult = { ok: false, reply: "", error: (e as Error).message }; }
    finally { testing = false; }
  }

  async function onCreate() {
    const spec = buildSpec();
    if (!spec) { showToast(formError); return; }
    creating = true;
    try {
      await createRecipe($apiKey, spec);
      showToast(`Đã tạo recipe ${spec.slug}`);
      await refreshAfterRecipeChange();
      onSuccess?.(spec.slug);
      resetForm();
      panelOpen = false;
    } catch (e) { formError = (e as Error).message; showToast(formError); }
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
        {#if formError}<div class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">{formError}</div>{/if}

        <div class="grid gap-3 sm:grid-cols-2">
          <div class="grid gap-1.5">
            <label for="mr-slug" class="text-sm font-medium">Slug <span class="text-destructive">*</span></label>
            <Input id="mr-slug" class="font-data" placeholder="my-chat-site" bind:value={slug} />
          </div>
          <div class="grid gap-1.5">
            <label for="mr-url" class="text-sm font-medium">URL <span class="text-destructive">*</span></label>
            <Input id="mr-url" class="font-data" type="url" placeholder="https://chat.example.com" bind:value={url} />
          </div>
        </div>

        <fieldset class="grid gap-3 rounded-lg border p-3">
          <legend class="px-1 text-sm font-medium">Gửi tin nhắn</legend>
          <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_9rem]">
            <div class="grid gap-1.5">
              <label for="mr-input-sel" class="text-sm font-medium">Selector ô nhập <span class="text-destructive">*</span></label>
              <Input id="mr-input-sel" class="font-data" placeholder="#prompt-textarea" bind:value={inputSelector} />
            </div>
            <div class="grid gap-1.5">
              <label for="mr-input-mode" class="text-sm font-medium">Kiểu nhập</label>
              <Select.Root type="single" bind:value={inputMode as unknown as string}>
                <Select.Trigger id="mr-input-mode" class="h-9 w-full">{inputMode === "fill" ? "fill" : "type"}</Select.Trigger>
                <Select.Content>
                  <Select.Item value="fill" label="fill">fill</Select.Item>
                  <Select.Item value="type" label="type">type (contenteditable)</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
          </div>
          <div class="grid gap-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
            <div class="grid gap-1.5">
              <label for="mr-submit-mode" class="text-sm font-medium">Cách gửi</label>
              <Select.Root type="single" bind:value={submitMode as unknown as string}>
                <Select.Trigger id="mr-submit-mode" class="h-9 w-full">{submitMode === "enter" ? "Nhấn Enter" : "Bấm nút"}</Select.Trigger>
                <Select.Content>
                  <Select.Item value="enter" label="Nhấn Enter">Nhấn Enter</Select.Item>
                  <Select.Item value="click" label="Bấm nút">Bấm nút (selector)</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
            {#if submitMode === "click"}
              <div class="grid gap-1.5">
                <label for="mr-submit-sel" class="text-sm font-medium">Selector nút gửi <span class="text-destructive">*</span></label>
                <Input id="mr-submit-sel" class="font-data" placeholder="button[data-testid='send-button']" bind:value={submitSelector} />
              </div>
            {/if}
          </div>
        </fieldset>

        <fieldset class="grid gap-3 rounded-lg border p-3">
          <legend class="px-1 text-sm font-medium">Nhận câu trả lời</legend>
          <div class="grid gap-1.5">
            <label for="mr-reply-sel" class="text-sm font-medium">Selector khối tin nhắn AI <span class="text-destructive">*</span></label>
            <Input id="mr-reply-sel" class="font-data" placeholder=".message.assistant" bind:value={lastMessageSelector} />
            <p class="text-xs text-muted-foreground">Tool luôn lấy phần tử CUỐI cùng khớp selector này.</p>
          </div>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="grid gap-1.5">
              <label for="mr-done-type" class="text-sm font-medium">Tín hiệu hoàn tất</label>
              <Select.Root type="single" bind:value={doneType as unknown as string}>
                <Select.Trigger id="mr-done-type" class="h-9 w-full">{doneTypeLabel[doneType]}</Select.Trigger>
                <Select.Content>
                  <Select.Item value="stable_text" label="Text đứng yên">Text đứng yên (mặc định)</Select.Item>
                  <Select.Item value="copy_button" label="Nút Copy hiện ra">Nút Copy hiện ra</Select.Item>
                  <Select.Item value="selector_appear" label="Selector xuất hiện">Selector xuất hiện</Select.Item>
                  <Select.Item value="selector_disappear" label="Selector biến mất">Selector biến mất</Select.Item>
                </Select.Content>
              </Select.Root>
            </div>
            {#if doneType === "selector_appear" || doneType === "selector_disappear"}
              <div class="grid gap-1.5">
                <label for="mr-done-sel" class="text-sm font-medium">Selector <span class="text-destructive">*</span></label>
                <Input id="mr-done-sel" class="font-data" placeholder=".typing-indicator" bind:value={doneSelector} />
              </div>
            {:else if doneType === "copy_button"}
              <div class="grid gap-1.5">
                <label for="mr-done-sel" class="text-sm font-medium">Selector nút Copy (tùy chọn)</label>
                <Input id="mr-done-sel" class="font-data" placeholder="để trống dùng mặc định" bind:value={doneSelector} />
              </div>
            {/if}
          </div>
          {#if doneType === "copy_button"}
            <div class="grid gap-3 sm:grid-cols-3">
              <div class="grid gap-1.5">
                <label for="mr-copy-scope" class="text-sm font-medium">Vị trí nút</label>
                <Select.Root type="single" bind:value={copyScope as unknown as string}>
                  <Select.Trigger id="mr-copy-scope" class="h-9 w-full">{copyScope}</Select.Trigger>
                  <Select.Content>
                    <Select.Item value="after" label="after">after (sau khối tin nhắn)</Select.Item>
                    <Select.Item value="inside" label="inside">inside (trong khối)</Select.Item>
                    <Select.Item value="page" label="page">page (bất kỳ đâu)</Select.Item>
                  </Select.Content>
                </Select.Root>
              </div>
              <div class="grid gap-1.5">
                <label for="mr-quiet" class="text-sm font-medium">quiet_ms</label>
                <Input id="mr-quiet" type="number" min="0" placeholder="600" bind:value={quietMs} />
              </div>
              <div class="grid gap-1.5">
                <label for="mr-fallback" class="text-sm font-medium">fallback_quiet_ms</label>
                <Input id="mr-fallback" type="number" min="0" placeholder="15000" bind:value={copyFallbackMs} />
              </div>
            </div>
          {:else}
            <div class="grid gap-3 sm:grid-cols-2">
              <div class="grid gap-1.5">
                <label for="mr-quiet" class="text-sm font-medium">quiet_ms</label>
                <Input id="mr-quiet" type="number" min="0" placeholder="3000" bind:value={quietMs} />
              </div>
              <div class="grid gap-1.5">
                <label for="mr-timeout" class="text-sm font-medium">timeout_ms</label>
                <Input id="mr-timeout" type="number" min="0" placeholder="120000" bind:value={timeoutMs} />
              </div>
            </div>
          {/if}
        </fieldset>

        <fieldset class="grid gap-2">
          <legend class="px-1 text-sm font-medium">Models <span class="text-destructive">*</span></legend>
          {#each models as _, i}
            <div class="flex items-center gap-2">
              <Input class="h-9 font-data" placeholder="chat-web" bind:value={models[i]} />
              {#if models.length > 1}<Button type="button" variant="ghost" size="icon-sm" aria-label="Xóa model" onclick={() => removeModel(i)}><Trash /></Button>{/if}
            </div>
          {/each}
          <Button type="button" variant="outline" size="sm" class="w-fit" onclick={addModel}><PlusCircle /> Thêm model</Button>
        </fieldset>

        <Collapsible.Root bind:open={advancedOpen}>
          <Collapsible.Trigger class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
            <CaretDown class={`transition-transform ${advancedOpen ? "" : "-rotate-90"}`} size={13} aria-hidden="true" /> Tùy chọn nâng cao
          </Collapsible.Trigger>
          <Collapsible.Content>
            <div class="mt-3 grid gap-4 rounded-lg border bg-muted/20 p-3">
              <div class="grid gap-3 sm:grid-cols-2">
                <div class="grid gap-1.5">
                  <label for="mr-newchat-mode" class="text-sm font-medium">Mở chat mới</label>
                  <Select.Root type="single" bind:value={newChatMode as unknown as string}>
                    <Select.Trigger id="mr-newchat-mode" class="h-9 w-full">{newChatMode === "none" ? "Không cần (trang luôn mở sẵn chat trống)" : newChatMode === "selector" ? "Bấm nút" : "Mở URL"}</Select.Trigger>
                    <Select.Content>
                      <Select.Item value="none" label="Không cần">Không cần</Select.Item>
                      <Select.Item value="selector" label="Bấm nút">Bấm nút (selector)</Select.Item>
                      <Select.Item value="url" label="Mở URL">Mở URL</Select.Item>
                    </Select.Content>
                  </Select.Root>
                </div>
                {#if newChatMode === "selector"}
                  <div class="grid gap-1.5"><label for="mr-newchat-sel" class="text-sm font-medium">Selector</label><Input id="mr-newchat-sel" class="font-data" bind:value={newChatSelector} /></div>
                {:else if newChatMode === "url"}
                  <div class="grid gap-1.5"><label for="mr-newchat-url" class="text-sm font-medium">URL</label><Input id="mr-newchat-url" class="font-data" bind:value={newChatUrl} /></div>
                {/if}
              </div>
              <div class="grid gap-3 sm:grid-cols-3">
                <div class="grid gap-1.5"><label for="mr-ready-delay" class="text-sm font-medium">ready_delay_ms</label><Input id="mr-ready-delay" type="number" min="0" placeholder="1200" bind:value={readyDelayMs} /></div>
                <div class="grid gap-1.5"><label for="mr-input-delay" class="text-sm font-medium">input_delay_ms</label><Input id="mr-input-delay" type="number" min="0" placeholder="400" bind:value={inputDelayMs} /></div>
                <div class="grid gap-1.5"><label for="mr-ready-timeout" class="text-sm font-medium">ready_timeout_ms</label><Input id="mr-ready-timeout" type="number" min="0" placeholder="20000" bind:value={readyTimeoutMs} /></div>
              </div>
              <div class="grid gap-1.5">
                <label for="mr-anon-trial" class="text-sm font-medium">Lượt dùng thử ẩn danh</label>
                <Input id="mr-anon-trial" type="number" min="0" class="w-40" placeholder="để trống = không giới hạn" bind:value={anonTrialLimit} />
                <p class="text-xs text-muted-foreground">Chỉ áp dụng khi recipe chưa có account nào đăng nhập. Thêm account sau ở tab Sites/Profiles.</p>
              </div>
              <label class="flex cursor-pointer items-center justify-between gap-4 rounded-lg border bg-card px-3 py-2 text-sm"><span><strong class="font-medium">Giữ context giữa các request</strong><span class="block text-xs text-muted-foreground">Tắt nếu site khôi phục hội thoại cũ khi mở lại tab.</span></span><Switch bind:checked={keepContext} aria-label="Giữ context giữa các request" /></label>
            </div>
          </Collapsible.Content>
        </Collapsible.Root>

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
