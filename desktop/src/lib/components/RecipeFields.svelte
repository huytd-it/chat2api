<script lang="ts">
  import { discoverRecipeModels } from "../api";
  import { DONE_TYPE_LABEL, type RecipeForm } from "../recipeForm.svelte";
  import { apiKey, showToast } from "../stores";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Select from "$lib/components/ui/select";
  import {
    ArrowClockwise, Browser, ChatCircleDots, CircleNotch, Clock,
    Copy, Database, PaperPlaneTilt, PlusCircle, Robot, Trash,
  } from "phosphor-svelte";

  interface Props {
    form: RecipeForm;
    idPrefix: string;
    advancedOpen?: boolean;
  }

  let { form, idPrefix, advancedOpen = $bindable(false) }: Props = $props();
  const id = (name: string) => `${idPrefix}-${name}`;
  let discoveringModels = $state(false);

  async function fetchModels() {
    const url = form.url.trim();
    if (!url) { showToast("Nhập URL trước khi lấy danh sách model."); return; }
    discoveringModels = true;
    try {
      const result = await discoverRecipeModels($apiKey, url);
      if (!result.models.length) {
        showToast("Không dò thấy model control. Có thể khai báo model và action bằng tay.");
        return;
      }
      form.setModels(result.models);
      showToast(`Đã lấy ${result.models.length} model.`);
    } catch (error) {
      showToast("Không lấy được models: " + (error as Error).message);
    } finally {
      discoveringModels = false;
    }
  }
</script>

<div class="recipe-workbench">
  <section class="recipe-section recipe-identity" aria-labelledby={id("identity-title")}>
    <div class="recipe-section-head">
      <span class="recipe-section-icon"><Browser aria-hidden="true" /></span>
      <div>
        <h3 id={id("identity-title")}>Trang đích</h3>
        <p>Điểm bắt đầu của mọi request browser.</p>
      </div>
      <span class="recipe-required">Bắt buộc</span>
    </div>
    <div class="recipe-fields cols-1">
      <label class="recipe-field" for={id("url")}>
        <span>URL trang chat</span>
        <Input id={id("url")} class="font-data" type="url" placeholder="https://chat.example.com" bind:value={form.url} />
      </label>
    </div>
  </section>

  <div class="recipe-main-flow">
    <section class="recipe-section" aria-labelledby={id("prompt-title")}>
      <div class="recipe-section-head">
        <span class="recipe-section-icon"><ChatCircleDots aria-hidden="true" /></span>
        <div><h3 id={id("prompt-title")}>Nhập prompt</h3><p>Định vị editor và cách Playwright đặt nội dung.</p></div>
      </div>
      <div class="recipe-fields cols-selector">
        <label class="recipe-field" for={id("input-sel")}>
          <span>Selector ô nhập <b>*</b></span>
          <Input id={id("input-sel")} class="font-data" placeholder="#prompt-textarea" bind:value={form.inputSelector} />
        </label>
        <label class="recipe-field" for={id("input-mode")}>
          <span>Phương thức nhập</span>
          <Select.Root type="single" bind:value={form.inputMode as unknown as string}>
            <Select.Trigger id={id("input-mode")} class="h-9 w-full">{form.inputMode === "fill" ? "fill" : "type"}</Select.Trigger>
            <Select.Content><Select.Item value="fill" label="fill">fill</Select.Item><Select.Item value="type" label="type">type · contenteditable</Select.Item></Select.Content>
          </Select.Root>
        </label>
      </div>
      <div class="recipe-fields cols-selector">
        <label class="recipe-field" for={id("submit-sel")}>
          <span>Selector nút gửi {form.submitMode === "click" ? "*" : ""}</span>
          <Input id={id("submit-sel")} class="font-data" disabled={form.submitMode !== "click"} placeholder="button[data-testid='send-button']" bind:value={form.submitSelector} />
        </label>
        <label class="recipe-field" for={id("submit-mode")}>
          <span>Action gửi</span>
          <Select.Root type="single" bind:value={form.submitMode as unknown as string}>
            <Select.Trigger id={id("submit-mode")} class="h-9 w-full">{form.submitMode === "enter" ? "Nhấn Enter" : "Bấm nút"}</Select.Trigger>
            <Select.Content><Select.Item value="enter" label="Nhấn Enter">Nhấn Enter</Select.Item><Select.Item value="click" label="Bấm nút">Bấm selector</Select.Item></Select.Content>
          </Select.Root>
        </label>
      </div>
    </section>

    <section class="recipe-section" aria-labelledby={id("response-title")}>
      <div class="recipe-section-head">
        <span class="recipe-section-icon"><PaperPlaneTilt aria-hidden="true" /></span>
        <div><h3 id={id("response-title")}>Thu câu trả lời</h3><p>Chọn reply cuối và quyết định thời điểm stream kết thúc.</p></div>
      </div>
      <label class="recipe-field" for={id("reply-sel")}>
        <span>Selector tin nhắn AI <b>*</b></span>
        <Input id={id("reply-sel")} class="font-data" placeholder=".message.assistant" bind:value={form.lastMessageSelector} />
        <small>Luôn đọc phần tử cuối cùng khớp selector.</small>
      </label>
      <div class="recipe-fields cols-2">
        <label class="recipe-field" for={id("done-type")}>
          <span>Tín hiệu hoàn tất</span>
          <Select.Root type="single" bind:value={form.doneType as unknown as string}>
            <Select.Trigger id={id("done-type")} class="h-9 w-full">{DONE_TYPE_LABEL[form.doneType]}</Select.Trigger>
            <Select.Content>
              <Select.Item value="copy_button" label="Nút Copy">Nút Copy hiện ra</Select.Item>
              <Select.Item value="stable_text" label="Text đứng yên">Text đứng yên</Select.Item>
              <Select.Item value="selector_appear" label="Selector xuất hiện">Selector xuất hiện</Select.Item>
              <Select.Item value="selector_disappear" label="Selector biến mất">Selector biến mất</Select.Item>
            </Select.Content>
          </Select.Root>
        </label>
        <label class="recipe-field" for={id("done-sel")}>
          <span>Selector tín hiệu {form.doneType === "copy_button" ? "(tùy chọn)" : form.doneType === "stable_text" ? "(không dùng)" : "*"}</span>
          <Input id={id("done-sel")} class="font-data" disabled={form.doneType === "stable_text"} placeholder={form.doneType === "copy_button" ? "để trống dùng bộ dò Copy" : ".typing-indicator"} bind:value={form.doneSelector} />
        </label>
      </div>
      <div class="recipe-fields cols-3">
        <label class="recipe-field" for={id("quiet")}><span>quiet_ms</span><Input id={id("quiet")} type="number" min="0" placeholder={form.doneType === "copy_button" ? "600" : "3000"} bind:value={form.quietMs} /></label>
        <label class="recipe-field" for={id("timeout")}><span>timeout_ms</span><Input id={id("timeout")} type="number" min="0" placeholder="120000" bind:value={form.timeoutMs} /></label>
        <label class="recipe-field" for={id("fallback")}><span>fallback_quiet_ms</span><Input id={id("fallback")} type="number" min="0" disabled={form.doneType !== "copy_button"} placeholder="15000" bind:value={form.copyFallbackMs} /></label>
      </div>
      {#if form.doneType === "copy_button"}
        <div class="recipe-fields cols-2">
          <label class="recipe-field" for={id("copy-scope")}>
            <span>Phạm vi tìm nút Copy</span>
            <Select.Root type="single" bind:value={form.copyScope as unknown as string}>
              <Select.Trigger id={id("copy-scope")} class="h-9 w-full">{form.copyScope}</Select.Trigger>
              <Select.Content><Select.Item value="after" label="after">after · sau reply</Select.Item><Select.Item value="inside" label="inside">inside · trong reply</Select.Item><Select.Item value="page" label="page">page · toàn trang</Select.Item></Select.Content>
            </Select.Root>
          </label>
          <label class="recipe-field" for={id("copy-exclude")}><span>Loại trừ selector</span><Input id={id("copy-exclude")} class="font-data" placeholder="pre, .code-actions" bind:value={form.copyExclude} /></label>
        </div>
        <label class="recipe-toggle" for={id("copy-result")}>
          <span><Copy aria-hidden="true" /><span><strong>Dùng nội dung clipboard</strong><small>Bấm nút Copy của reply cuối thay vì chỉ đọc text DOM.</small></span></span>
          <Switch id={id("copy-result")} bind:checked={form.useCopyResult} />
        </label>
      {/if}
      <div class="recipe-toggle-row">
        <label class="recipe-toggle compact"><span><strong>Giữ Markdown</strong><small>Bảo toàn heading, list và code.</small></span><Switch bind:checked={form.markdownFormat} aria-label="Giữ cấu trúc markdown" /></label>
        <label class="recipe-toggle compact"><span><strong>Lưu HTML gốc</strong><small>Phục vụ inspector và debug.</small></span><Switch bind:checked={form.captureHtml} aria-label="Lưu HTML gốc" /></label>
      </div>
    </section>
  </div>

  <aside class="recipe-side-config" aria-label="Cấu hình recipe bổ sung">
    <section class="recipe-section" aria-labelledby={id("models-title")}>
      <div class="recipe-section-head">
        <span class="recipe-section-icon"><Robot aria-hidden="true" /></span>
        <div><h3 id={id("models-title")}>Models</h3><p>Public ID và action chọn model trước khi paste/send.</p></div>
      </div>
      <Button type="button" variant="outline" size="sm" class="w-full" disabled={discoveringModels} onclick={fetchModels}>
        {#if discoveringModels}<CircleNotch class="animate-spin" /> Đang đọc trang{:else}<ArrowClockwise /> Lấy danh sách từ website{/if}
      </Button>
      <div class="model-list">
        {#each form.models as _, i}
          <div class="model-row">
            <div class="model-row-head"><span>Model {i + 1}</span>{#if form.models.length > 1}<Button type="button" variant="ghost" size="icon-sm" aria-label="Xóa model" onclick={() => form.removeModel(i)}><Trash /></Button>{/if}</div>
            <Input class="h-9 font-data" aria-label="Model id" placeholder="chat-web" bind:value={form.models[i]} />
            <Input class="h-9 font-data" aria-label="Action chọn model" placeholder="click:#menu;click:.model-max" bind:value={form.modelActions[i]} />
            <Input class="h-9 font-data" aria-label="Giá trị model" placeholder="option value · tùy chọn" bind:value={form.modelValues[i]} />
          </div>
        {/each}
      </div>
      <Button type="button" variant="ghost" size="sm" class="w-full" onclick={() => form.addModel()}><PlusCircle /> Thêm model</Button>
    </section>

    <section class="recipe-section" aria-labelledby={id("session-title")}>
      <div class="recipe-section-head"><span class="recipe-section-icon"><Database aria-hidden="true" /></span><div><h3 id={id("session-title")}>Session & account</h3><p>Context, account rotation và storage state cũ.</p></div></div>
      <label class="recipe-toggle compact"><span><strong>Giữ context</strong><small>Tái sử dụng page giữa các request.</small></span><Switch bind:checked={form.keepContext} aria-label="Giữ context" /></label>
      <div class="recipe-fields cols-2">
        <label class="recipe-field" for={id("login-strategy")}>
          <span>Chiến lược account</span>
          <Select.Root type="single" bind:value={form.loginStrategy as unknown as string}>
            <Select.Trigger id={id("login-strategy")} class="h-9 w-full">{form.loginStrategy}</Select.Trigger>
            <Select.Content><Select.Item value="round_robin" label="round_robin">round_robin</Select.Item><Select.Item value="fill_first" label="fill_first">fill_first</Select.Item></Select.Content>
          </Select.Root>
        </label>
        <label class="recipe-field" for={id("login-quota")}><span>Quota/account</span><Input id={id("login-quota")} type="number" min="1" bind:value={form.loginQuota} /></label>
      </div>
      <label class="recipe-field" for={id("anon-trial")}><span>Lượt thử ẩn danh</span><Input id={id("anon-trial")} type="number" min="0" placeholder="trống = không giới hạn" bind:value={form.anonTrialLimit} /></label>
      <label class="recipe-field" for={id("storage-state")}><span>storage_state đơn (legacy)</span><Input id={id("storage-state")} class="font-data" placeholder="auth/state.json" bind:value={form.legacyStorageState} /></label>
      {#if form.accountNames.length}
        <div class="account-list">
          {#each form.accountNames as _, i}
            <div class="account-row">
              <Input class="font-data" aria-label="Tên account" placeholder="account-name" bind:value={form.accountNames[i]} />
              <Input class="font-data" aria-label="Storage state account" placeholder="auth/account.json" bind:value={form.accountStorageStates[i]} />
              <Button type="button" variant="ghost" size="icon-sm" aria-label="Xóa account" onclick={() => form.removeAccount(i)}><Trash /></Button>
            </div>
          {/each}
        </div>
      {/if}
      <Button type="button" variant="ghost" size="sm" class="w-full" onclick={() => form.addAccount()}><PlusCircle /> Thêm account YAML</Button>
      <p class="recipe-note">Account trong Profiles cùng domain vẫn được tự động nhận. Khai báo ở đây chỉ dùng khi cần ghim file state riêng.</p>
    </section>

    <section class="recipe-section" aria-labelledby={id("runtime-title")}>
      <div class="recipe-section-head"><span class="recipe-section-icon"><Clock aria-hidden="true" /></span><div><h3 id={id("runtime-title")}>Điều hướng & timing</h3><p>Mở chat sạch và điều chỉnh site tải chậm.</p></div></div>
      <label class="recipe-field" for={id("newchat-mode")}>
        <span>Mở chat mới</span>
        <Select.Root type="single" bind:value={form.newChatMode as unknown as string}>
          <Select.Trigger id={id("newchat-mode")} class="h-9 w-full">{form.newChatMode === "none" ? "Không thao tác" : form.newChatMode === "selector" ? "Bấm selector" : "Mở URL"}</Select.Trigger>
          <Select.Content><Select.Item value="none" label="Không thao tác">Không thao tác</Select.Item><Select.Item value="selector" label="Bấm selector">Bấm selector</Select.Item><Select.Item value="url" label="Mở URL">Mở URL</Select.Item></Select.Content>
        </Select.Root>
      </label>
      {#if form.newChatMode === "selector"}<label class="recipe-field" for={id("newchat-sel")}><span>Selector chat mới *</span><Input id={id("newchat-sel")} class="font-data" placeholder="#new-chat" bind:value={form.newChatSelector} /></label>{/if}
      {#if form.newChatMode === "url"}<label class="recipe-field" for={id("newchat-url")}><span>URL chat mới *</span><Input id={id("newchat-url")} class="font-data" placeholder="https://chat.example.com/new" bind:value={form.newChatUrl} /></label>{/if}
      <div class="recipe-fields cols-3 timing-grid">
        <label class="recipe-field" for={id("ready-delay")}><span>ready delay</span><Input id={id("ready-delay")} type="number" min="0" placeholder="1200" bind:value={form.readyDelayMs} /><small>ms</small></label>
        <label class="recipe-field" for={id("input-delay")}><span>input delay</span><Input id={id("input-delay")} type="number" min="0" placeholder="400" bind:value={form.inputDelayMs} /><small>ms</small></label>
        <label class="recipe-field" for={id("ready-timeout")}><span>ready timeout</span><Input id={id("ready-timeout")} type="number" min="0" placeholder="20000" bind:value={form.readyTimeoutMs} /><small>ms</small></label>
      </div>
    </section>
  </aside>
</div>

<style>
  .recipe-workbench { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(20rem, .85fr); gap: 1rem; align-items: start; }
  .recipe-identity { grid-column: 1 / -1; }
  .recipe-main-flow, .recipe-side-config { display: grid; gap: 1rem; min-width: 0; }
  .recipe-section { display: grid; gap: .9rem; padding: 1rem; border: 1px solid var(--border); border-radius: .75rem; background: color-mix(in oklch, var(--card) 94%, var(--muted)); }
  .recipe-section-head { display: flex; align-items: flex-start; gap: .7rem; min-width: 0; }
  .recipe-section-head > div { min-width: 0; flex: 1; }
  .recipe-section-head h3 { margin: 0; font-size: .9rem; font-weight: 650; line-height: 1.3; }
  .recipe-section-head p { margin: .15rem 0 0; color: var(--muted-foreground); font-size: .75rem; line-height: 1.4; }
  .recipe-section-icon { display: grid; place-items: center; width: 2rem; height: 2rem; flex: 0 0 auto; border-radius: .5rem; background: color-mix(in oklch, var(--primary) 11%, transparent); color: var(--primary); }
  .recipe-section-icon :global(svg) { width: 1rem; height: 1rem; }
  .recipe-required { align-self: center; color: var(--muted-foreground); font-size: .67rem; font-weight: 600; }
  .recipe-fields { display: grid; gap: .75rem; min-width: 0; }
  .cols-1 { grid-template-columns: 1fr; }.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }.cols-selector { grid-template-columns: minmax(0, 1fr) 10rem; }
  .recipe-field { display: grid; align-content: start; gap: .35rem; min-width: 0; color: var(--foreground); font-size: .75rem; font-weight: 550; }
  .recipe-field > span b { color: var(--destructive); }.recipe-field small, .recipe-note { color: var(--muted-foreground); font-size: .68rem; font-weight: 400; line-height: 1.45; }
  .recipe-toggle-row { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .65rem; }
  .recipe-toggle { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: .75rem; border: 1px solid var(--border); border-radius: .6rem; background: var(--background); }
  .recipe-toggle > span { display: flex; align-items: flex-start; gap: .55rem; min-width: 0; }.recipe-toggle > span > span, .recipe-toggle.compact > span { display: grid; gap: .15rem; }
  .recipe-toggle strong { font-size: .76rem; font-weight: 600; }.recipe-toggle small { color: var(--muted-foreground); font-size: .68rem; line-height: 1.35; }.recipe-toggle :global(svg) { width: 1rem; height: 1rem; color: var(--primary); }
  .model-list, .account-list { display: grid; gap: .6rem; }.model-row { display: grid; gap: .45rem; padding: .7rem; border: 1px solid var(--border); border-radius: .6rem; background: var(--background); }.model-row-head { display: flex; align-items: center; justify-content: space-between; color: var(--muted-foreground); font-size: .68rem; font-weight: 600; }
  .account-row { display: grid; grid-template-columns: minmax(7rem, .65fr) minmax(0, 1.35fr) auto; gap: .4rem; align-items: center; }.timing-grid .recipe-field { position: relative; }.timing-grid .recipe-field small { position: absolute; right: .55rem; bottom: .6rem; }
  .recipe-note { margin: -.2rem 0 0; }
  @media (max-width: 1000px) { .recipe-workbench { grid-template-columns: 1fr; }.recipe-identity { grid-column: auto; }.recipe-side-config { grid-template-columns: repeat(2, minmax(0, 1fr)); }.recipe-side-config > :last-child { grid-column: 1 / -1; } }
  @media (max-width: 700px) { .recipe-side-config, .cols-2, .cols-3, .cols-selector, .recipe-toggle-row { grid-template-columns: 1fr; }.recipe-side-config > :last-child { grid-column: auto; }.account-row { grid-template-columns: 1fr auto; }.account-row :global(input:nth-child(2)) { grid-column: 1 / -1; grid-row: 2; }.recipe-section { padding: .85rem; } }
</style>
