<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { profiles, profilesLoading, profilesMeta, refreshProfiles } from "../sync";
  import { closeProfile, createProfile, deleteProfile, detectProfileDomains, openProfile, updateProfile, type ProfileInfo } from "../api";
  import AccountDialog from "./AccountDialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import { Badge } from "$lib/components/ui/badge";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as Card from "$lib/components/ui/card";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { Browser, CircleNotch, FolderOpen, MagnifyingGlass, PencilSimple, Plus, Star, Trash, UserCircle, WarningCircle, X } from "phosphor-svelte";

  let creating = $state(false); let newName = $state(""); let newMaxTabs = $state(4); let newHeadless = $state(true); let creatingBusy = $state(false);
  let busyIds = $state<Set<number>>(new Set());
  let editingId = $state<number | null>(null); let editMaxTabs = $state(4); let editHeadless = $state(true); let editNotes = $state("");
  let watchProfiles = $state<Set<string>>(new Set());
  let suggestions = $state<Record<number, string[]>>({}); let dialogProfile = $state<string | null>(null);
  let deleteTarget = $state<ProfileInfo | null>(null); let purgeChecked = $state(false); let panelError = $state("");

  const liveSuggestions = $derived(
    Object.fromEntries(
      Object.entries(suggestions).map(([id, hosts]) => [
        id,
        hosts.filter((h) => !$profiles.find((p) => p.id === Number(id))?.accounts.some((a) => a.host === h)),
      ]),
    ),
  );

  function setBusy(id: number, on: boolean) {
    const next = new Set(busyIds);
    if (on) next.add(id); else next.delete(id);
    busyIds = next;
  }
  function watchOpen(name: string) { watchProfiles = new Set(watchProfiles).add(name); }
  function watchClose(name: string) { const next = new Set(watchProfiles); next.delete(name); watchProfiles = next; }

  function statusOf(p: ProfileInfo): { label: string; cls: string } { if (p.locked && !p.open) return { label: "Bị khoá", cls: "bg-destructive" }; if (p.open) return { label: `Đang chạy · ${p.tabs} tab`, cls: "bg-success" }; return { label: "Rảnh", cls: "bg-muted-foreground" }; }
  function fail(e: unknown) { panelError = (e as Error).message; showToast(panelError); }
  async function onCreate() { const name = newName.trim().toLowerCase(); if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) { panelError = "Tên profile chỉ gồm chữ thường, số và dấu -"; showToast(panelError); return; } creatingBusy = true; panelError = ""; try { await createProfile($apiKey, name, { max_tabs: newMaxTabs, headless: newHeadless }); showToast(`Đã tạo profile ${name}`); newName = ""; creating = false; await refreshProfiles(); } catch (e) { fail(e); } finally { creatingBusy = false; } }
  function startEdit(p: ProfileInfo) { editingId = p.id; editMaxTabs = p.max_tabs; editHeadless = p.headless === 1; editNotes = p.notes ?? ""; }
  async function saveEdit(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { await updateProfile($apiKey, p.id, { max_tabs: editMaxTabs, headless: editHeadless, notes: editNotes }); editingId = null; await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function makeDefault(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { await updateProfile($apiKey, p.id, { is_default: true }); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onOpen(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { const res = await openProfile($apiKey, p.id); watchOpen(p.name); showToast(res.headless ? `${p.name} đang chạy nền nên không có cửa sổ mới — bấm Đóng rồi Mở lại.` : `Đã mở cửa sổ ${p.name}. Đăng nhập rồi bấm “Dò domain”.`); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onDetect(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { const res = await detectProfileDomains($apiKey, p.id); suggestions = { ...suggestions, [p.id]: res.suggested }; if (!res.suggested.length) showToast(`${p.name}: không có domain nào chưa khai báo.`); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onClose(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { await closeProfile($apiKey, p.name); watchClose(p.name); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  function requestDelete(p: ProfileInfo) { deleteTarget = p; purgeChecked = false; }
  async function confirmDelete() { const p = deleteTarget; if (!p) return; const purge = purgeChecked; deleteTarget = null; setBusy(p.id, true); panelError = ""; try { await deleteProfile($apiKey, p.id, purge); showToast(`Đã xóa profile ${p.name}`); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
</script>

<Card.Root class="overflow-hidden" aria-labelledby="profiles-title">
  <Card.Header class="flex-row items-center justify-between gap-4 border-b"><div class="flex items-start gap-3"><div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><FolderOpen size={19} /></div><div><Card.Title id="profiles-title">Browser profiles</Card.Title><Card.Description>Hạ tầng Chromium dùng chung đăng nhập cho nhiều domain.</Card.Description></div></div><Button variant={creating ? "ghost" : "outline"} size="sm" onclick={() => (creating = !creating)}>{#if creating}<X /> Hủy{:else}<Plus /> Profile mới{/if}</Button></Card.Header>
  <Card.Content class="grid gap-4 p-4 sm:p-6">
    {#if panelError}<div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{panelError}</div>{/if}
    {#if $profilesMeta && !$profilesMeta.persisted}<div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Kho SQLite chưa mở nên chưa quản lý được profile. Xem log khởi động để biết vì sao.</div>
    {:else if $profilesMeta}<div class="rounded-lg border bg-muted/20 p-3 text-xs leading-5 text-muted-foreground"><p>Chế độ <strong class="font-data text-foreground">{$profilesMeta.mode}</strong> · tối đa <strong class="font-data text-foreground">{$profilesMeta.max_profiles}</strong> profile · <span class="break-all font-data">{$profilesMeta.profiles_dir}</span></p><p class="mt-1">Recipe browser có account ở đây được gán profile cho <strong class="text-foreground">từng request</strong>, bất kể chế độ trên — đổi ở Settings → API (<code class="font-data text-foreground">API_ACCOUNT_STRATEGY</code>). Chế độ <code class="font-data text-foreground">{$profilesMeta.mode}</code> chỉ còn quyết định đường chạy cho domain chưa có account nào.</p></div>{/if}

    {#if creating}<form class="grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_8rem_auto_auto] sm:items-end" onsubmit={(e) => { e.preventDefault(); onCreate(); }}><div class="grid gap-1.5"><label for="profile-name" class="text-sm font-medium">Tên profile</label><Input id="profile-name" class="font-data" placeholder="main" bind:value={newName} /></div><div class="grid gap-1.5"><label for="profile-tabs" class="text-sm font-medium">Tab tối đa</label><Input id="profile-tabs" type="number" min="1" max="32" bind:value={newMaxTabs} /></div><label class="flex h-9 items-center gap-2 text-sm"><Switch bind:checked={newHeadless} aria-label="Chạy profile ẩn" /> Chạy ẩn</label><Button type="submit" disabled={creatingBusy}>{#if creatingBusy}<CircleNotch class="animate-spin" />{:else}<Plus />{/if} Tạo</Button></form>{/if}

    {#if $profilesLoading && !$profiles.length}<div class="flex min-h-32 flex-col items-center justify-center gap-2 text-muted-foreground" role="status" aria-live="polite"><CircleNotch class="animate-spin" size={24} /><p class="text-sm">Đang tải profiles…</p></div>
    {:else if !$profiles.length && $profilesMeta?.persisted}<div class="flex min-h-32 flex-col items-center justify-center text-center"><UserCircle class="mb-2 text-muted-foreground" size={28} /><p class="font-medium">Chưa có profile</p><p class="mt-1 text-sm text-muted-foreground">Tạo profile để gom đăng nhập nhiều domain.</p></div>{/if}

    <div class="grid gap-3">
      {#each $profiles as p (p.id)}{@const status = statusOf(p)}
        <article class="rounded-lg border bg-card p-4">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start"><div class="flex min-w-0 flex-1 items-start gap-3"><span class={`mt-1.5 size-2.5 shrink-0 rounded-full ${status.cls}`}></span><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><h3 class="font-data font-semibold">{p.name}</h3>{#if p.is_default}<Badge variant="secondary"><Star weight="fill" /> Mặc định</Badge>{/if}</div><p class="mt-1 text-xs text-muted-foreground">{p.domains} domain · {p.max_tabs} tab tối đa · {status.label}</p></div></div>
            <div class="flex flex-wrap gap-1.5"><Button variant="outline" size="sm" disabled={busyIds.has(p.id)} onclick={() => onOpen(p)}><Browser /> Mở</Button><Button variant="outline" size="sm" disabled={busyIds.has(p.id) || !p.open} onclick={() => onDetect(p)}><MagnifyingGlass /> Dò domain</Button><Button variant="outline" size="sm" disabled={busyIds.has(p.id)} onclick={() => (dialogProfile = p.name)}><Plus /> Account</Button><Button variant="ghost" size="icon-sm" aria-label={`Sửa profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => (editingId === p.id ? (editingId = null) : startEdit(p))}><PencilSimple /></Button>{#if p.open}<Button variant="ghost" size="icon-sm" aria-label={`Đóng profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => onClose(p)}><X /></Button>{/if}<Button variant="destructive" size="icon-sm" aria-label={`Xóa profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => requestDelete(p)}><Trash /></Button></div></div>
          {#if p.accounts.length}<div class="mt-3 flex flex-wrap gap-1.5">{#each p.accounts as account (account.id)}<Badge variant="outline" class="font-data">{account.host} / {account.label}</Badge>{/each}</div>{/if}
          {#if liveSuggestions[p.id]?.length}<div class="mt-3 flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Còn đăng nhập chưa khai báo: {liveSuggestions[p.id].join(", ")} — bấm “Account” để thêm.</div>{/if}
          {#if editingId === p.id}<form class="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-[8rem_minmax(0,1fr)_auto] sm:items-end" onsubmit={(e) => { e.preventDefault(); saveEdit(p); }}><div class="grid gap-1.5"><label for="edit-tabs-{p.id}" class="text-sm font-medium">Tab tối đa</label><Input id="edit-tabs-{p.id}" type="number" min="1" max="32" bind:value={editMaxTabs} /></div><div class="grid gap-1.5"><label for="edit-notes-{p.id}" class="text-sm font-medium">Ghi chú</label><Input id="edit-notes-{p.id}" bind:value={editNotes} /></div><div class="flex flex-wrap items-center gap-2"><label class="flex h-8 items-center gap-2 text-sm"><Switch bind:checked={editHeadless} aria-label={`Chạy ẩn profile ${p.name}`} /> Chạy ẩn</label><Button type="submit" size="sm" disabled={busyIds.has(p.id)}>Lưu</Button>{#if !p.is_default}<Button type="button" variant="outline" size="sm" disabled={busyIds.has(p.id)} onclick={() => makeDefault(p)}><Star /> Mặc định</Button>{/if}</div></form>{/if}
          {#if watchProfiles.has(p.name)}<div class="mt-3 flex flex-col gap-3 rounded-lg border border-warning/20 bg-warning/5 p-3 sm:flex-row sm:items-center"><Browser class="shrink-0 text-warning" /><p class="min-w-0 flex-1 text-sm">Cửa sổ profile này đang mở — đăng nhập rồi bấm “Dò domain”.</p><Button variant="ghost" size="sm" onclick={() => watchClose(p.name)}>Ẩn nhắc này</Button></div>{/if}
        </article>
      {/each}
    </div>
  </Card.Content>
</Card.Root>

{#if dialogProfile !== null}<AccountDialog profile={dialogProfile} onclose={() => (dialogProfile = null)} />{/if}
<AlertDialog.Root open={deleteTarget !== null} onOpenChange={(open) => { if (!open) deleteTarget = null; }}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>Xóa profile {deleteTarget?.name}?</AlertDialog.Title>
      <AlertDialog.Description>
        Profile sẽ bị gỡ khỏi danh sách. Thư mục <code class="break-all font-data">{deleteTarget?.user_data_dir}</code> giữ toàn bộ đăng nhập của profile này.
      </AlertDialog.Description>
    </AlertDialog.Header>
    <label class="flex items-start gap-2 rounded-lg border p-3 text-sm">
      <Checkbox bind:checked={purgeChecked} aria-label="Xóa vĩnh viễn thư mục dữ liệu Chromium" />
      <span>Xóa vĩnh viễn thư mục dữ liệu Chromium <span class="block text-xs text-muted-foreground">Bỏ trống để chỉ gỡ khỏi danh sách — có thể dùng lại thư mục sau này.</span></span>
    </label>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>Hủy</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmDelete}>Xóa profile</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
