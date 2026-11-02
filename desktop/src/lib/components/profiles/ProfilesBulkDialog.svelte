<script lang="ts">
  import { untrack } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { addProfileAccount, loginSitesWithGoogle, removeDomainProfile, type ProfileInfo } from "$lib/api";
  import { refreshDomains, refreshProfiles, refreshRecipes } from "$lib/sync";
  import { Badge } from "$lib/components/ui/badge";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import * as Dialog from "$lib/components/ui/dialog";
  import { CircleNotch, Stop, WarningCircle } from "phosphor-svelte";
  import { GOOGLE_SITE_RESULT, PROFILE_NAME_RE, normalizeHost, type BulkAction, type GoogleState } from "./profile-utils";

  export interface BulkRequest {
    action: BulkAction;
    /** Bên đã tick trong bảng; bên còn lại chọn trong dialog. */
    profileIds?: number[];
    hosts?: string[];
  }

  interface Props {
    request: BulkRequest | null;
    profiles: ProfileInfo[];
    sites: string[];
    google: Record<number, GoogleState>;
    onclose: () => void;
    /** Xong một lượt đăng nhập Google: panel nạp lại khối Google của các profile này. */
    ongooglechanged: (ids: number[]) => void;
  }
  let { request, profiles, sites, google, onclose, ongooglechanged }: Props = $props();

  interface ResultRow { key: string; profile: string; host: string; ok: boolean; label: string; detail: string; warn?: boolean }

  let pickedHosts = $state<Set<string>>(new Set());
  let pickedProfiles = $state<Set<number>>(new Set());
  let extra = $state(""); let label = $state("main"); let headed = $state(false); let labelError = $state("");
  let running = $state(false); let finished = $state(false); let stopRequested = $state(false);
  let results = $state<ResultRow[]>([]); let doneCount = $state(0); let runTotal = $state(0);

  $effect(() => {
    if (!request) return;
    untrack(() => {
      pickedHosts = new Set(); pickedProfiles = new Set();
      extra = ""; label = "main"; headed = false; labelError = "";
      running = false; finished = false; stopRequested = false;
      results = []; doneCount = 0; runTotal = 0;
    });
  });

  const action = $derived(request?.action ?? "attach");
  const pickHosts = $derived(!!request?.profileIds);
  const extraHosts = $derived(extra.split(/[\s,]+/).map(normalizeHost).filter(Boolean));
  const chosenProfiles = $derived(
    pickHosts
      ? profiles.filter((p) => request?.profileIds?.includes(p.id))
      : profiles.filter((p) => pickedProfiles.has(p.id)),
  );
  const chosenHosts = $derived(pickHosts ? [...new Set([...pickedHosts, ...extraHosts])] : (request?.hosts ?? []));

  const TEXT: Record<BulkAction, { title: string; submit: string }> = {
    attach: { title: "Gắn domain vào profile", submit: "Gắn" },
    detach: { title: "Gỡ domain khỏi profile", submit: "Gỡ" },
    google: { title: "Đăng nhập domain bằng Google", submit: "Đăng nhập" },
  };

  /** Lý do bỏ qua một cặp; rỗng = sẽ chạy. */
  function skipReason(p: ProfileInfo, host: string): string {
    const isAttached = p.accounts.some((a) => a.host === host);
    if (action === "attach" && isAttached) return "đã gắn";
    if (action === "detach" && !isAttached) return "chưa gắn";
    if (action === "google" && p.scrapling_mode === "fetcher") return "profile Fetcher không mở được browser";
    return "";
  }

  const pairs = $derived(chosenProfiles.flatMap((profile) => chosenHosts.map((host) => ({ profile, host, skip: skipReason(profile, host) }))));
  const runnable = $derived(pairs.filter((x) => !x.skip));
  const skipped = $derived(pairs.length - runnable.length);
  const skipReasons = $derived([...new Set(pairs.map((x) => x.skip).filter(Boolean))].join(", "));
  const notSignedIn = $derived(
    action === "google"
      ? [...new Set(runnable.map((x) => x.profile))].filter((p) => google[p.id]?.identity?.status !== "signed_in").map((p) => p.name)
      : [],
  );
  const okCount = $derived(results.filter((r) => r.ok).length);
  const canClose = $derived(!running);

  function toggleHost(host: string, on: boolean) { const next = new Set(pickedHosts); if (on) next.add(host); else next.delete(host); pickedHosts = next; }
  function toggleProfile(id: number, on: boolean) { const next = new Set(pickedProfiles); if (on) next.add(id); else next.delete(id); pickedProfiles = next; }

  function push(row: Omit<ResultRow, "key">) { results = [...results, { ...row, key: `${results.length}` }]; }

  /** Google: gom theo profile, vì mỗi profile chỉ chạy tuần tự trong một cửa sổ. */
  async function runGoogle(list: typeof runnable) {
    const byProfile = new Map<number, { profile: ProfileInfo; hosts: string[] }>();
    for (const { profile, host } of list) {
      const group = byProfile.get(profile.id) ?? { profile, hosts: [] };
      group.hosts.push(host);
      byProfile.set(profile.id, group);
    }
    for (const { profile, hosts } of byProfile.values()) {
      if (stopRequested) return;
      try {
        const res = await loginSitesWithGoogle($apiKey, profile.id, hosts, { headed });
        for (const r of res.results) push({ profile: profile.name, host: r.host, ok: r.ok, warn: r.status === "verify_required" || r.status === "unsure", label: GOOGLE_SITE_RESULT[r.status] ?? r.status, detail: r.detail });
      } catch (e) {
        for (const host of hosts) push({ profile: profile.name, host, ok: false, label: "Lỗi", detail: (e as Error).message });
      }
      doneCount += hosts.length;
    }
  }

  async function runPairs(list: typeof runnable, cleanLabel: string) {
    for (const { profile, host } of list) {
      if (stopRequested) return;
      try {
        if (action === "attach") await addProfileAccount($apiKey, profile.id, host, cleanLabel);
        else await removeDomainProfile($apiKey, host, profile.id);
        push({ profile: profile.name, host, ok: true, label: action === "attach" ? "Đã gắn" : "Đã gỡ", detail: "" });
      } catch (e) {
        push({ profile: profile.name, host, ok: false, label: "Lỗi", detail: (e as Error).message });
      }
      doneCount += 1;
    }
  }

  async function submit() {
    const cleanLabel = label.trim() || "main";
    if (action === "attach" && !PROFILE_NAME_RE.test(cleanLabel)) { labelError = "Nhãn chỉ gồm chữ thường, số và dấu -"; return; }
    labelError = "";
    // Chốt danh sách: refresh giữa chừng không được đổi những gì đã xác nhận.
    const list = [...runnable];
    const googleIds = [...new Set(list.map((x) => x.profile.id))];
    const runAction = action;
    running = true; stopRequested = false; results = []; doneCount = 0; runTotal = list.length;
    try {
      if (runAction === "google") await runGoogle(list); else await runPairs(list, cleanLabel);
    } finally {
      running = false; finished = true;
    }
    await Promise.all([refreshProfiles(), refreshDomains(), refreshRecipes()]).catch((e) => showToast((e as Error).message));
    if (runAction === "google") ongooglechanged(googleIds);
  }
</script>

<Dialog.Root open={request !== null} onOpenChange={(v) => { if (!v && canClose) onclose(); }}>
  <Dialog.Content class="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-xl" showCloseButton={canClose}>
    <Dialog.Header>
      <Dialog.Title>{TEXT[action].title}</Dialog.Title>
      <Dialog.Description>
        {#if pickHosts}Áp dụng cho {chosenProfiles.length} profile: <span class="font-data">{chosenProfiles.map((p) => p.name).join(", ")}</span>
        {:else}Áp dụng cho {chosenHosts.length} domain: <span class="font-data">{chosenHosts.join(", ")}</span>{/if}
      </Dialog.Description>
    </Dialog.Header>

    {#if !running && !finished}
      <div class="grid gap-4">
        {#if pickHosts}
          <fieldset class="grid gap-2">
            <legend class="mb-2 text-sm font-medium">Chọn domain</legend>
            {#if sites.length}
              <div class="grid max-h-52 gap-2 overflow-y-auto rounded-lg border p-3 sm:grid-cols-2">
                {#each sites as host (host)}
                  <label class="flex min-w-0 items-center gap-2 font-data text-xs"><Checkbox checked={pickedHosts.has(host)} onCheckedChange={(v) => toggleHost(host, !!v)} aria-label={host} /><span class="break-all">{host}</span></label>
                {/each}
              </div>
            {/if}
            <label for="bulk-extra" class="mt-1 text-xs text-muted-foreground">Domain khác, cách nhau bằng dấu phẩy</label>
            <Input id="bulk-extra" class="font-data" placeholder="chat.example.com" bind:value={extra} />
          </fieldset>
        {:else}
          <fieldset class="grid gap-2">
            <legend class="mb-2 text-sm font-medium">Chọn profile</legend>
            <div class="grid max-h-52 gap-2 overflow-y-auto rounded-lg border p-3 sm:grid-cols-2">
              {#each profiles as p (p.id)}
                <label class="flex min-w-0 items-center gap-2 font-data text-xs"><Checkbox checked={pickedProfiles.has(p.id)} onCheckedChange={(v) => toggleProfile(p.id, !!v)} aria-label={p.name} /><span class="break-all">{p.name}</span></label>
              {/each}
            </div>
          </fieldset>
        {/if}

        {#if action === "attach"}
          <div class="grid gap-1.5">
            <label for="bulk-label" class="text-sm font-medium">Nhãn account</label>
            <Input id="bulk-label" class="max-w-48 font-data" aria-invalid={!!labelError} bind:value={label} />
            {#if labelError}<p class="text-xs text-destructive">{labelError}</p>{/if}
          </div>
          <p class="text-xs leading-5 text-muted-foreground">Gắn chỉ khai báo quan hệ profile–domain, không đăng nhập. Profile chưa đăng nhập site đó thì phải đăng nhập sau, hoặc dùng Đăng nhập Google.</p>
        {:else if action === "detach"}
          <p class="text-xs leading-5 text-muted-foreground">Gỡ mọi account của domain khỏi từng profile đã chọn. Server từ chối cặp nào làm recipe mất account cuối cùng và báo lý do trong kết quả.</p>
        {:else}
          <label class="flex items-center gap-2 text-sm"><Switch bind:checked={headed} aria-label="Hiện cửa sổ khi đăng nhập" /> Hiện cửa sổ</label>
          <p class="text-xs leading-5 text-muted-foreground">Chạy lần lượt từng profile: mở web, bấm “Continue with Google” rồi gắn site vào profile. Có thể mất vài phút.</p>
          {#if notSignedIn.length}
            <p class="flex items-start gap-2 text-xs leading-5 text-warning"><WarningCircle size={14} class="mt-0.5 shrink-0" /><span>Chưa ghi nhận đăng nhập Google: <span class="font-data">{notSignedIn.join(", ")}</span>. Các profile này có thể không đăng nhập được web.</span></p>
          {/if}
        {/if}

        <p class="text-sm" aria-live="polite">
          {#if pairs.length}
            Sẽ xử lý <strong class="font-medium">{runnable.length}</strong> cặp profile–domain{#if skipped}, bỏ qua {skipped} ({skipReasons}){/if}.
          {:else}
            <span class="text-muted-foreground">Chọn ít nhất một {pickHosts ? "domain" : "profile"}.</span>
          {/if}
        </p>
      </div>
    {:else}
      <div class="grid gap-3">
        <p class="flex items-center gap-2 text-sm" role="status" aria-live="polite">
          {#if running}<CircleNotch class="animate-spin" /> Đã xong {doneCount}/{runTotal}{#if stopRequested} · dừng sau cặp đang chạy{/if}
          {:else}Thành công {okCount}/{results.length}{#if results.length < runTotal} · {runTotal - results.length} cặp chưa chạy vì đã dừng{/if}{/if}
        </p>
        {#if results.length}
          <ul class="max-h-72 divide-y overflow-y-auto rounded-lg border">
            {#each results as r (r.key)}
              <li class="grid gap-1 px-3 py-2 text-xs">
                <span class="flex flex-wrap items-center gap-2">
                  <Badge variant={r.ok ? "success" : r.warn ? "warning" : "destructive"}>{r.label}</Badge>
                  <span class="break-all font-data">{r.profile} · {r.host}</span>
                </span>
                {#if r.detail}<span class="text-muted-foreground">{r.detail}</span>{/if}
              </li>
            {/each}
          </ul>
        {/if}
      </div>
    {/if}

    <Dialog.Footer>
      {#if running}
        <Button variant="outline" disabled={stopRequested} onclick={() => (stopRequested = true)}><Stop /> Dừng</Button>
      {:else if finished}
        <Button onclick={onclose}>Xong</Button>
      {:else}
        <Button variant="ghost" onclick={onclose}>Hủy</Button>
        <Button variant={action === "detach" ? "destructive" : "default"} disabled={!runnable.length} onclick={submit}>{TEXT[action].submit} {runnable.length || ""}</Button>
      {/if}
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
