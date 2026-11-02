<script lang="ts">
  import { untrack } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { updateProfile, type ProfileInfo } from "$lib/api";
  import { refreshProfiles } from "$lib/sync";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import { Textarea } from "$lib/components/ui/textarea";
  import * as Select from "$lib/components/ui/select";
  import * as Sheet from "$lib/components/ui/sheet";
  import { CircleNotch, Star, WarningCircle } from "phosphor-svelte";
  import { MAX_TABS_LIMIT, modeLabel, SCRAPLING_MODES, validTabs } from "./profile-utils";

  interface Props {
    /** Profile đang chỉnh; null = đóng sheet. */
    profile: ProfileInfo | null;
    oncancel: () => void;
  }
  let { profile, oncancel }: Props = $props();

  let mode = $state("dynamic"); let maxTabs = $state<number>(4); let headless = $state(true); let notes = $state("");
  let busy = $state<"" | "save" | "default">(""); let formError = $state(""); let tabsError = $state("");
  const id = $derived(profile?.id ?? null);
  const modeChanged = $derived(!!profile && mode !== (profile.scrapling_mode || "dynamic"));

  // Chỉ nạp lại khi đổi profile: danh sách refresh giữa chừng không được xoá chữ đang gõ.
  $effect(() => {
    if (id === null) return;
    untrack(() => {
      mode = profile!.scrapling_mode || "dynamic";
      maxTabs = profile!.max_tabs;
      headless = profile!.headless === 1;
      notes = profile!.notes ?? "";
      formError = ""; tabsError = "";
    });
  });

  // Đổi chế độ KHÔNG đụng tới thư mục Chromium của profile: session mới nhận
  // đúng `user_data_dir` cũ nên cookie/localStorage đã đăng nhập đi theo. Chỉ
  // cần nói rõ điều đó, vì "đổi chế độ" nghe như phải đăng nhập lại từ đầu.
  async function submit(e: Event) {
    e.preventDefault();
    const p = profile;
    if (!p) return;
    tabsError = validTabs(maxTabs) ? "" : `Số tab từ 1 đến ${MAX_TABS_LIMIT}`;
    if (tabsError) return;
    const changedMode = modeChanged;
    const wasOpen = p.open;
    const nextMode = mode;
    busy = "save"; formError = "";
    try {
      await updateProfile($apiKey, p.id, { scrapling_mode: nextMode, max_tabs: maxTabs, headless, notes });
      await refreshProfiles();
      oncancel();
      if (changedMode) showToast(`${p.name} đã chuyển sang ${modeLabel(nextMode)} — vẫn dùng lại profile cũ nên toàn bộ đăng nhập giữ nguyên.` + (wasOpen ? " Cửa sổ đang chạy sẽ được mở lại bằng chế độ mới." : ""));
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      busy = "";
    }
  }

  async function makeDefault() {
    const p = profile;
    if (!p) return;
    busy = "default"; formError = "";
    try {
      await updateProfile($apiKey, p.id, { is_default: true });
      await refreshProfiles();
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      busy = "";
    }
  }
</script>

<Sheet.Root open={profile !== null} onOpenChange={(v) => { if (!v) oncancel(); }}>
  <Sheet.Content side="right" class="w-full gap-0 p-0 sm:max-w-md!">
    <Sheet.Header class="border-b p-4">
      <Sheet.Title class="break-all font-data pr-8">Cài đặt {profile?.name}</Sheet.Title>
      <Sheet.Description>Tài khoản Google chỉnh ở khối Google của profile.</Sheet.Description>
    </Sheet.Header>
    <form id="profile-settings-form" class="grid flex-1 content-start gap-4 overflow-y-auto p-4" onsubmit={submit} novalidate>
      {#if formError}<div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{formError}</div>{/if}
      <div class="grid gap-1.5">
        <label for="settings-mode" class="text-sm font-medium">Chế độ Scrapling</label>
        <Select.Root type="single" bind:value={mode}>
          <Select.Trigger id="settings-mode" class="w-full">{modeLabel(mode)}</Select.Trigger>
          <Select.Content>{#each SCRAPLING_MODES as m (m.value)}<Select.Item value={m.value} label={m.label}>{m.label} · {m.detail}</Select.Item>{/each}</Select.Content>
        </Select.Root>
        {#if modeChanged}
          <p class="text-xs leading-5 text-muted-foreground">Đổi sang <strong class="text-foreground">{modeLabel(mode)}</strong> dùng lại chính thư mục profile này ({profile?.domains} domain) — không phải đăng nhập lại. {#if profile?.open}Cửa sổ đang chạy sẽ được đóng và mở lại bằng chế độ mới; nếu profile đang phục vụ request thì việc mở lại đợi tới lúc rảnh.{/if}</p>
        {/if}
      </div>
      <div class="grid gap-1.5">
        <label for="settings-tabs" class="text-sm font-medium">Tab tối đa</label>
        <Input id="settings-tabs" class="w-28" type="number" min="1" max={MAX_TABS_LIMIT} aria-invalid={!!tabsError} bind:value={maxTabs} />
        {#if tabsError}<p class="text-xs text-destructive">{tabsError}</p>{/if}
      </div>
      <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headless} aria-label={`Chạy ẩn profile ${profile?.name ?? ""}`} /> Chạy ẩn</label>
      <div class="grid gap-1.5">
        <label for="settings-notes" class="text-sm font-medium">Ghi chú</label>
        <Textarea id="settings-notes" rows={3} bind:value={notes} />
      </div>
      <div class="grid gap-1.5 border-t pt-4">
        <span class="text-sm font-medium">Profile mặc định</span>
        {#if profile?.is_default}
          <p class="flex items-center gap-1.5 text-xs text-muted-foreground"><Star weight="fill" /> Đây là profile mặc định.</p>
        {:else}
          <Button variant="outline" size="sm" class="justify-self-start" disabled={!!busy} onclick={makeDefault}>{#if busy === "default"}<CircleNotch class="animate-spin" />{:else}<Star />{/if} Đặt làm mặc định</Button>
        {/if}
      </div>
      <div class="grid gap-1 border-t pt-4">
        <span class="text-sm font-medium">Thư mục dữ liệu</span>
        <code class="break-all font-data text-xs text-muted-foreground">{profile?.user_data_dir}</code>
      </div>
    </form>
    <Sheet.Footer class="flex-row justify-end gap-2 border-t p-4">
      <Button variant="ghost" onclick={oncancel}>Hủy</Button>
      <Button type="submit" form="profile-settings-form" disabled={!!busy}>{#if busy === "save"}<CircleNotch class="animate-spin" />{/if} Lưu</Button>
    </Sheet.Footer>
  </Sheet.Content>
</Sheet.Root>
