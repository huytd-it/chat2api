<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { apiKey, showToast } from "../stores";
  import { refreshProfiles } from "../sync";
  import {
    checkGoogle,
    deleteGoogleIdentity,
    fetchGoogleIdentity,
    loginGoogle,
    loginSitesWithGoogle,
    saveGoogleIdentity,
    type GoogleIdentity,
    type GoogleSiteResult,
    type ProfileInfo,
  } from "../api";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Switch } from "$lib/components/ui/switch";
  import { Badge, type BadgeVariant } from "$lib/components/ui/badge";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { ArrowsClockwise, Browser, CircleNotch, GoogleLogo, PencilSimple, ShieldWarning, SignIn, Trash } from "phosphor-svelte";

  interface Props {
    profile: ProfileInfo;
    /** Mọi site đã biết (domain có recipe/account) — để chọn nhanh khi SSO. */
    sites: string[];
  }
  let { profile, sites }: Props = $props();

  let identity = $state<GoogleIdentity | null>(null);
  let waiting = $state(false);
  let busy = $state<"" | "check" | "login" | "verify" | "save" | "sites">("");
  let editing = $state(false);
  let ssoOpen = $state(false);

  let email = $state("");
  let password = $state("");
  let totpSecret = $state("");
  let recoveryEmail = $state("");
  let autoLogin = $state(true);

  let picked = $state<Set<string>>(new Set());
  let extraUrl = $state("");
  let ssoHeaded = $state(false);
  let siteResults = $state<GoogleSiteResult[]>([]);

  let poll: ReturnType<typeof setInterval> | null = null;

  const STATUS: Record<string, { label: string; variant: BadgeVariant }> = {
    signed_in: { label: "Đã đăng nhập", variant: "success" },
    signed_out: { label: "Chưa đăng nhập", variant: "outline" },
    verify_required: { label: "Cần xác minh", variant: "warning" },
    error: { label: "Lỗi", variant: "destructive" },
    unknown: { label: "Chưa kiểm tra", variant: "outline" },
  };
  const status = $derived(STATUS[identity?.status ?? "unknown"] ?? STATUS.unknown);
  // Site chưa gắn vào profile — thứ cần đăng nhập bằng Google nhất.
  const missingSites = $derived(sites.filter((h) => !profile.accounts.some((a) => a.host === h)));

  onMount(load);
  onDestroy(stopPoll);

  async function load() {
    try {
      const res = await fetchGoogleIdentity($apiKey, profile.id);
      identity = res.identity;
      waiting = res.waiting;
      if (waiting) startPoll(); else stopPoll();
    } catch {
      identity = null;
    }
  }

  // Server đang giữ cửa sổ chờ người dùng xác minh: hỏi lại tới khi xong.
  function startPoll() {
    if (poll) return;
    poll = setInterval(async () => {
      await load();
      if (!waiting) {
        showToast(identity?.status === "signed_in"
          ? `${profile.name}: đã xác minh Google xong`
          : `${profile.name}: hết thời gian chờ xác minh Google`);
        await refreshProfiles();
      }
    }, 4000);
  }
  function stopPoll() {
    if (poll) clearInterval(poll);
    poll = null;
  }

  function fail(e: unknown) { showToast((e as Error).message); }

  function startEdit() {
    email = identity?.email ?? "";
    recoveryEmail = identity?.recovery_email ?? "";
    autoLogin = identity?.auto_login ?? true;
    password = "";
    totpSecret = "";
    editing = true;
  }

  async function save() {
    busy = "save";
    try {
      const res = await saveGoogleIdentity($apiKey, profile.id, {
        email: email.trim(),
        password: password || undefined,
        totp_secret: totpSecret.trim() || undefined,
        recovery_email: recoveryEmail.trim(),
        auto_login: autoLogin,
      });
      identity = res.identity;
      editing = false;
      showToast("Đã lưu tài khoản Google");
    } catch (e) { fail(e); } finally { busy = ""; }
  }

  async function remove() {
    busy = "save";
    try {
      await deleteGoogleIdentity($apiKey, profile.id);
      identity = null;
      editing = false;
    } catch (e) { fail(e); } finally { busy = ""; }
  }

  async function check() {
    busy = "check";
    try {
      identity = (await checkGoogle($apiKey, profile.id)).identity;
      showToast(`${profile.name}: ${STATUS[identity.status]?.label ?? identity.status}`);
    } catch (e) { fail(e); } finally { busy = ""; }
  }

  async function login(headed: boolean) {
    busy = headed ? "verify" : "login";
    try {
      identity = (await loginGoogle($apiKey, profile.id, headed)).identity;
      waiting = !!identity.waiting;
      if (waiting) {
        startPoll();
        showToast("Đã mở cửa sổ profile — hoàn tất xác minh Google trong cửa sổ đó");
      } else {
        showToast(`${profile.name}: ${STATUS[identity.status]?.label ?? identity.status}`);
      }
      await refreshProfiles();
    } catch (e) { fail(e); } finally { busy = ""; }
  }

  function toggleSite(host: string, on: boolean) {
    const next = new Set(picked);
    if (on) next.add(host); else next.delete(host);
    picked = next;
  }

  function openSso() {
    ssoOpen = !ssoOpen;
    if (ssoOpen && !picked.size) picked = new Set(missingSites);
  }

  async function runSites() {
    const targets = [...picked, ...extraUrl.split(/[\s,]+/).filter(Boolean)];
    if (!targets.length) { showToast("Chọn ít nhất một web"); return; }
    busy = "sites";
    siteResults = [];
    try {
      siteResults = (await loginSitesWithGoogle($apiKey, profile.id, targets, { headed: ssoHeaded })).results;
      const ok = siteResults.filter((r) => r.ok).length;
      showToast(`Đăng nhập bằng Google: ${ok}/${siteResults.length} web thành công`);
      await refreshProfiles();
    } catch (e) { fail(e); } finally { busy = ""; }
  }

  function when(ts: number | null | undefined): string {
    if (!ts) return "chưa kiểm tra";
    const mins = Math.round((Date.now() - ts) / 60000);
    if (mins < 1) return "vừa xong";
    if (mins < 60) return `${mins} phút trước`;
    if (mins < 1440) return `${Math.round(mins / 60)} giờ trước`;
    return new Date(ts).toLocaleString();
  }

  const RESULT: Record<string, string> = {
    done: "Đã đăng nhập", already: "Có vẻ đã đăng nhập sẵn", unsure: "Chưa chắc",
    no_button: "Không thấy nút Google", verify_required: "Cần xác minh", error: "Lỗi",
  };
</script>

<section class="mt-3 grid gap-3 rounded-lg border bg-muted/10 p-3" aria-label={`Google của ${profile.name}`}>
  <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
    <div class="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-sm">
      <GoogleLogo size={16} class="shrink-0 text-muted-foreground" />
      <span class="font-medium">Google</span>
      <Badge variant={status.variant}>{waiting ? "Đang chờ xác minh…" : status.label}</Badge>
      {#if identity?.signed_in_as}<span class="truncate font-data text-xs text-muted-foreground">{identity.signed_in_as}</span>
      {:else if identity?.email}<span class="truncate font-data text-xs text-muted-foreground">{identity.email}</span>{/if}
      <span class="text-xs text-muted-foreground">· {when(identity?.checked_at)}</span>
      {#if identity?.email && identity.auto_login}<span class="text-xs text-muted-foreground">· tự đăng nhập</span>{/if}
    </div>
    <div class="flex flex-wrap gap-1.5">
      <Button variant="outline" size="sm" disabled={!!busy || waiting} onclick={check}>
        {#if busy === "check"}<CircleNotch class="animate-spin" />{:else}<ArrowsClockwise />{/if} Kiểm tra
      </Button>
      <Button variant="outline" size="sm" disabled={!!busy || waiting || !identity?.email} title={identity?.email ? "Kiểm tra rồi tự đăng nhập nếu rớt phiên (chạy ẩn)" : "Khai báo email Google trước"} onclick={() => login(false)}>
        {#if busy === "login"}<CircleNotch class="animate-spin" />{:else}<SignIn />{/if} Đăng nhập
      </Button>
      {#if identity?.status === "verify_required" || identity?.status === "error"}
        <Button variant="outline" size="sm" class="border-warning/50 text-warning" disabled={!!busy || waiting} title="Mở cửa sổ profile để tự vượt bước xác minh Google" onclick={() => login(true)}>
          {#if busy === "verify"}<CircleNotch class="animate-spin" />{:else}<ShieldWarning />{/if} Xác minh
        </Button>
      {/if}
      <Button variant="outline" size="sm" disabled={!!busy} onclick={openSso}><Browser /> Web dùng Google</Button>
      <Button variant="ghost" size="sm" disabled={!!busy} onclick={() => (editing ? (editing = false) : startEdit())}><PencilSimple /> Tài khoản</Button>
    </div>
  </div>

  {#if identity?.detail}
    <p class={`text-xs ${identity.status === "signed_in" ? "text-warning" : identity.status === "verify_required" ? "text-warning" : "text-muted-foreground"}`}>{identity.detail}</p>
  {/if}

  {#if editing}
    <form class="grid gap-3 border-t pt-3 sm:grid-cols-2" onsubmit={(e) => { e.preventDefault(); save(); }}>
      <div class="grid gap-1.5"><label for="g-email-{profile.id}" class="text-sm font-medium">Email Google</label><Input id="g-email-{profile.id}" type="email" autocomplete="off" class="font-data" placeholder="ban@gmail.com" bind:value={email} /></div>
      <div class="grid gap-1.5"><label for="g-pass-{profile.id}" class="text-sm font-medium">Mật khẩu</label><Input id="g-pass-{profile.id}" type="password" autocomplete="new-password" placeholder={identity?.has_password ? "đã lưu — bỏ trống để giữ" : "dùng khi phiên rớt"} bind:value={password} /></div>
      <div class="grid gap-1.5"><label for="g-totp-{profile.id}" class="text-sm font-medium">TOTP secret <span class="font-normal text-muted-foreground">(tuỳ chọn)</span></label><Input id="g-totp-{profile.id}" type="password" autocomplete="off" class="font-data" placeholder={identity?.has_totp ? "đã lưu — bỏ trống để giữ" : "khoá base32 của Authenticator"} bind:value={totpSecret} /></div>
      <div class="grid gap-1.5"><label for="g-rec-{profile.id}" class="text-sm font-medium">Email khôi phục <span class="font-normal text-muted-foreground">(tuỳ chọn)</span></label><Input id="g-rec-{profile.id}" type="email" autocomplete="off" class="font-data" bind:value={recoveryEmail} /></div>
      <label class="flex items-center gap-2 text-sm sm:col-span-2"><Switch bind:checked={autoLogin} aria-label="Tự kiểm tra và đăng nhập lại định kỳ" /> Tự kiểm tra &amp; đăng nhập lại định kỳ <span class="text-xs text-muted-foreground">(chu kỳ ở Settings › Google)</span></label>
      <p class="text-xs leading-5 text-muted-foreground sm:col-span-2">Mật khẩu và TOTP lưu trong DB của server và không bao giờ hiện lại. Có TOTP secret thì bước "mã Authenticator" được tự điền; các kiểu xác minh khác (SMS, bấm xác nhận trên điện thoại) cần bạn làm tay qua nút Xác minh.</p>
      <div class="flex flex-wrap gap-2 sm:col-span-2">
        <Button type="submit" size="sm" disabled={!!busy}>{#if busy === "save"}<CircleNotch class="animate-spin" />{/if} Lưu</Button>
        <Button type="button" variant="ghost" size="sm" onclick={() => (editing = false)}>Huỷ</Button>
        {#if identity?.email}<Button type="button" variant="ghost" size="sm" class="ml-auto text-destructive" disabled={!!busy} onclick={remove}><Trash /> Xoá tài khoản Google</Button>{/if}
      </div>
    </form>
  {/if}

  {#if ssoOpen}
    <div class="grid gap-3 border-t pt-3">
      <p class="text-xs text-muted-foreground">Mở từng web trong profile này, bấm "Continue with Google", chọn đúng tài khoản rồi gắn luôn site vào profile. Profile nên đăng nhập Google trước.</p>
      {#if sites.length}
        <div class="flex flex-wrap gap-x-4 gap-y-2">
          {#each sites as host (host)}
            {@const attached = profile.accounts.some((a) => a.host === host)}
            <label class="flex items-center gap-1.5 text-xs font-data">
              <Checkbox checked={picked.has(host)} onCheckedChange={(v) => toggleSite(host, !!v)} aria-label={`Đăng nhập ${host} bằng Google`} />
              <span class={attached ? "text-muted-foreground" : ""}>{host}</span>{#if attached}<span class="font-sans text-muted-foreground">(đã gắn)</span>{/if}
            </label>
          {/each}
        </div>
      {/if}
      <div class="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-end">
        <div class="grid gap-1.5"><label for="g-urls-{profile.id}" class="text-sm font-medium">URL khác</label><Input id="g-urls-{profile.id}" class="font-data" placeholder="https://chat.example.com, ..." bind:value={extraUrl} /></div>
        <label class="flex items-center gap-2 text-sm"><Switch bind:checked={ssoHeaded} aria-label="Hiện cửa sổ khi đăng nhập web" /> Hiện cửa sổ</label>
        <Button size="sm" disabled={!!busy} onclick={runSites}>{#if busy === "sites"}<CircleNotch class="animate-spin" />{:else}<GoogleLogo />{/if} Đăng nhập bằng Google</Button>
      </div>
      {#if siteResults.length}
        <ul class="grid gap-1 text-xs">
          {#each siteResults as r (r.host + r.url)}
            <li class="flex flex-wrap items-center gap-2">
              <Badge variant={r.ok ? "success" : r.status === "verify_required" || r.status === "unsure" ? "warning" : "destructive"}>{RESULT[r.status] ?? r.status}</Badge>
              <span class="font-data">{r.host}</span>
              {#if r.detail}<span class="text-muted-foreground">{r.detail}</span>{/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
</section>
