<script lang="ts">
  import { untrack } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { fetchRemoteProfiles, importProfile, type ProfileBundle, type RemoteProfile } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import * as Dialog from "$lib/components/ui/dialog";
  import * as Select from "$lib/components/ui/select";
  import { CircleNotch, MagnifyingGlass, UploadSimple, WarningCircle } from "phosphor-svelte";
  import { PROFILE_NAME_ERROR, PROFILE_NAME_RE } from "./profile-utils";

  interface Props {
    open: boolean;
    onimported: (name: string) => void | Promise<void>;
  }
  let { open = $bindable(false), onimported }: Props = $props();

  let source = $state<"file" | "remote">("file");
  let bundle = $state<ProfileBundle | null>(null);
  let name = $state("");
  let remoteUrl = $state(""); let remoteKey = $state(""); let remoteList = $state<RemoteProfile[] | null>(null); let remotePick = $state("");
  let remoteLoading = $state(false); let busy = $state(false); let formError = $state(""); let nameError = $state("");

  const ready = $derived(source === "file" ? bundle !== null : remotePick !== "");

  $effect(() => {
    if (!open) return;
    untrack(() => {
      source = "file"; bundle = null; name = ""; remoteList = null; remotePick = "";
      formError = ""; nameError = "";
    });
  });

  async function onFile(e: Event) {
    const file = (e.currentTarget as HTMLInputElement).files?.[0];
    bundle = null;
    formError = "";
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      if (data?.format !== "chat2api-profile") throw new Error("không phải file profile của chat2api");
      bundle = data;
      name = data.profile?.name ?? "";
    } catch (err) {
      formError = `Không đọc được ${file.name}: ${(err as Error).message}`;
    }
  }

  async function loadRemote() {
    remoteLoading = true; formError = "";
    try {
      remoteList = await fetchRemoteProfiles($apiKey, remoteUrl.trim(), remoteKey.trim());
      remotePick = remoteList[0]?.name ?? "";
      name = remotePick;
    } catch (err) {
      remoteList = null;
      formError = (err as Error).message;
    } finally {
      remoteLoading = false;
    }
  }

  async function submit(e: Event) {
    e.preventDefault();
    const cleanName = name.trim().toLowerCase();
    nameError = cleanName && !PROFILE_NAME_RE.test(cleanName) ? PROFILE_NAME_ERROR : "";
    if (nameError) return;
    const payload = source === "file"
      ? (bundle ? { bundle } : null)
      : (remotePick ? { remote: { url: remoteUrl.trim(), apiKey: remoteKey.trim(), profile: remotePick } } : null);
    if (!payload) return;
    busy = true; formError = "";
    try {
      const res = await importProfile($apiKey, payload, cleanName);
      showToast(`Đã nhập profile ${res.name}: ${res.imported.accounts} account, ${res.imported.cookies} cookie — đăng nhập được nạp vào browser ở lần mở đầu tiên.`);
      open = false;
      await onimported(res.name);
    } catch (err) {
      formError = (err as Error).message;
    } finally {
      busy = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Nhập profile từ máy khác</Dialog.Title>
      <Dialog.Description>Mang theo cấu hình, danh sách account và phiên đăng nhập.</Dialog.Description>
    </Dialog.Header>
    <form id="profile-import-form" class="grid gap-4" onsubmit={submit} novalidate>
      {#if formError}<div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{formError}</div>{/if}
      <div class="flex flex-wrap items-center gap-2" role="group" aria-label="Nguồn nhập">
        <Button size="sm" variant={source === "file" ? "secondary" : "ghost"} aria-pressed={source === "file"} onclick={() => (source = "file")}>File đã xuất</Button>
        <Button size="sm" variant={source === "remote" ? "secondary" : "ghost"} aria-pressed={source === "remote"} onclick={() => (source = "remote")}>Kéo qua mạng</Button>
      </div>
      {#if source === "file"}
        <div class="grid gap-1.5">
          <label for="import-file" class="text-sm font-medium">File profile</label>
          <Input id="import-file" type="file" accept=".json,application/json" onchange={onFile} />
          {#if bundle}
            <p class="text-xs text-muted-foreground">Profile <strong class="font-data text-foreground">{bundle.profile.name}</strong> · {bundle.accounts.length} account ({bundle.accounts.map((a) => a.host).join(", ") || "chưa khai báo site"}) · {bundle.storage_state?.cookies?.length ?? 0} cookie</p>
          {:else}
            <p class="text-xs text-muted-foreground">Ở máy nguồn, chọn profile rồi vào menu ⋯ → Xuất sang máy khác để lấy file <span class="font-data">.chat2api-profile.json</span>.</p>
          {/if}
        </div>
      {:else}
        <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
          <div class="grid gap-1.5"><label for="import-url" class="text-sm font-medium">Địa chỉ máy nguồn</label><Input id="import-url" class="font-data" placeholder="192.168.1.5:8100" bind:value={remoteUrl} /></div>
          <div class="grid gap-1.5"><label for="import-key" class="text-sm font-medium">API key máy nguồn</label><Input id="import-key" type="password" class="font-data" autocomplete="off" bind:value={remoteKey} /></div>
          <Button variant="outline" disabled={remoteLoading || !remoteUrl.trim()} onclick={loadRemote}>{#if remoteLoading}<CircleNotch class="animate-spin" />{:else}<MagnifyingGlass />{/if} Xem profile</Button>
        </div>
        {#if remoteList && !remoteList.length}
          <p class="text-xs text-muted-foreground">Máy nguồn chưa có profile nào.</p>
        {:else if remoteList}
          <div class="grid gap-1.5">
            <label for="import-pick" class="text-sm font-medium">Profile cần kéo về</label>
            <Select.Root type="single" bind:value={remotePick} onValueChange={(v) => (name = v)}>
              <Select.Trigger id="import-pick" class="w-full font-data">{remotePick || "Chọn profile"}</Select.Trigger>
              <Select.Content>{#each remoteList as r (r.name)}<Select.Item value={r.name} label={r.name}>{r.name} · {r.accounts.length ? r.accounts.map((a) => a.host).join(", ") : "chưa khai báo site"}</Select.Item>{/each}</Select.Content>
            </Select.Root>
          </div>
        {/if}
      {/if}
      <div class="grid gap-1.5">
        <label for="import-name" class="text-sm font-medium">Tên profile ở máy này</label>
        <Input id="import-name" class="font-data" placeholder="giữ tên gốc" aria-invalid={!!nameError} bind:value={name} />
        {#if nameError}<p class="text-xs text-destructive">{nameError}</p>{/if}
      </div>
      <p class="text-xs leading-5 text-muted-foreground">Đăng nhập được nạp vào browser ở lần mở profile đầu tiên. Recipe không đi kèm — máy này cần có recipe cho các site đó. Một số site buộc đăng nhập lại khi thấy IP hoặc thiết bị mới.</p>
    </form>
    <Dialog.Footer>
      <Button variant="ghost" onclick={() => (open = false)}>Hủy</Button>
      <Button type="submit" form="profile-import-form" disabled={busy || !ready}>{#if busy}<CircleNotch class="animate-spin" />{:else}<UploadSimple />{/if} Nhập</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
