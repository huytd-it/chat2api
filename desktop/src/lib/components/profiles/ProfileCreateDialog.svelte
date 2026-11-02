<script lang="ts">
  import { untrack } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { createProfile, loginGoogle, saveGoogleIdentity } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { CircleNotch, Plus, WarningCircle } from "phosphor-svelte";
  import { GMAIL_RE, MAX_TABS_LIMIT, modeLabel, PROFILE_NAME_ERROR, PROFILE_NAME_RE, SCRAPLING_MODES, validTabs } from "./profile-utils";

  interface Props {
    open: boolean;
    /** Tạo xong: panel nạp lại danh sách và chọn profile mới. */
    oncreated: (name: string) => void | Promise<void>;
    /** Trạng thái Google của profile đổi: panel nạp lại khối Google. */
    ongooglechanged: (id: number) => void;
  }
  let { open = $bindable(false), oncreated, ongooglechanged }: Props = $props();

  let name = $state(""); let mode = $state("dynamic"); let maxTabs = $state<number>(4); let headless = $state(true);
  let gmail = $state(""); let gmailPass = $state(""); let loginNow = $state(true);
  let busy = $state(false); let nameError = $state(""); let tabsError = $state(""); let gmailError = $state(""); let formError = $state("");

  $effect(() => {
    if (!open) return;
    untrack(() => {
      name = ""; mode = "dynamic"; maxTabs = 4; headless = true;
      gmail = ""; gmailPass = ""; loginNow = true;
      nameError = ""; tabsError = ""; gmailError = ""; formError = "";
    });
  });

  /** Lưu Gmail/mật khẩu; đăng nhập ngay thì mở cửa sổ và tự điền (chạy nền). */
  async function saveGmail(id: number, profileName: string, email: string) {
    await saveGoogleIdentity($apiKey, id, { email, password: gmailPass || undefined, auto_login: true });
    ongooglechanged(id);
    if (!loginNow || !gmailPass) return;
    showToast(`${profileName}: đang mở cửa sổ và tự điền Gmail — Google đòi xác minh thì làm tiếp trong cửa sổ đó`);
    loginGoogle($apiKey, id, true)
      .then((res) => {
        ongooglechanged(id);
        if (!res.identity.waiting) showToast(`${profileName}: Google ${res.identity.status === "signed_in" ? "đã đăng nhập" : res.identity.detail || res.identity.status}`);
      })
      .catch((e) => showToast((e as Error).message));
  }

  async function submit(e: Event) {
    e.preventDefault();
    const cleanName = name.trim().toLowerCase();
    const email = gmail.trim().toLowerCase();
    nameError = PROFILE_NAME_RE.test(cleanName) ? "" : PROFILE_NAME_ERROR;
    tabsError = validTabs(maxTabs) ? "" : `Số tab từ 1 đến ${MAX_TABS_LIMIT}`;
    gmailError = email && !GMAIL_RE.test(email) ? "Gmail không hợp lệ" : "";
    if (nameError || tabsError || gmailError) return;
    busy = true; formError = "";
    try {
      const created = await createProfile($apiKey, cleanName, { scrapling_mode: mode, max_tabs: maxTabs, headless });
      showToast(`Đã tạo profile ${cleanName} (${modeLabel(mode)})`);
      // Profile đã tồn tại từ đây: lỗi Gmail chỉ báo lại, không giữ form, vì
      // bấm Tạo lần nữa sẽ vấp trùng tên. Gmail sửa tiếp được ở khối Google.
      if (email) await saveGmail(created.id, cleanName, email).catch((err) => showToast(`Đã tạo profile nhưng chưa lưu được Gmail: ${(err as Error).message}`));
      open = false;
      await oncreated(cleanName);
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>Tạo profile</Dialog.Title>
      <Dialog.Description>Một thư mục Chromium riêng, dùng chung đăng nhập cho nhiều domain.</Dialog.Description>
    </Dialog.Header>
    <form id="profile-create-form" class="grid gap-4" onsubmit={submit} novalidate>
      {#if formError}<div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{formError}</div>{/if}
      <div class="grid gap-1.5">
        <label for="profile-name" class="text-sm font-medium">Tên profile</label>
        <Input id="profile-name" class="font-data" placeholder="main" aria-invalid={!!nameError} aria-describedby={nameError ? "profile-name-error" : undefined} bind:value={name} />
        {#if nameError}<p id="profile-name-error" class="text-xs text-destructive">{nameError}</p>{/if}
      </div>
      <div class="grid gap-4 sm:grid-cols-[minmax(0,1fr)_8rem]">
        <div class="grid gap-1.5">
          <label for="profile-mode" class="text-sm font-medium">Chế độ Scrapling</label>
          <Select.Root type="single" bind:value={mode}>
            <Select.Trigger id="profile-mode" class="w-full">{modeLabel(mode)}</Select.Trigger>
            <Select.Content>{#each SCRAPLING_MODES as m (m.value)}<Select.Item value={m.value} label={m.label}>{m.label} · {m.detail}</Select.Item>{/each}</Select.Content>
          </Select.Root>
        </div>
        <div class="grid gap-1.5">
          <label for="profile-tabs" class="text-sm font-medium">Tab tối đa</label>
          <Input id="profile-tabs" type="number" min="1" max={MAX_TABS_LIMIT} aria-invalid={!!tabsError} bind:value={maxTabs} />
        </div>
        {#if tabsError}<p class="text-xs text-destructive sm:col-span-2">{tabsError}</p>{/if}
      </div>
      <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headless} aria-label="Chạy profile ẩn" /> Chạy ẩn</label>
      <fieldset class="grid gap-3 border-t pt-4">
        <legend class="sr-only">Tài khoản Google tùy chọn</legend>
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="grid gap-1.5">
            <label for="profile-gmail" class="text-sm font-medium">Gmail <span class="font-normal text-muted-foreground">(tuỳ chọn)</span></label>
            <Input id="profile-gmail" type="email" autocomplete="off" class="font-data" placeholder="ban@gmail.com" aria-invalid={!!gmailError} aria-describedby={gmailError ? "profile-gmail-error" : undefined} bind:value={gmail} />
            {#if gmailError}<p id="profile-gmail-error" class="text-xs text-destructive">{gmailError}</p>{/if}
          </div>
          <div class="grid gap-1.5 content-start">
            <label for="profile-gmail-pass" class="text-sm font-medium">Mật khẩu Gmail</label>
            <Input id="profile-gmail-pass" type="password" autocomplete="new-password" placeholder="để server tự điền" bind:value={gmailPass} />
          </div>
        </div>
        <label class="flex items-center gap-2 text-sm"><Switch bind:checked={loginNow} aria-label="Đăng nhập Google ngay sau khi tạo" /> Đăng nhập ngay sau khi tạo</label>
        <p class="text-xs leading-5 text-muted-foreground">Gmail và mật khẩu lưu ở server, không hiện lại. Server tự điền khi đăng nhập Google, khi phiên Google rớt, và khi đăng nhập web bằng nút “Continue with Google”.</p>
      </fieldset>
    </form>
    <Dialog.Footer>
      <Button variant="ghost" onclick={() => (open = false)}>Hủy</Button>
      <Button type="submit" form="profile-create-form" disabled={busy}>{#if busy}<CircleNotch class="animate-spin" />{:else}<Plus />{/if} Tạo</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
