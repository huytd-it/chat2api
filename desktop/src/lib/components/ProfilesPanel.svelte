<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { apiKey, showToast } from "../stores";
  import { cooldowns, ensureProfiles, profiles, profilesError, profilesLoading, profilesMeta, refreshCooldowns, refreshProfiles, domains, ensureDomains, refreshDomains } from "../sync";
  import { closeProfile, deleteDomain, deleteProfile, detectProfileDomains, exportProfile, openProfile, removeProfileAccount, type ProfileAccount, type ProfileInfo } from "../api";
  import AccountDialog from "./AccountDialog.svelte";
  import AccountCooldownsPanel from "./AccountCooldownsPanel.svelte";
  import GoogleAuthPanel from "./GoogleAuthPanel.svelte";
  import ProfilesTable from "./profiles/ProfilesTable.svelte";
  import DomainsTable from "./profiles/DomainsTable.svelte";
  import ProfilesBulkBar from "./profiles/ProfilesBulkBar.svelte";
  import ProfilesBulkDialog, { type BulkRequest } from "./profiles/ProfilesBulkDialog.svelte";
  import ProfileDetail from "./profiles/ProfileDetail.svelte";
  import ProfileSites from "./profiles/ProfileSites.svelte";
  import ProfileCreateDialog from "./profiles/ProfileCreateDialog.svelte";
  import ProfileImportDialog from "./profiles/ProfileImportDialog.svelte";
  import ProfileCloneDialog from "./profiles/ProfileCloneDialog.svelte";
  import ProfileSettingsSheet from "./profiles/ProfileSettingsSheet.svelte";
  import { isDomainDeletable, type BulkAction, type GoogleState } from "./profiles/profile-utils";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import * as Tabs from "$lib/components/ui/tabs";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as Card from "$lib/components/ui/card";
  import * as Collapsible from "$lib/components/ui/collapsible";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { Browser, CaretDown, CircleNotch, FolderOpen, Plus, UploadSimple, UserCircle, WarningCircle, X } from "phosphor-svelte";

  // Tab nằm trên URL để link "?tab=locks" từ bảng và nút Back đều đúng.
  const TABS = ["profiles", "domains", "locks"];
  // Primitive style theo data-active nhưng Bits UI phát data-state="active".
  const TAB_ACTIVE = "px-2.5 data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-sm dark:data-[state=active]:border-input dark:data-[state=active]:bg-input/30 dark:data-[state=active]:text-foreground";
  const tab = $derived(TABS.includes(page.url.searchParams.get("tab") ?? "") ? page.url.searchParams.get("tab")! : "profiles");
  function setTab(value: string) { goto(`?tab=${value}`, { replaceState: true, noScroll: true, keepFocus: true }); }

  let checkedProfiles = $state<Set<number>>(new Set());
  let checkedDomains = $state<Set<string>>(new Set());
  let bulkRequest = $state<BulkRequest | null>(null);
  let selectedId = $state<number | null>(null);
  let detailEl = $state<HTMLElement | null>(null);
  // Hành động đang chạy theo từng profile, để nút đúng chỗ hiện spinner.
  let busyActions = $state<Record<number, string>>({});
  let googleStates = $state<Record<number, GoogleState>>({});
  // Tăng lên để GoogleAuthPanel của profile đó nạp lại trạng thái.
  let googleRev = $state<Record<number, number>>({});
  let watchProfiles = $state<Set<string>>(new Set());
  let suggestions = $state<Record<number, string[]>>({});
  let panelError = $state("");
  let creating = $state(false);
  let importing = $state(false);
  let settingsId = $state<number | null>(null);
  let cloningId = $state<number | null>(null);
  let dialogProfile = $state<string | null>(null);
  let dialogDomain = $state("");
  let deleteTarget = $state<ProfileInfo | null>(null);
  let purgeChecked = $state(false);
  let removeTarget = $state<{ profile: ProfileInfo; account: ProfileAccount } | null>(null);

  const selected = $derived($profiles.find((p) => p.id === selectedId) ?? $profiles[0] ?? null);
  const settingsProfile = $derived($profiles.find((p) => p.id === settingsId) ?? null);
  const cloningProfile = $derived($profiles.find((p) => p.id === cloningId) ?? null);

  const allSites = $derived(
    [...new Set([
      ...$domains.map((d) => d.host),
      ...$profiles.flatMap((p) => p.accounts.map((a) => a.host)),
      ...Object.values(suggestions).flat(),
    ])].sort((a, b) => a.localeCompare(b)),
  );

  const selectedSuggestions = $derived(
    selected ? (suggestions[selected.id] ?? []).filter((h) => !selected.accounts.some((a) => a.host === h)) : [],
  );

  // Panel này chạy ở route /profiles đứng một mình (không có bootstrap nào).
  // ensureProfiles() lo nạp danh sách mà không gọi API hai lần; ensureDomains()
  // cho đủ toàn bộ site để gợi ý gắn vào profile.
  onMount(() => { ensureProfiles(); ensureDomains(); refreshCooldowns(); });

  function fail(e: unknown) { panelError = (e as Error).message; showToast(panelError); }
  function bumpGoogle(id: number) { googleRev = { ...googleRev, [id]: (googleRev[id] ?? 0) + 1 }; }
  function watchOpen(name: string) { watchProfiles = new Set(watchProfiles).add(name); }
  function watchClose(name: string) { const next = new Set(watchProfiles); next.delete(name); watchProfiles = next; }

  // Selection chỉ giữ những gì còn tồn tại: profile/domain có thể biến mất sau khi refresh.
  const liveProfileIds = $derived($profiles.filter((p) => checkedProfiles.has(p.id)).map((p) => p.id));
  const liveHosts = $derived(allSites.filter((h) => checkedDomains.has(h)));
  function bulkFromProfiles(action: BulkAction) { bulkRequest = { action, profileIds: liveProfileIds }; }
  function bulkFromDomains(action: BulkAction) { bulkRequest = { action, hosts: liveHosts }; }

  let deleteHosts = $state<string[]>([]);
  let deletingDomains = $state(false);
  const deletableHosts = $derived(liveHosts.filter((h) => isDomainDeletable($domains, h)));
  // Nói rõ trước khi xoá: đây là phần không lấy lại được.
  const deleteImpact = $derived({
    attached: $profiles.flatMap((p) => p.accounts).filter((a) => deleteHosts.includes(a.host)).length,
    saved: $domains.filter((d) => deleteHosts.includes(d.host)).reduce((sum, d) => sum + d.accounts, 0),
  });

  async function confirmDeleteDomains() {
    const hosts = deleteHosts;
    deleteHosts = [];
    deletingDomains = true;
    panelError = "";
    const failures: string[] = [];
    for (const host of hosts) {
      try {
        await deleteDomain($apiKey, host);
      } catch (e) {
        failures.push(`${host}: ${(e as Error).message}`);
      }
    }
    // Xoá khỏi kết quả dò, nếu không host vẫn hiện lại trong bảng.
    const gone = new Set(hosts.filter((h) => !failures.some((f) => f.startsWith(`${h}:`))));
    suggestions = Object.fromEntries(Object.entries(suggestions).map(([id, list]) => [id, list.filter((h) => !gone.has(h))]));
    await Promise.all([refreshDomains(), refreshProfiles()]);
    deletingDomains = false;
    if (failures.length) panelError = `Không xóa được ${failures.length}/${hosts.length} domain — ${failures.join("; ")}`;
    if (gone.size) showToast(`Đã xóa ${gone.size} domain`);
  }

  function select(p: ProfileInfo) {
    selectedId = p.id;
    // Chi tiết nằm dưới bảng: đưa người dùng tới phần vừa chọn.
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    detailEl?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }

  async function refreshAndSelect(name: string) {
    await refreshProfiles();
    const found = $profiles.find((p) => p.name === name);
    if (found) selectedId = found.id;
  }

  /** Bọc một thao tác trên profile: đánh dấu bận, dọn lỗi cũ, báo lỗi mới. */
  async function run(p: ProfileInfo, action: string, fn: () => Promise<void>) {
    busyActions = { ...busyActions, [p.id]: action };
    panelError = "";
    try {
      await fn();
    } catch (e) {
      fail(e);
    } finally {
      const { [p.id]: _done, ...rest } = busyActions;
      busyActions = rest;
    }
  }

  const onOpen = (p: ProfileInfo) => run(p, "open", async () => {
    const res = await openProfile($apiKey, p.id);
    watchOpen(p.name);
    showToast(res.headless ? `${p.name} đang chạy nền nên không có cửa sổ mới — bấm Đóng rồi Mở lại.` : `Đã mở cửa sổ ${p.name}. Đăng nhập rồi bấm “Dò domain”.`);
    await refreshProfiles();
  });

  const onDetect = (p: ProfileInfo) => run(p, "detect", async () => {
    const res = await detectProfileDomains($apiKey, p.id);
    suggestions = { ...suggestions, [p.id]: res.suggested };
    if (!res.suggested.length) showToast(`${p.name}: không có domain nào chưa khai báo.`);
  });

  const onClose = (p: ProfileInfo) => run(p, "close", async () => {
    await closeProfile($apiKey, p.name);
    watchClose(p.name);
    await refreshProfiles();
  });

  // Mang profile sang máy khác. Copy thư mục Chromium không dùng được ở máy khác
  // (cookie bị mã hoá theo máy), nên server đọc đăng nhập qua chính browser rồi
  // gói thành một file JSON; máy đích nạp lại ở lần mở profile đầu tiên.
  const onExport = (p: ProfileInfo) => run(p, "export", async () => {
    const bundle = await exportProfile($apiKey, p.id);
    const url = URL.createObjectURL(new Blob([JSON.stringify(bundle)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${p.name}.chat2api-profile.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast(`Đã xuất ${p.name}: ${bundle.accounts.length} account, ${bundle.storage_state?.cookies?.length ?? 0} cookie. File chứa phiên đăng nhập — giữ kín như mật khẩu.`);
    await refreshProfiles();
  });

  function requestDelete(p: ProfileInfo) { deleteTarget = p; purgeChecked = false; }
  function confirmDelete() {
    const p = deleteTarget;
    if (!p) return;
    const purge = purgeChecked;
    deleteTarget = null;
    run(p, "delete", async () => {
      await deleteProfile($apiKey, p.id, purge);
      showToast(`Đã xóa profile ${p.name}`);
      await refreshProfiles();
    });
  }

  function confirmRemoveAccount() {
    const target = removeTarget;
    if (!target) return;
    removeTarget = null;
    run(target.profile, "remove-account", async () => {
      await removeProfileAccount($apiKey, target.profile.id, target.account.id);
      showToast("Đã gỡ site khỏi profile");
      await refreshProfiles();
    });
  }

  function openAddAccount(p: ProfileInfo, host: string) { dialogProfile = p.name; dialogDomain = host; }
  function closeAccountDialog() { dialogProfile = null; dialogDomain = ""; }
</script>

{#snippet notice(text: string)}
  <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />{text}</div>
{/snippet}

<Card.Root class="gap-0 overflow-hidden py-0" aria-labelledby="profiles-title">
  <Card.Header class="flex flex-col gap-3 border-b py-4 sm:flex-row sm:items-center sm:justify-between">
    <div class="flex items-start gap-3">
      <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><FolderOpen size={19} /></div>
      <div>
        <Card.Title id="profiles-title">Browser profiles</Card.Title>
        <Card.Description>Hạ tầng Chromium dùng chung đăng nhập cho nhiều domain.</Card.Description>
      </div>
    </div>
    <div class="flex shrink-0 flex-wrap gap-2">
      <Button variant="outline" onclick={() => (importing = true)}><UploadSimple /> Nhập từ máy khác</Button>
      <Button onclick={() => (creating = true)}><Plus /> Profile mới</Button>
    </div>
  </Card.Header>

  <Card.Content class="p-0">
    <div class="grid gap-3 p-4 empty:hidden sm:px-6">
      {#if panelError}
        <div class="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
          <WarningCircle class="mt-0.5 shrink-0" />
          <span class="min-w-0 flex-1">{panelError}</span>
          <Button variant="ghost" size="icon-xs" aria-label="Ẩn thông báo lỗi" onclick={() => (panelError = "")}><X /></Button>
        </div>
      {/if}
      {#if $profilesError}
        <div class="flex flex-col gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive sm:flex-row sm:items-center" role="alert">
          <span class="flex min-w-0 flex-1 items-start gap-2"><WarningCircle class="mt-0.5 shrink-0" />Không nạp được danh sách profile: {$profilesError}</span>
          <Button variant="outline" size="sm" disabled={$profilesLoading} onclick={() => refreshProfiles()}>Thử lại</Button>
        </div>
      {/if}
      {#if $profilesMeta && !$profilesMeta.persisted}
        {@render notice("Kho SQLite chưa mở nên chưa quản lý được profile. Xem log khởi động để biết vì sao.")}
      {:else if $profilesMeta}
        <Collapsible.Root class="text-xs leading-5 text-muted-foreground">
          <Collapsible.Trigger class="group flex w-full items-center gap-1.5 rounded-md text-left hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
            <CaretDown size={13} class="shrink-0 transition-transform group-data-[state=closed]:-rotate-90" />
            <span class="min-w-0">Chế độ <strong class="font-data text-foreground">{$profilesMeta.mode}</strong> · {$profiles.length}/<span class="font-data">{$profilesMeta.max_profiles}</span> profile · <span class="break-all font-data">{$profilesMeta.profiles_dir}</span></span>
          </Collapsible.Trigger>
          <Collapsible.Content>
            <p class="mt-1 pl-5">Recipe browser có account ở đây được gán profile cho <strong class="text-foreground">từng request</strong>, bất kể chế độ trên — đổi ở Settings → API (<code class="font-data text-foreground">API_ACCOUNT_STRATEGY</code>). Chế độ <code class="font-data text-foreground">{$profilesMeta.mode}</code> chỉ còn quyết định đường chạy cho domain chưa có account nào.</p>
          </Collapsible.Content>
        </Collapsible.Root>
      {/if}
    </div>

    <!-- Tabs.Content giữ nội dung trong DOM khi ẩn: GoogleAuthPanel vẫn poll được
         lúc người dùng đang ở tab khác. -->
    <Tabs.Root value={tab} onValueChange={setTab}>
      <div class="overflow-x-auto border-t px-4 py-2 sm:px-6">
        <Tabs.List>
          <Tabs.Trigger class={TAB_ACTIVE} value="profiles">Profiles</Tabs.Trigger>
          <Tabs.Trigger class={TAB_ACTIVE} value="domains">Domain</Tabs.Trigger>
          <Tabs.Trigger class={TAB_ACTIVE} value="locks">Account bị khóa{#if $cooldowns.length}<Badge variant="warning" class="ml-1">{$cooldowns.length}</Badge>{/if}</Tabs.Trigger>
        </Tabs.List>
      </div>

      <Tabs.Content value="profiles">
    {#if $profilesLoading && !$profiles.length}
      <div class="flex min-h-48 flex-col items-center justify-center gap-2 border-t text-muted-foreground" role="status" aria-live="polite"><CircleNotch class="animate-spin" size={24} /><p class="text-sm">Đang tải profiles…</p></div>
    {:else if !$profiles.length && !$profilesError && $profilesMeta?.persisted}
      <div class="flex min-h-48 flex-col items-center justify-center border-t p-6 text-center">
        <UserCircle class="mb-2 text-muted-foreground" size={28} />
        <p class="font-medium">Chưa có profile</p>
        <p class="mt-1 text-sm text-muted-foreground">Tạo profile để gom đăng nhập nhiều domain.</p>
        <Button class="mt-4" onclick={() => (creating = true)}><Plus /> Tạo profile đầu tiên</Button>
      </div>
    {/if}

    {#if selected}
      <div class="grid">
        <ProfilesBulkBar count={liveProfileIds.length} noun="profile" target="domain" onaction={bulkFromProfiles} onclear={() => (checkedProfiles = new Set())} />
        <ProfilesTable profiles={$profiles} activeId={selected.id} bind:checked={checkedProfiles} google={googleStates} onselect={select} />

        <div class="grid min-w-0 scroll-mt-2 content-start gap-5 border-t p-4 sm:p-6" bind:this={detailEl}>
          <ProfileDetail
            profile={selected}
            busyAction={busyActions[selected.id] ?? ""}
            onopen={() => onOpen(selected)}
            onclose={() => onClose(selected)}
            ondetect={() => onDetect(selected)}
            onaddaccount={() => openAddAccount(selected, "")}
            onsettings={() => (settingsId = selected.id)}
            onexport={() => onExport(selected)}
            onclone={() => (cloningId = selected.id)}
            ondelete={() => requestDelete(selected)}
          />
          {#if watchProfiles.has(selected.name) && selected.open}
            <div class="flex flex-col gap-3 rounded-lg border border-warning/20 bg-warning/5 p-3 sm:flex-row sm:items-center">
              <Browser class="shrink-0 text-warning" />
              <p class="min-w-0 flex-1 text-sm">Cửa sổ profile này đang mở — đăng nhập rồi bấm “Dò domain”.</p>
              <Button variant="ghost" size="sm" onclick={() => watchClose(selected.name)}>Ẩn nhắc này</Button>
            </div>
          {/if}
          <ProfileSites
            profile={selected}
            sites={allSites}
            suggested={selectedSuggestions}
            busy={!!busyActions[selected.id]}
            onadd={(host) => openAddAccount(selected, host)}
            onremove={(account) => (removeTarget = { profile: selected, account })}
          />
          <!-- Mount cho mọi profile rồi ẩn: panel tự giữ vòng poll chờ xác minh và
               báo trạng thái cho danh sách, đổi profile không được làm mất các việc đó. -->
          {#each $profiles as p (p.id)}
            <div hidden={p.id !== selected.id}>
              {#key googleRev[p.id] ?? 0}
                <GoogleAuthPanel profile={p} sites={allSites} onstatus={(state) => (googleStates = { ...googleStates, [p.id]: state })} />
              {/key}
            </div>
          {/each}
        </div>
      </div>
    {/if}
      </Tabs.Content>

      <Tabs.Content value="domains">
        <ProfilesBulkBar count={liveHosts.length} noun="domain" target="profile" onaction={bulkFromDomains} onclear={() => (checkedDomains = new Set())} deletable={deletableHosts.length} ondelete={() => (deleteHosts = deletableHosts)} />
        <DomainsTable hosts={allSites} profiles={$profiles} bind:checked={checkedDomains} ondelete={(host) => (deleteHosts = [host])} />
      </Tabs.Content>

      <Tabs.Content value="locks" class="border-t p-4 sm:p-6">
        <AccountCooldownsPanel />
      </Tabs.Content>
    </Tabs.Root>
  </Card.Content>
</Card.Root>

<ProfileCreateDialog bind:open={creating} oncreated={refreshAndSelect} ongooglechanged={bumpGoogle} />
<ProfileImportDialog bind:open={importing} onimported={async (name) => { await Promise.all([refreshAndSelect(name), refreshDomains()]); }} />
<ProfileCloneDialog
  profile={cloningProfile}
  closing={cloningProfile ? busyActions[cloningProfile.id] === "close" : false}
  oncancel={() => (cloningId = null)}
  oncloseprofile={onClose}
  oncloned={refreshAndSelect}
/>
<ProfileSettingsSheet profile={settingsProfile} oncancel={() => (settingsId = null)} />
<ProfilesBulkDialog
  request={bulkRequest}
  profiles={$profiles}
  sites={allSites}
  google={googleStates}
  onclose={() => (bulkRequest = null)}
  ongooglechanged={(ids) => ids.forEach(bumpGoogle)}
/>

{#if dialogProfile !== null}{#key dialogProfile + "|" + dialogDomain}<AccountDialog profile={dialogProfile} domain={dialogDomain} onclose={closeAccountDialog} />{/key}{/if}

<AlertDialog.Root open={deleteHosts.length > 0} onOpenChange={(open) => { if (!open) deleteHosts = []; }}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>Xóa {deleteHosts.length} domain?</AlertDialog.Title>
      <AlertDialog.Description>
        <span class="block break-all font-data">{deleteHosts.join(", ")}</span>
        <span class="mt-2 block">Sẽ gỡ {deleteImpact.attached} account khỏi các profile và xóa vĩnh viễn {deleteImpact.saved} file đăng nhập đã lưu. Cookie trong thư mục Chromium của profile vẫn còn. Không hoàn tác được.</span>
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>Hủy</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={deletingDomains} onclick={confirmDeleteDomains}>Xóa domain</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

<AlertDialog.Root open={removeTarget !== null} onOpenChange={(open) => { if (!open) removeTarget = null; }}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>Gỡ {removeTarget?.account.host} khỏi {removeTarget?.profile.name}?</AlertDialog.Title>
      <AlertDialog.Description>Account <span class="font-data">{removeTarget?.account.label}</span> không còn được dùng để phục vụ site này qua profile đó. Bạn có thể khai báo lại sau.</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>Hủy</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmRemoveAccount}>Gỡ site</AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

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
