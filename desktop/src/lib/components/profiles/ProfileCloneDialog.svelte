<script lang="ts">
  import { untrack } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { cloneProfile, type ProfileInfo } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { CircleNotch, Copy, Stop, WarningCircle } from "phosphor-svelte";
  import { modeLabel, PROFILE_NAME_ERROR, PROFILE_NAME_RE, SCRAPLING_MODES } from "./profile-utils";

  interface Props {
    /** Profile đang nhân bản; null = đóng dialog. */
    profile: ProfileInfo | null;
    closing: boolean;
    oncancel: () => void;
    oncloseprofile: (p: ProfileInfo) => void;
    oncloned: (name: string) => void | Promise<void>;
  }
  let { profile, closing, oncancel, oncloseprofile, oncloned }: Props = $props();

  let name = $state(""); let mode = $state("dynamic"); let busy = $state(false); let nameError = $state(""); let formError = $state("");
  const id = $derived(profile?.id ?? null);

  // Chỉ nạp lại khi đổi profile: danh sách refresh giữa chừng không được xoá chữ đang gõ.
  $effect(() => {
    if (id === null) return;
    untrack(() => {
      name = `${profile!.name}-copy`;
      mode = profile!.scrapling_mode || "dynamic";
      nameError = ""; formError = "";
    });
  });

  // Nhân bản = copy thư mục Chromium + account sang profile mới: giữ nguyên
  // đăng nhập mà vẫn có đường lui khi đổi chế độ Scrapling.
  async function submit(e: Event) {
    e.preventDefault();
    const p = profile;
    if (!p) return;
    const cleanName = name.trim().toLowerCase();
    nameError = PROFILE_NAME_RE.test(cleanName) ? "" : PROFILE_NAME_ERROR;
    if (nameError) return;
    busy = true; formError = "";
    try {
      await cloneProfile($apiKey, p.id, cleanName, { scrapling_mode: mode });
      showToast(`Đã nhân bản ${p.name} → ${cleanName} (${modeLabel(mode)})`);
      oncancel();
      await oncloned(cleanName);
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog.Root open={profile !== null} onOpenChange={(v) => { if (!v) oncancel(); }}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>Nhân bản {profile?.name}</Dialog.Title>
      <Dialog.Description>Copy cả thư mục Chromium ({profile?.domains ?? 0} domain) sang profile mới. Bản gốc không đổi, cache không được copy.</Dialog.Description>
    </Dialog.Header>
    <form id="profile-clone-form" class="grid gap-4" onsubmit={submit} novalidate>
      {#if formError}<div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{formError}</div>{/if}
      {#if profile?.open}
        <div class="flex flex-col gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 sm:flex-row sm:items-center">
          <p class="min-w-0 flex-1 text-sm text-warning">Profile đang chạy. Đóng trước đã, copy lúc Chromium còn ghi sẽ ra bản sao hỏng.</p>
          <Button variant="outline" size="sm" disabled={closing} onclick={() => profile && oncloseprofile(profile)}>{#if closing}<CircleNotch class="animate-spin" />{:else}<Stop />{/if} Đóng profile</Button>
        </div>
      {/if}
      <div class="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem]">
        <div class="grid gap-1.5">
          <label for="clone-name" class="text-sm font-medium">Tên bản sao</label>
          <Input id="clone-name" class="font-data" aria-invalid={!!nameError} bind:value={name} />
          {#if nameError}<p class="text-xs text-destructive">{nameError}</p>{/if}
        </div>
        <div class="grid gap-1.5 content-start">
          <label for="clone-mode" class="text-sm font-medium">Chế độ Scrapling</label>
          <Select.Root type="single" bind:value={mode}>
            <Select.Trigger id="clone-mode" class="w-full">{modeLabel(mode)}</Select.Trigger>
            <Select.Content>{#each SCRAPLING_MODES as m (m.value)}<Select.Item value={m.value} label={m.label}>{m.label} · {m.detail}</Select.Item>{/each}</Select.Content>
          </Select.Root>
        </div>
      </div>
    </form>
    <Dialog.Footer>
      <Button variant="ghost" onclick={oncancel}>Hủy</Button>
      <Button type="submit" form="profile-clone-form" disabled={busy || !!profile?.open}>{#if busy}<CircleNotch class="animate-spin" />{:else}<Copy />{/if} Nhân bản</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
