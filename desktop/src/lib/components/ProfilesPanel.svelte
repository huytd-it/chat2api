<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, showToast } from "../stores";
  import { cooldowns, ensureProfiles, profiles, profilesError, profilesLoading, profilesMeta, refreshCooldowns, refreshProfiles, domains, ensureDomains, isAccountLocked } from "../sync";
  import { cloneProfile, closeProfile, createProfile, deleteProfile, detectProfileDomains, openProfile, removeProfileAccount, updateProfile, type ProfileInfo } from "../api";
  import AccountDialog from "./AccountDialog.svelte";
  import AccountCooldownsPanel from "./AccountCooldownsPanel.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import { Badge } from "$lib/components/ui/badge";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as Card from "$lib/components/ui/card";
  import * as Select from "$lib/components/ui/select";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { Browser, Check, CircleNotch, Copy, FolderOpen, LockKey, MagnifyingGlass, PencilSimple, Plus, Star, Trash, UserCircle, WarningCircle, X } from "phosphor-svelte";

  let creating = $state(false); let newName = $state(""); let newMaxTabs = $state(4); let newHeadless = $state(true); let newMode = $state("dynamic"); let creatingBusy = $state(false);
  let busyIds = $state<Set<number>>(new Set());
  let editingId = $state<number | null>(null); let editMaxTabs = $state(4); let editHeadless = $state(true); let editMode = $state("dynamic"); let editNotes = $state("");
  let cloningId = $state<number | null>(null); let cloneName = $state(""); let cloneMode = $state("dynamic");
  let watchProfiles = $state<Set<string>>(new Set());
  let suggestions = $state<Record<number, string[]>>({}); let dialogProfile = $state<string | null>(null); let dialogDomain = $state("");
  let deleteTarget = $state<ProfileInfo | null>(null); let purgeChecked = $state(false); let panelError = $state("");

  const allSites = $derived(
    [...new Set([
      ...$domains.map((d) => d.host),
      ...$profiles.flatMap((p) => p.accounts.map((a) => a.host)),
      ...Object.values(suggestions).flat(),
    ])].sort((a, b) => a.localeCompare(b)),
  );

  const liveSuggestions = $derived(
    Object.fromEntries(
      Object.entries(suggestions).map(([id, hosts]) => [
        id,
        hosts.filter((h) => !$profiles.find((p) => p.id === Number(id))?.accounts.some((a) => a.host === h)),
      ]),
    ),
  );

  // Panel này chạy ở hai chỗ: tab Profiles của /integrations (trang đó có
  // bootstrap riêng) và route /profiles đứng một mình (không có bootstrap nào).
  // Trước đây nó chỉ nạp lại sau mỗi thao tác, nên mở thẳng /profiles là thấy
  // danh sách rỗng dù kho vẫn còn profile. ensureProfiles() lo cả hai đường mà
  // không gọi API hai lần. Kèm ensureDomains() để có đủ toàn bộ site cho ma
  // trận profile × site bên dưới.
  onMount(() => { ensureProfiles(); ensureDomains(); refreshCooldowns(); });

  function openAddAccount(p: ProfileInfo, host: string) { dialogProfile = p.name; dialogDomain = host; }
  function closeAccountDialog() { dialogProfile = null; dialogDomain = ""; }

  function setBusy(id: number, on: boolean) {
    const next = new Set(busyIds);
    if (on) next.add(id); else next.delete(id);
    busyIds = next;
  }
  function watchOpen(name: string) { watchProfiles = new Set(watchProfiles).add(name); }
  function watchClose(name: string) { const next = new Set(watchProfiles); next.delete(name); watchProfiles = next; }

  // Ba chế độ fetcher của Scrapling; fetcher chỉ gửi HTTP nên không mở được cửa sổ.
  function modeLabel(mode: string): string { return mode === "stealthy" ? "Stealthy" : mode === "fetcher" ? "Fetcher" : "Dynamic"; }
  function statusOf(p: ProfileInfo): { label: string; cls: string } { if (p.locked && !p.open) return { label: "Bị khoá", cls: "bg-destructive" }; if (p.open) return { label: `Đang chạy · ${p.tabs} tab`, cls: "bg-success" }; return { label: "Rảnh", cls: "bg-muted-foreground" }; }
  function fail(e: unknown) { panelError = (e as Error).message; showToast(panelError); }
  async function onCreate() { const name = newName.trim().toLowerCase(); if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) { panelError = "Tên profile chỉ gồm chữ thường, số và dấu -"; showToast(panelError); return; } creatingBusy = true; panelError = ""; try { await createProfile($apiKey, name, { scrapling_mode: newMode, max_tabs: newMaxTabs, headless: newHeadless }); showToast(`Đã tạo profile ${name} (${modeLabel(newMode)})`); newName = ""; creating = false; await refreshProfiles(); } catch (e) { fail(e); } finally { creatingBusy = false; } }
  function startEdit(p: ProfileInfo) { editingId = p.id; editMaxTabs = p.max_tabs; editHeadless = p.headless === 1; editMode = p.scrapling_mode || "dynamic"; editNotes = p.notes ?? ""; }
  // Đổi chế độ KHÔNG đụng tới thư mục Chromium của profile: session mới nhận
  // đúng `user_data_dir` cũ nên cookie/localStorage đã đăng nhập đi theo. Chỉ
  // cần nói rõ điều đó, vì "đổi chế độ" nghe như phải đăng nhập lại từ đầu.
  async function saveEdit(p: ProfileInfo) { const modeChanged = editMode !== (p.scrapling_mode || "dynamic"); const wasOpen = p.open; setBusy(p.id, true); panelError = ""; try { await updateProfile($apiKey, p.id, { scrapling_mode: editMode, max_tabs: editMaxTabs, headless: editHeadless, notes: editNotes }); editingId = null; await refreshProfiles(); if (modeChanged) showToast(`${p.name} đã chuyển sang ${modeLabel(editMode)} — vẫn dùng lại profile cũ nên toàn bộ đăng nhập giữ nguyên.` + (wasOpen ? " Cửa sổ đang chạy sẽ được mở lại bằng chế độ mới." : "")); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function makeDefault(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { await updateProfile($apiKey, p.id, { is_default: true }); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onOpen(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { const res = await openProfile($apiKey, p.id); watchOpen(p.name); showToast(res.headless ? `${p.name} đang chạy nền nên không có cửa sổ mới — bấm Đóng rồi Mở lại.` : `Đã mở cửa sổ ${p.name}. Đăng nhập rồi bấm “Dò domain”.`); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onDetect(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { const res = await detectProfileDomains($apiKey, p.id); suggestions = { ...suggestions, [p.id]: res.suggested }; if (!res.suggested.length) showToast(`${p.name}: không có domain nào chưa khai báo.`); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onClose(p: ProfileInfo) { setBusy(p.id, true); panelError = ""; try { await closeProfile($apiKey, p.name); watchClose(p.name); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  // Nhân bản = copy thư mục Chromium + account sang profile mới: giữ nguyên
  // đăng nhập mà vẫn có đường lui khi đổi chế độ Scrapling.
  function startClone(p: ProfileInfo) { cloningId = p.id; editingId = null; cloneName = `${p.name}-copy`; cloneMode = p.scrapling_mode || "dynamic"; }
  async function onClone(p: ProfileInfo) { const name = cloneName.trim().toLowerCase(); if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) { panelError = "Tên profile chỉ gồm chữ thường, số và dấu -"; showToast(panelError); return; } setBusy(p.id, true); panelError = ""; try { await cloneProfile($apiKey, p.id, name, { scrapling_mode: cloneMode }); showToast(`Đã nhân bản ${p.name} → ${name} (${modeLabel(cloneMode)})`); cloningId = null; await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  function requestDelete(p: ProfileInfo) { deleteTarget = p; purgeChecked = false; }
  async function confirmDelete() { const p = deleteTarget; if (!p) return; const purge = purgeChecked; deleteTarget = null; setBusy(p.id, true); panelError = ""; try { await deleteProfile($apiKey, p.id, purge); showToast(`Đã xóa profile ${p.name}`); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
  async function onRemoveAccount(p: ProfileInfo, accountId: number) { setBusy(p.id, true); panelError = ""; try { await removeProfileAccount($apiKey, p.id, accountId); showToast("Đã gỡ site khỏi profile"); await refreshProfiles(); } catch (e) { fail(e); } finally { setBusy(p.id, false); } }
</script>

<Card.Root class="overflow-hidden" aria-labelledby="profiles-title">
  <Card.Header class="flex-row items-center justify-between gap-4 border-b"><div class="flex items-start gap-3"><div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><FolderOpen size={19} /></div><div><Card.Title id="profiles-title">Browser profiles</Card.Title><Card.Description>Hạ tầng Chromium dùng chung đăng nhập cho nhiều domain.</Card.Description></div></div><Button variant={creating ? "ghost" : "outline"} size="sm" onclick={() => (creating = !creating)}>{#if creating}<X /> Hủy{:else}<Plus /> Profile mới{/if}</Button></Card.Header>
  <Card.Content class="grid gap-4 p-4 sm:p-6">
    {#if $cooldowns.length}
      <AccountCooldownsPanel />
    {/if}
    {#if panelError}<div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{panelError}</div>{/if}
    {#if $profilesError}<div class="flex flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive sm:flex-row sm:items-center" role="alert"><span class="flex min-w-0 flex-1 items-start gap-2"><WarningCircle class="mt-0.5 shrink-0" />Không nạp được danh sách profile: {$profilesError}</span><Button variant="outline" size="sm" disabled={$profilesLoading} onclick={() => refreshProfiles()}>Thử lại</Button></div>{/if}
    {#if $profilesMeta && !$profilesMeta.persisted}<div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Kho SQLite chưa mở nên chưa quản lý được profile. Xem log khởi động để biết vì sao.</div>
    {:else if $profilesMeta}<div class="rounded-lg border bg-muted/20 p-3 text-xs leading-5 text-muted-foreground"><p>Chế độ <strong class="font-data text-foreground">{$profilesMeta.mode}</strong> · tối đa <strong class="font-data text-foreground">{$profilesMeta.max_profiles}</strong> profile · <span class="break-all font-data">{$profilesMeta.profiles_dir}</span></p><p class="mt-1">Recipe browser có account ở đây được gán profile cho <strong class="text-foreground">từng request</strong>, bất kể chế độ trên — đổi ở Settings → API (<code class="font-data text-foreground">API_ACCOUNT_STRATEGY</code>). Chế độ <code class="font-data text-foreground">{$profilesMeta.mode}</code> chỉ còn quyết định đường chạy cho domain chưa có account nào.</p></div>{/if}

    {#if creating}<form class="grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_11rem_8rem_auto_auto] sm:items-end" onsubmit={(e) => { e.preventDefault(); onCreate(); }}><div class="grid gap-1.5"><label for="profile-name" class="text-sm font-medium">Tên profile</label><Input id="profile-name" class="font-data" placeholder="main" bind:value={newName} /></div><div class="grid gap-1.5"><label for="profile-mode" class="text-sm font-medium">Chế độ Scrapling</label><Select.Root type="single" bind:value={newMode}><Select.Trigger id="profile-mode" class="h-9 w-full">{modeLabel(newMode)}</Select.Trigger><Select.Content><Select.Item value="dynamic" label="Dynamic">Dynamic · Chromium thường</Select.Item><Select.Item value="stealthy" label="Stealthy">Stealthy · chống bot</Select.Item><Select.Item value="fetcher" label="Fetcher">Fetcher · chỉ HTTP, không mở browser</Select.Item></Select.Content></Select.Root></div><div class="grid gap-1.5"><label for="profile-tabs" class="text-sm font-medium">Tab tối đa</label><Input id="profile-tabs" type="number" min="1" max="32" bind:value={newMaxTabs} /></div><label class="flex h-9 items-center gap-2 text-sm"><Switch bind:checked={newHeadless} aria-label="Chạy profile ẩn" /> Chạy ẩn</label><Button type="submit" disabled={creatingBusy}>{#if creatingBusy}<CircleNotch class="animate-spin" />{:else}<Plus />{/if} Tạo</Button></form>{/if}

    {#if $profilesLoading && !$profiles.length}<div class="flex min-h-32 flex-col items-center justify-center gap-2 text-muted-foreground" role="status" aria-live="polite"><CircleNotch class="animate-spin" size={24} /><p class="text-sm">Đang tải profiles…</p></div>
    {:else if !$profiles.length && !$profilesError && $profilesMeta?.persisted}<div class="flex min-h-32 flex-col items-center justify-center text-center"><UserCircle class="mb-2 text-muted-foreground" size={28} /><p class="font-medium">Chưa có profile</p><p class="mt-1 text-sm text-muted-foreground">Tạo profile để gom đăng nhập nhiều domain.</p></div>{/if}

    <div class="grid gap-3">
      {#each $profiles as p (p.id)}{@const status = statusOf(p)}
        <article class="rounded-lg border bg-card p-4">
          <div class="flex flex-col gap-3 lg:flex-row lg:items-start"><div class="flex min-w-0 flex-1 items-start gap-3"><span class={`mt-1.5 size-2.5 shrink-0 rounded-full ${status.cls}`}></span><div class="min-w-0"><div class="flex flex-wrap items-center gap-2"><h3 class="font-data font-semibold">{p.name}</h3><Badge variant="outline" class="font-data text-[11px]">{modeLabel(p.scrapling_mode)}</Badge>{#if p.is_default}<Badge variant="secondary"><Star weight="fill" /> Mặc định</Badge>{/if}</div><p class="mt-1 text-xs text-muted-foreground">{p.domains} domain · {p.max_tabs} tab tối đa · {status.label}</p></div></div>
            <div class="flex flex-wrap gap-1.5"><Button variant="outline" size="sm" disabled={busyIds.has(p.id)} onclick={() => onOpen(p)}><Browser /> Mở</Button><Button variant="outline" size="sm" disabled={busyIds.has(p.id) || !p.open} onclick={() => onDetect(p)}><MagnifyingGlass /> Dò domain</Button><Button variant="outline" size="sm" disabled={busyIds.has(p.id)} onclick={() => openAddAccount(p, "")}><Plus /> Account</Button><Button variant="ghost" size="icon-sm" aria-label={`Nhân bản profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => (cloningId === p.id ? (cloningId = null) : startClone(p))}><Copy /></Button><Button variant="ghost" size="icon-sm" aria-label={`Sửa profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => (editingId === p.id ? (editingId = null) : startEdit(p))}><PencilSimple /></Button>{#if p.open}<Button variant="ghost" size="icon-sm" aria-label={`Đóng profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => onClose(p)}><X /></Button>{/if}<Button variant="destructive" size="icon-sm" aria-label={`Xóa profile ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => requestDelete(p)}><Trash /></Button></div></div>
          <div class="mt-3 grid gap-2">
            <p class="text-xs text-muted-foreground">
              {#if allSites.length}
                {p.accounts.length}/{allSites.length} site đã gắn ·
                <span class="inline-flex items-center gap-1 align-middle"><span class="size-2 rounded-full bg-success"></span> đã có</span> ·
                <span class="inline-flex items-center gap-1 align-middle"><Plus size={11} class="text-primary" /> chưa có — bấm để thêm</span>
              {:else}
                Chưa biết site nào — bấm “Dò domain” khi profile đang mở, hoặc “Account” để thêm tay.
              {/if}
            </p>
            {#if allSites.length}
              <div class="flex flex-wrap gap-1.5">
                {#each allSites as host (host)}
                  {@const matched = p.accounts.filter((a) => a.host === host)}
                  {@const suggested = liveSuggestions[p.id]?.includes(host) ?? false}
                  {#if matched.length}
                    {#each matched as account (account.id)}
                      {@const locked = isAccountLocked($cooldowns, account.id)}
                      <span class={locked
                        ? "inline-flex items-center gap-1 rounded-full border border-warning/50 bg-warning/10 px-2.5 py-0.5 text-xs font-data text-warning"
                        : "inline-flex items-center gap-1 rounded-full border border-success/40 bg-success/10 px-2.5 py-0.5 text-xs font-data text-success"} title={locked ? `${account.host} / ${account.label} — đang bị khóa limit, mở khóa ở bảng trên` : `${account.host} / ${account.label} — đã đăng nhập`}>
                        {#if locked}<LockKey size={12} class="shrink-0" />{:else}<Check size={12} class="shrink-0" />{/if}
                        <span>{account.host} / {account.label}</span>
                        {#if locked}<span class="font-sans font-medium">bị khóa</span>{/if}
                        <button class="ml-1 rounded-full p-0.5 text-success/70 transition-colors hover:bg-destructive/15 hover:text-destructive" aria-label={`Gỡ ${account.host} khỏi ${p.name}`} title={`Gỡ ${account.host} khỏi ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => onRemoveAccount(p, account.id)}>
                          <X size={12} />
                        </button>
                      </span>
                    {/each}
                  {:else}
                    <button
                      class={suggested
                        ? "inline-flex items-center gap-1 rounded-full border border-dashed border-warning/50 bg-warning/10 px-2.5 py-0.5 text-xs font-data text-warning transition-colors hover:border-warning hover:bg-warning/20 disabled:opacity-50"
                        : "inline-flex items-center gap-1 rounded-full border border-dashed border-muted-foreground/30 bg-muted/20 px-2.5 py-0.5 text-xs font-data text-muted-foreground transition-colors hover:border-primary/60 hover:bg-primary/10 hover:text-primary disabled:opacity-50"}
                      title={suggested ? `${host} đang đăng nhập trong profile này — bấm để khai báo` : `Thêm ${host} vào ${p.name}`}
                      disabled={busyIds.has(p.id)}
                      onclick={() => openAddAccount(p, host)}
                    >
                      <Plus size={12} class="shrink-0" />
                      <span>{host}</span>
                    </button>
                  {/if}
                {/each}
              </div>
            {:else if p.accounts.length}
              <div class="flex flex-wrap gap-1.5">
                {#each p.accounts as account (account.id)}
                  {@const lockedElse = isAccountLocked($cooldowns, account.id)}
                  <span class={lockedElse
                    ? "inline-flex items-center gap-1 rounded-full border border-warning/50 bg-warning/10 px-2.5 py-0.5 text-xs font-data text-warning"
                    : "inline-flex items-center gap-1 rounded-full border border-success/40 bg-success/10 px-2.5 py-0.5 text-xs font-data text-success"} title={lockedElse ? "Đang bị khóa limit" : "Đã đăng nhập"}>
                    {#if lockedElse}<LockKey size={12} class="shrink-0" />{:else}<Check size={12} class="shrink-0" />{/if}
                    <span>{account.host} / {account.label}</span>
                    {#if lockedElse}<span class="font-sans font-medium">bị khóa</span>{/if}
                    <button class="ml-1 rounded-full p-0.5 text-success/70 transition-colors hover:bg-destructive/15 hover:text-destructive" aria-label={`Gỡ ${account.host} khỏi ${p.name}`} disabled={busyIds.has(p.id)} onclick={() => onRemoveAccount(p, account.id)}>
                      <X size={12} />
                    </button>
                  </span>
                {/each}
              </div>
            {/if}
          </div>
          {#if liveSuggestions[p.id]?.length}<div class="mt-3 flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Còn đăng nhập chưa khai báo: {liveSuggestions[p.id].join(", ")} — bấm “Account” để thêm.</div>{/if}
          {#if editingId === p.id}<form class="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-[11rem_8rem_minmax(0,1fr)_auto] sm:items-end" onsubmit={(e) => { e.preventDefault(); saveEdit(p); }}><div class="grid gap-1.5"><label for="edit-mode-{p.id}" class="text-sm font-medium">Chế độ Scrapling</label><Select.Root type="single" bind:value={editMode}><Select.Trigger id="edit-mode-{p.id}" class="h-8 w-full">{modeLabel(editMode)}</Select.Trigger><Select.Content><Select.Item value="dynamic" label="Dynamic">Dynamic · Chromium thường</Select.Item><Select.Item value="stealthy" label="Stealthy">Stealthy · chống bot</Select.Item><Select.Item value="fetcher" label="Fetcher">Fetcher · chỉ HTTP, không mở browser</Select.Item></Select.Content></Select.Root></div><div class="grid gap-1.5"><label for="edit-tabs-{p.id}" class="text-sm font-medium">Tab tối đa</label><Input id="edit-tabs-{p.id}" type="number" min="1" max="32" bind:value={editMaxTabs} /></div><div class="grid gap-1.5"><label for="edit-notes-{p.id}" class="text-sm font-medium">Ghi chú</label><Input id="edit-notes-{p.id}" bind:value={editNotes} /></div><div class="flex flex-wrap items-center gap-2"><label class="flex h-8 items-center gap-2 text-sm"><Switch bind:checked={editHeadless} aria-label={`Chạy ẩn profile ${p.name}`} /> Chạy ẩn</label><Button type="submit" size="sm" disabled={busyIds.has(p.id)}>Lưu</Button>{#if !p.is_default}<Button type="button" variant="outline" size="sm" disabled={busyIds.has(p.id)} onclick={() => makeDefault(p)}><Star /> Mặc định</Button>{/if}</div>{#if editMode !== (p.scrapling_mode || "dynamic")}<p class="text-xs text-muted-foreground sm:col-span-4">Đổi sang <strong class="text-foreground">{modeLabel(editMode)}</strong> dùng lại chính thư mục profile này ({p.domains} domain đã đăng nhập) — không phải đăng nhập lại. {#if p.open}Cửa sổ đang chạy sẽ được đóng và mở lại bằng chế độ mới; nếu profile đang phục vụ request thì việc mở lại đợi tới lúc rảnh.{/if}</p>{/if}</form>{/if}
          {#if cloningId === p.id}<form class="mt-4 grid gap-3 border-t pt-4 sm:grid-cols-[minmax(0,1fr)_11rem_auto] sm:items-end" onsubmit={(e) => { e.preventDefault(); onClone(p); }}><div class="grid gap-1.5"><label for="clone-name-{p.id}" class="text-sm font-medium">Tên bản sao</label><Input id="clone-name-{p.id}" class="font-data" bind:value={cloneName} /></div><div class="grid gap-1.5"><label for="clone-mode-{p.id}" class="text-sm font-medium">Chế độ Scrapling</label><Select.Root type="single" bind:value={cloneMode}><Select.Trigger id="clone-mode-{p.id}" class="h-8 w-full">{modeLabel(cloneMode)}</Select.Trigger><Select.Content><Select.Item value="dynamic" label="Dynamic">Dynamic · Chromium thường</Select.Item><Select.Item value="stealthy" label="Stealthy">Stealthy · chống bot</Select.Item><Select.Item value="fetcher" label="Fetcher">Fetcher · chỉ HTTP, không mở browser</Select.Item></Select.Content></Select.Root></div><Button type="submit" size="sm" disabled={busyIds.has(p.id) || p.open}><Copy /> Nhân bản</Button><p class="text-xs text-muted-foreground sm:col-span-3">Copy cả thư mục Chromium ({p.domains} domain đã đăng nhập) sang profile mới — bản gốc không đổi. {#if p.open}<span class="text-warning">Đang chạy: bấm ✕ để đóng trước đã, copy lúc Chromium còn ghi sẽ ra bản sao hỏng.</span>{:else}Cache không được copy nên bản sao nhẹ hơn.{/if}</p></form>{/if}
          {#if watchProfiles.has(p.name)}<div class="mt-3 flex flex-col gap-3 rounded-lg border border-warning/20 bg-warning/5 p-3 sm:flex-row sm:items-center"><Browser class="shrink-0 text-warning" /><p class="min-w-0 flex-1 text-sm">Cửa sổ profile này đang mở — đăng nhập rồi bấm “Dò domain”.</p><Button variant="ghost" size="sm" onclick={() => watchClose(p.name)}>Ẩn nhắc này</Button></div>{/if}
        </article>
      {/each}
    </div>
  </Card.Content>
</Card.Root>

{#if dialogProfile !== null}{#key dialogProfile + "|" + dialogDomain}<AccountDialog profile={dialogProfile} domain={dialogDomain} onclose={closeAccountDialog} />{/key}{/if}
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
