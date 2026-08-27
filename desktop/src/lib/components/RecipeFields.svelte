<script lang="ts">
  import { DONE_TYPE_LABEL, type RecipeForm } from "../recipeForm.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Select from "$lib/components/ui/select";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import { CaretDown, PlusCircle, Trash } from "phosphor-svelte";

  interface Props {
    form: RecipeForm;
    /** Tiền tố id — hai bản của biểu mẫu có thể cùng nằm trong một trang. */
    idPrefix: string;
    /** Mở sẵn khối nâng cao (màn sửa thường cần tới nó ngay). */
    advancedOpen?: boolean;
  }
  let { form, idPrefix, advancedOpen = $bindable(false) }: Props = $props();

  const id = (name: string) => `${idPrefix}-${name}`;
</script>

<div class="grid gap-1.5">
  <label for={id("url")} class="text-sm font-medium">URL <span class="text-destructive">*</span></label>
  <Input id={id("url")} class="font-data" type="url" placeholder="https://chat.example.com" bind:value={form.url} />
</div>

<fieldset class="grid gap-3 rounded-lg border p-3">
  <legend class="px-1 text-sm font-medium">Gửi tin nhắn</legend>
  <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_9rem]">
    <div class="grid gap-1.5">
      <label for={id("input-sel")} class="text-sm font-medium">Selector ô nhập <span class="text-destructive">*</span></label>
      <Input id={id("input-sel")} class="font-data" placeholder="#prompt-textarea" bind:value={form.inputSelector} />
    </div>
    <div class="grid gap-1.5">
      <label for={id("input-mode")} class="text-sm font-medium">Kiểu nhập</label>
      <Select.Root type="single" bind:value={form.inputMode as unknown as string}>
        <Select.Trigger id={id("input-mode")} class="h-9 w-full">{form.inputMode === "fill" ? "fill" : "type"}</Select.Trigger>
        <Select.Content>
          <Select.Item value="fill" label="fill">fill</Select.Item>
          <Select.Item value="type" label="type">type (contenteditable)</Select.Item>
        </Select.Content>
      </Select.Root>
    </div>
  </div>
  <div class="grid gap-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
    <div class="grid gap-1.5">
      <label for={id("submit-mode")} class="text-sm font-medium">Cách gửi</label>
      <Select.Root type="single" bind:value={form.submitMode as unknown as string}>
        <Select.Trigger id={id("submit-mode")} class="h-9 w-full">{form.submitMode === "enter" ? "Nhấn Enter" : "Bấm nút"}</Select.Trigger>
        <Select.Content>
          <Select.Item value="enter" label="Nhấn Enter">Nhấn Enter</Select.Item>
          <Select.Item value="click" label="Bấm nút">Bấm nút (selector)</Select.Item>
        </Select.Content>
      </Select.Root>
    </div>
    {#if form.submitMode === "click"}
      <div class="grid gap-1.5">
        <label for={id("submit-sel")} class="text-sm font-medium">Selector nút gửi <span class="text-destructive">*</span></label>
        <Input id={id("submit-sel")} class="font-data" placeholder="button[data-testid='send-button']" bind:value={form.submitSelector} />
      </div>
    {/if}
  </div>
</fieldset>

<fieldset class="grid gap-3 rounded-lg border p-3">
  <legend class="px-1 text-sm font-medium">Nhận câu trả lời</legend>
  <div class="grid gap-1.5">
    <label for={id("reply-sel")} class="text-sm font-medium">Selector khối tin nhắn AI <span class="text-destructive">*</span></label>
    <Input id={id("reply-sel")} class="font-data" placeholder=".message.assistant" bind:value={form.lastMessageSelector} />
    <p class="text-xs text-muted-foreground">Tool luôn lấy phần tử CUỐI cùng khớp selector này.</p>
  </div>
  <div class="grid gap-3 sm:grid-cols-2">
    <div class="grid gap-1.5">
      <label for={id("done-type")} class="text-sm font-medium">Tín hiệu hoàn tất</label>
      <Select.Root type="single" bind:value={form.doneType as unknown as string}>
        <Select.Trigger id={id("done-type")} class="h-9 w-full">{DONE_TYPE_LABEL[form.doneType]}</Select.Trigger>
        <Select.Content>
          <Select.Item value="stable_text" label="Text đứng yên">Text đứng yên (mặc định)</Select.Item>
          <Select.Item value="copy_button" label="Nút Copy hiện ra">Nút Copy hiện ra</Select.Item>
          <Select.Item value="selector_appear" label="Selector xuất hiện">Selector xuất hiện</Select.Item>
          <Select.Item value="selector_disappear" label="Selector biến mất">Selector biến mất</Select.Item>
        </Select.Content>
      </Select.Root>
    </div>
    {#if form.doneType === "selector_appear" || form.doneType === "selector_disappear"}
      <div class="grid gap-1.5">
        <label for={id("done-sel")} class="text-sm font-medium">Selector <span class="text-destructive">*</span></label>
        <Input id={id("done-sel")} class="font-data" placeholder=".typing-indicator" bind:value={form.doneSelector} />
      </div>
    {:else if form.doneType === "copy_button"}
      <div class="grid gap-1.5">
        <label for={id("done-sel")} class="text-sm font-medium">Selector nút Copy (tùy chọn)</label>
        <Input id={id("done-sel")} class="font-data" placeholder="để trống dùng mặc định" bind:value={form.doneSelector} />
      </div>
    {/if}
  </div>
  {#if form.doneType === "copy_button"}
    <div class="grid gap-3 sm:grid-cols-3">
      <div class="grid gap-1.5">
        <label for={id("copy-scope")} class="text-sm font-medium">Vị trí nút</label>
        <Select.Root type="single" bind:value={form.copyScope as unknown as string}>
          <Select.Trigger id={id("copy-scope")} class="h-9 w-full">{form.copyScope}</Select.Trigger>
          <Select.Content>
            <Select.Item value="after" label="after">after (sau khối tin nhắn)</Select.Item>
            <Select.Item value="inside" label="inside">inside (trong khối)</Select.Item>
            <Select.Item value="page" label="page">page (bất kỳ đâu)</Select.Item>
          </Select.Content>
        </Select.Root>
      </div>
      <div class="grid gap-1.5">
        <label for={id("quiet")} class="text-sm font-medium">quiet_ms</label>
        <Input id={id("quiet")} type="number" min="0" placeholder="600" bind:value={form.quietMs} />
      </div>
      <div class="grid gap-1.5">
        <label for={id("fallback")} class="text-sm font-medium">fallback_quiet_ms</label>
        <Input id={id("fallback")} type="number" min="0" placeholder="15000" bind:value={form.copyFallbackMs} />
      </div>
    </div>
  {:else}
    <div class="grid gap-3 sm:grid-cols-2">
      <div class="grid gap-1.5">
        <label for={id("quiet")} class="text-sm font-medium">quiet_ms</label>
        <Input id={id("quiet")} type="number" min="0" placeholder="3000" bind:value={form.quietMs} />
      </div>
      <div class="grid gap-1.5">
        <label for={id("timeout")} class="text-sm font-medium">timeout_ms</label>
        <Input id={id("timeout")} type="number" min="0" placeholder="120000" bind:value={form.timeoutMs} />
      </div>
    </div>
  {/if}
</fieldset>

<fieldset class="grid gap-2">
  <legend class="px-1 text-sm font-medium">Models <span class="text-destructive">*</span></legend>
  {#each form.models as _, i}
    <div class="flex items-center gap-2">
      <Input class="h-9 font-data" placeholder="chat-web" bind:value={form.models[i]} />
      {#if form.models.length > 1}<Button type="button" variant="ghost" size="icon-sm" aria-label="Xóa model" onclick={() => form.removeModel(i)}><Trash /></Button>{/if}
    </div>
  {/each}
  <Button type="button" variant="outline" size="sm" class="w-fit" onclick={() => form.addModel()}><PlusCircle /> Thêm model</Button>
</fieldset>

<Collapsible.Root bind:open={advancedOpen}>
  <Collapsible.Trigger class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
    <CaretDown class={`transition-transform ${advancedOpen ? "" : "-rotate-90"}`} size={13} aria-hidden="true" /> Tùy chọn nâng cao
  </Collapsible.Trigger>
  <Collapsible.Content>
    <div class="mt-3 grid gap-4 rounded-lg border bg-muted/20 p-3">
      <div class="grid gap-3 sm:grid-cols-2">
        <div class="grid gap-1.5">
          <label for={id("newchat-mode")} class="text-sm font-medium">Mở chat mới</label>
          <Select.Root type="single" bind:value={form.newChatMode as unknown as string}>
            <Select.Trigger id={id("newchat-mode")} class="h-9 w-full">{form.newChatMode === "none" ? "Không cần (trang luôn mở sẵn chat trống)" : form.newChatMode === "selector" ? "Bấm nút" : "Mở URL"}</Select.Trigger>
            <Select.Content>
              <Select.Item value="none" label="Không cần">Không cần</Select.Item>
              <Select.Item value="selector" label="Bấm nút">Bấm nút (selector)</Select.Item>
              <Select.Item value="url" label="Mở URL">Mở URL</Select.Item>
            </Select.Content>
          </Select.Root>
        </div>
        {#if form.newChatMode === "selector"}
          <div class="grid gap-1.5"><label for={id("newchat-sel")} class="text-sm font-medium">Selector</label><Input id={id("newchat-sel")} class="font-data" bind:value={form.newChatSelector} /></div>
        {:else if form.newChatMode === "url"}
          <div class="grid gap-1.5"><label for={id("newchat-url")} class="text-sm font-medium">URL</label><Input id={id("newchat-url")} class="font-data" bind:value={form.newChatUrl} /></div>
        {/if}
      </div>
      <div class="grid gap-3 sm:grid-cols-3">
        <div class="grid gap-1.5"><label for={id("ready-delay")} class="text-sm font-medium">ready_delay_ms</label><Input id={id("ready-delay")} type="number" min="0" placeholder="1200" bind:value={form.readyDelayMs} /></div>
        <div class="grid gap-1.5"><label for={id("input-delay")} class="text-sm font-medium">input_delay_ms</label><Input id={id("input-delay")} type="number" min="0" placeholder="400" bind:value={form.inputDelayMs} /></div>
        <div class="grid gap-1.5"><label for={id("ready-timeout")} class="text-sm font-medium">ready_timeout_ms</label><Input id={id("ready-timeout")} type="number" min="0" placeholder="20000" bind:value={form.readyTimeoutMs} /></div>
      </div>
      <div class="grid gap-1.5">
        <label for={id("anon-trial")} class="text-sm font-medium">Lượt dùng thử ẩn danh</label>
        <Input id={id("anon-trial")} type="number" min="0" class="w-40" placeholder="để trống = không giới hạn" bind:value={form.anonTrialLimit} />
        <p class="text-xs text-muted-foreground">Chỉ áp dụng khi recipe chưa có account nào đăng nhập. Thêm account ở tab Profiles.</p>
      </div>
      <label class="flex cursor-pointer items-center justify-between gap-4 rounded-lg border bg-card px-3 py-2 text-sm"><span><strong class="font-medium">Giữ context giữa các request</strong><span class="block text-xs text-muted-foreground">Tắt nếu site khôi phục hội thoại cũ khi mở lại tab.</span></span><Switch bind:checked={form.keepContext} aria-label="Giữ context giữa các request" /></label>
      <label class="flex cursor-pointer items-center justify-between gap-4 rounded-lg border bg-card px-3 py-2 text-sm"><span><strong class="font-medium">Giữ cấu trúc markdown</strong><span class="block text-xs text-muted-foreground">Đọc câu trả lời theo khối (heading, list, code) thay vì text thuần.</span></span><Switch bind:checked={form.markdownFormat} aria-label="Giữ cấu trúc markdown" /></label>
      <label class="flex cursor-pointer items-center justify-between gap-4 rounded-lg border bg-card px-3 py-2 text-sm"><span><strong class="font-medium">Lưu HTML gốc</strong><span class="block text-xs text-muted-foreground">Kèm HTML của câu trả lời vào bản ghi session để soi lại sau.</span></span><Switch bind:checked={form.captureHtml} aria-label="Lưu HTML gốc" /></label>
    </div>
  </Collapsible.Content>
</Collapsible.Root>
