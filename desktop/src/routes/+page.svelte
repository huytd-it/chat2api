<script lang="ts">
  import { onMount } from "svelte";
  import { serverStatus } from "$lib/stores";
  import {
    overview,
    recipes,
    accounts,
    refreshOverview,
    refreshRecipes,
    refreshAccounts,
    refreshModels,
  } from "$lib/sync";
  import type { RequestRoute, SessionDistribution } from "$lib/api";
  import PageShell from "$lib/components/PageShell.svelte";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import ArrowClockwiseIcon from "phosphor-svelte/lib/ArrowClockwiseIcon";
  import ArrowRightIcon from "phosphor-svelte/lib/ArrowRightIcon";
  import WarningIcon from "phosphor-svelte/lib/WarningIcon";
  import CheckCircleIcon from "phosphor-svelte/lib/CheckCircleIcon";
  import CircleNotchIcon from "phosphor-svelte/lib/CircleNotchIcon";
  import PlugsConnectedIcon from "phosphor-svelte/lib/PlugsConnectedIcon";
  import BrowserIcon from "phosphor-svelte/lib/BrowserIcon";
  import UserCircleIcon from "phosphor-svelte/lib/UserCircleIcon";

  let refreshing = $state(false);
  let loaded = $state(false);
  let now = $state(Date.now());
  let documentVisible = $state(true);

  onMount(() => {
    let active = true;
    const onVisibilityChange = () => {
      documentVisible = document.visibilityState === "visible";
    };
    const poll = async () => {
      if (!documentVisible) return;
      await refreshOverview();
      if (active) {
        loaded = true;
        now = Date.now();
      }
    };
    onVisibilityChange();
    document.addEventListener("visibilitychange", onVisibilityChange);
    poll();
    const timer = window.setInterval(poll, 1500);
    return () => {
      active = false;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.clearInterval(timer);
    };
  });

  async function refreshAll() {
    refreshing = true;
    try {
      await Promise.all([refreshOverview(), refreshRecipes(), refreshAccounts(), refreshModels()]);
      now = Date.now();
    } finally {
      refreshing = false;
    }
  }

  const unhealthy = $derived($overview?.unhealthy ?? []);
  const routes = $derived($overview?.request_routes ?? []);
  const activeRoutes = $derived(routes.filter((route) => route.status === "running"));
  const recentRoutes = $derived(routes.filter((route) => route.status !== "running").slice(0, 8));
  const distribution = $derived($overview?.session_distribution ?? []);
  const distributionTotal = $derived(distribution.reduce((sum, item) => sum + item.sessions, 0));
  const distributionMax = $derived(Math.max(1, ...distribution.map((item) => item.sessions)));
  const domainsWithoutAccounts = $derived(
    $accounts.filter((domain) => domain.recipes.length > 0 && domain.accounts.length === 0),
  );
  const healthy = $derived(
    $serverStatus.state !== "error" && !unhealthy.length && !domainsWithoutAccounts.length,
  );
  const stats = $derived([
    { label: "Đang xử lý", value: activeRoutes.length, detail: "request đang giữ slot" },
    { label: "60 giây qua", value: $overview?.requests_last_minute ?? 0, detail: "request được tiếp nhận" },
    { label: "Browser context", value: $overview?.contexts ?? 0, detail: `${$overview?.open_browsers.length ?? 0} recipe đang mở` },
    { label: "Đích sẵn sàng", value: $overview?.accounts ?? 0, detail: `${$overview?.domains ?? 0} domain` },
  ]);

  function routeTarget(route: RequestRoute): string {
    if (route.profile_name && route.account_label) return `${route.profile_name} / ${route.account_label}`;
    if (route.account_label) return route.account_label;
    return "Ẩn danh / direct";
  }

  function distributionTarget(item: SessionDistribution): string {
    if (item.profile_name && item.account_label) return `${item.profile_name} / ${item.account_label}`;
    if (item.account_label) return item.account_label;
    return "Ẩn danh / direct";
  }

  function branchShare(item: SessionDistribution): number {
    return distributionTotal ? Math.round((item.sessions / distributionTotal) * 100) : 0;
  }

  function branchStyle(item: SessionDistribution, index: number): string {
    const strength = item.sessions / distributionMax;
    const duration = Math.max(1.2, 3.4 - strength * 1.8);
    return `--branch-strength:${strength};--flow-duration:${duration}s;--flow-delay:-${index * 0.41}s`;
  }

  function elapsed(route: RequestRoute): string {
    const duration = route.duration_ms ?? Math.max(0, now - route.started_at);
    if (duration < 1000) return `${duration} ms`;
    return `${(duration / 1000).toFixed(duration < 10000 ? 1 : 0)} s`;
  }

  function age(timestamp: number): string {
    const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
    if (seconds < 5) return "vừa xong";
    if (seconds < 60) return `${seconds} giây trước`;
    const minutes = Math.floor(seconds / 60);
    return minutes < 60 ? `${minutes} phút trước` : `${Math.floor(minutes / 60)} giờ trước`;
  }

  function statusLabel(status: RequestRoute["status"]): string {
    return ({
      running: "Đang chạy",
      ok: "Hoàn tất",
      error: "Lỗi",
      timeout: "Quá hạn",
      trial_limit: "Hết lượt",
      cancelled: "Đã huỷ",
    } as Record<RequestRoute["status"], string>)[status] ?? status;
  }

  function statusVariant(status: RequestRoute["status"]): "success" | "warning" | "destructive" | "outline" {
    if (status === "ok") return "success";
    if (status === "running") return "warning";
    if (["error", "timeout", "trial_limit"].includes(status)) return "destructive";
    return "outline";
  }
</script>

<PageShell
  title="Request routing"
  description="Theo dõi từng request từ client, qua model và recipe, tới đúng profile, account và upstream đang phục vụ."
  width="wide"
>
  {#snippet actions()}
    <div class="flex items-center gap-3">
      <span class="flex items-center gap-2 text-xs text-muted-foreground" aria-live="polite">
        <span class="size-1.5 rounded-full bg-success motion-safe:animate-pulse"></span>
        Cập nhật mỗi 1.5 giây
      </span>
      <Button variant="outline" size="sm" onclick={refreshAll} disabled={refreshing}>
        <ArrowClockwiseIcon size={16} class={refreshing ? "animate-spin" : ""} />
        Làm mới
      </Button>
    </div>
  {/snippet}

  {#if !loaded}
    <Skeleton class="h-14 w-full rounded-lg" />
  {:else if $serverStatus.state === "error"}
    <Alert.Root variant="destructive">
      <WarningIcon size={16} />
      <Alert.Title>Mất kết nối tới server</Alert.Title>
      <Alert.Description>Kiểm tra sidecar còn chạy không, rồi thử làm mới.</Alert.Description>
    </Alert.Root>
  {:else if !healthy}
    <Alert.Root class="border-warning/40 bg-warning/10 text-warning">
      <WarningIcon size={16} />
      <Alert.Title>Luồng phân phối có điểm cần chú ý</Alert.Title>
      <Alert.Description class="text-warning/90">
        {unhealthy.length ? `${unhealthy.length} recipe lỗi liên tiếp. ` : ""}
        {domainsWithoutAccounts.length ? `${domainsWithoutAccounts.length} domain chưa có account.` : ""}
        <a class="font-medium underline underline-offset-2" href="/integrations">Mở Integrations</a>
      </Alert.Description>
    </Alert.Root>
  {/if}

  <section class="border-y border-foreground/20" aria-label="Nhịp phân phối hiện tại">
    <div class="grid grid-cols-2 lg:grid-cols-4">
      {#each stats as stat (stat.label)}
        <div class="min-h-24 border-border px-4 py-4 even:border-l max-lg:border-b lg:border-r lg:last:border-r-0">
          <div class="text-xs font-medium text-muted-foreground">{stat.label}</div>
          {#if !loaded}
            <Skeleton class="mt-3 h-7 w-12 rounded-sm" />
          {:else}
            <div class="display-face mt-2 text-3xl font-semibold leading-none tabular-nums">{stat.value}</div>
          {/if}
          <div class="mt-2 text-[11px] text-muted-foreground">{stat.detail}</div>
        </div>
      {/each}
    </div>
  </section>

  <section aria-labelledby="distribution-title" class="distribution-section">
    <div class="flex flex-wrap items-end justify-between gap-3 border-b-2 border-foreground pb-3">
      <div>
        <h3 id="distribution-title" class="display-face text-2xl font-semibold leading-none">Phân phối sessions</h3>
        <p class="mt-2 text-xs text-muted-foreground">Dựa trên 100 session chưa lưu trữ gần nhất. Mỗi session được tính một lần theo đích đã phục vụ nó.</p>
      </div>
      <div class="text-right">
        <strong class="display-face block text-3xl font-semibold leading-none tabular-nums">{distributionTotal}</strong>
        <span class="text-[10px] text-muted-foreground">SESSION GẦN ĐÂY</span>
      </div>
    </div>

    {#if distribution.length}
      <div class:flow-paused={!documentVisible} class="distribution-diagram" aria-live="polite">
        <div class="source-stage">
          <div class="source-node">
            <span class="source-pulse" aria-hidden="true"></span>
            <PlugsConnectedIcon size={20} />
            <span><small>SESSIONS</small><strong>{distributionTotal}</strong><em>session chưa lưu trữ</em></span>
          </div>
          <div class="source-trunk" aria-hidden="true"><span></span></div>
        </div>

        <div class="branch-stage">
          {#each distribution as item, index (`${item.recipe_slug}-${item.profile_name}-${item.account_label}-${item.domain}`)}
            <div class="flow-branch" style={branchStyle(item, index)}>
              <div class="flow-rail" aria-hidden="true">
                <span class="flow-particle particle-a"></span>
                <span class="flow-particle particle-b"></span>
                {#if item.sessions > 2}<span class="flow-particle particle-c"></span>{/if}
              </div>
              <div class="destination-node">
                <div class="destination-main">
                  <span class="destination-rank font-data">{String(index + 1).padStart(2, "0")}</span>
                  <span class="min-w-0">
                    <small>RECIPE / TARGET</small>
                    <strong>{item.recipe_slug}</strong>
                    <em>{distributionTarget(item)}{item.domain ? ` · ${item.domain}` : ""}</em>
                  </span>
                </div>
                <div class="destination-count">
                  <strong class="display-face tabular-nums">{item.sessions}</strong>
                  <span>{branchShare(item)}%</span>
                </div>
                <div class="destination-meter" aria-hidden="true"><span style={`transform:scaleX(${item.sessions / distributionMax})`}></span></div>
                {#if item.active || item.errors}
                  <div class="destination-state">
                    {#if item.active}<span class="text-warning">{item.active} đang chạy</span>{/if}
                    {#if item.errors}<span class="text-destructive">{item.errors} lỗi</span>{/if}
                  </div>
                {/if}
              </div>
            </div>
          {/each}
        </div>
      </div>
    {:else}
      <div class="grid min-h-52 place-items-center border-b border-dashed border-border px-6 py-10 text-center">
        <div>
          <div class="mx-auto flex size-10 items-center justify-center rounded-full border border-border bg-card text-primary">
            <PlugsConnectedIcon size={20} />
          </div>
          <p class="mt-3 text-sm font-medium">Chưa có session để phân phối</p>
          <p class="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">Diagram sẽ tự tách nhánh khi session đầu tiên được ghi nhận.</p>
        </div>
      </div>
    {/if}
  </section>

  <section aria-labelledby="live-routing-title">
    <div class="flex flex-wrap items-end justify-between gap-3 border-b-2 border-foreground pb-3">
      <div>
        <h3 id="live-routing-title" class="display-face text-2xl font-semibold leading-none">Luồng đang chạy</h3>
        <p class="mt-2 text-xs text-muted-foreground">Mỗi hàng là một quyết định routing đã được server chốt trước khi stream bắt đầu.</p>
      </div>
      <Badge variant={activeRoutes.length ? "warning" : "outline"} class="font-data">
        {activeRoutes.length} ACTIVE
      </Badge>
    </div>

    {#if activeRoutes.length}
      <div class="divide-y divide-border" aria-live="polite">
        {#each activeRoutes as route (route.id)}
          <article class="routing-row py-5">
            <div class="route-node route-client">
              <span class="route-icon"><PlugsConnectedIcon size={17} /></span>
              <span><small>CLIENT</small><strong>{route.stream ? "SSE stream" : "HTTP request"}</strong></span>
            </div>
            <ArrowRightIcon class="route-arrow" size={17} />
            <div class="route-node">
              <span><small>MODEL</small><strong class="font-data">{route.model_public_id}</strong></span>
            </div>
            <ArrowRightIcon class="route-arrow" size={17} />
            <div class="route-node">
              <span class="route-icon"><BrowserIcon size={17} /></span>
              <span><small>RECIPE / UPSTREAM</small><strong>{route.recipe_slug ?? "direct provider"}</strong><em>{route.domain ?? "OpenAI-compatible"}</em></span>
            </div>
            <ArrowRightIcon class="route-arrow" size={17} />
            <div class="route-node route-target">
              <span class="route-icon"><UserCircleIcon size={17} /></span>
              <span><small>PROFILE / ACCOUNT</small><strong>{routeTarget(route)}</strong></span>
            </div>
            <div class="route-state">
              <CircleNotchIcon size={17} class="animate-spin text-warning" />
              <strong class="font-data">{elapsed(route)}</strong>
              <span>{route.ttfb_ms === null ? "đợi byte đầu" : `TTFB ${route.ttfb_ms} ms`}</span>
            </div>
          </article>
        {/each}
      </div>
    {:else}
      <div class="grid min-h-48 place-items-center border-b border-dashed border-border px-6 py-10 text-center">
        <div>
          <div class="mx-auto flex size-10 items-center justify-center rounded-full border border-border bg-card text-primary">
            <PlugsConnectedIcon size={20} />
          </div>
          <p class="mt-3 text-sm font-medium">Chưa có request đang chạy</p>
          <p class="mt-1 max-w-md text-xs leading-relaxed text-muted-foreground">
            Gửi một completion từ client hoặc mở Sessions để thấy đường đi xuất hiện tại đây.
          </p>
          <Button href="/sessions" variant="outline" size="sm" class="mt-4">Mở Sessions</Button>
        </div>
      </div>
    {/if}
  </section>

  <div class="grid gap-8 lg:grid-cols-[minmax(0,1.55fr)_minmax(17rem,0.7fr)]">
    <section aria-labelledby="recent-routing-title">
      <div class="flex items-end justify-between border-b border-foreground/30 pb-3">
        <div>
          <h3 id="recent-routing-title" class="display-face text-xl font-semibold leading-none">Request gần đây</h3>
          <p class="mt-2 text-xs text-muted-foreground">Kết quả và đích cuối cùng của từng lượt gọi.</p>
        </div>
        <a href="/sessions" class="text-xs font-medium text-primary underline-offset-4 hover:underline">Xem sessions</a>
      </div>

      {#if recentRoutes.length}
        <div class="divide-y divide-border">
          {#each recentRoutes as route (route.id)}
            <svelte:element
              this={route.session_id ? "a" : "div"}
              class="recent-row group"
              href={route.session_id ? `/sessions/${route.session_id}` : undefined}
            >
              <span class="status-mark status-{route.status}" aria-hidden="true"></span>
              <span class="min-w-0">
                <strong class="block truncate font-data text-xs font-medium">{route.model_public_id}</strong>
                <span class="mt-1 block truncate text-[11px] text-muted-foreground">
                  {route.recipe_slug ?? "direct"} → {routeTarget(route)}
                  {route.domain ? ` → ${route.domain}` : ""}
                </span>
              </span>
              <span class="hidden text-right sm:block">
                <Badge variant={statusVariant(route.status)}>{statusLabel(route.status)}</Badge>
                <span class="mt-1 block font-data text-[10px] text-muted-foreground">{elapsed(route)}</span>
              </span>
              <span class="text-right font-data text-[10px] text-muted-foreground">{age(route.started_at)}</span>
            </svelte:element>
          {/each}
        </div>
      {:else}
        <p class="border-b border-dashed border-border py-10 text-center text-sm text-muted-foreground">
          Chưa có lịch sử request để hiển thị.
        </p>
      {/if}
    </section>

    <aside class="border-t-2 border-foreground pt-4" aria-labelledby="routing-policy-title">
      <h3 id="routing-policy-title" class="display-face text-xl font-semibold leading-none">Cách server quyết định</h3>
      <ol class="mt-5 divide-y divide-border border-y border-border">
        <li class="policy-step"><span>1</span><div><strong>Resolve model</strong><p>Model public được ánh xạ sang recipe/provider.</p></div></li>
        <li class="policy-step"><span>2</span><div><strong>Chọn account</strong><p>Ưu tiên target client chỉ định; nếu không, rotator chọn account rảnh.</p></div></li>
        <li class="policy-step"><span>3</span><div><strong>Giữ slot</strong><p>Account/profile được reserve trước khi response headers mở.</p></div></li>
        <li class="policy-step"><span>4</span><div><strong>Chạy upstream</strong><p>Stream giữ concurrency slot tới byte cuối, rồi giải phóng đích.</p></div></li>
      </ol>
      {#if $overview && !$overview.routes_persisted}
        <p class="mt-4 text-xs leading-relaxed text-warning">Kho SQLite chưa mở nên lịch sử routing không được lưu.</p>
      {:else if healthy}
        <p class="mt-4 flex items-center gap-2 text-xs text-success"><CheckCircleIcon size={15} /> Routing store đang ghi nhận bình thường.</p>
      {/if}
    </aside>
  </div>
</PageShell>

<style>
  .distribution-diagram {
    display: grid;
    grid-template-columns: minmax(11rem, 0.56fr) minmax(0, 1.44fr);
    min-height: 26rem;
    overflow: hidden;
    border-bottom: 1px solid var(--border);
    background-image: linear-gradient(90deg, color-mix(in oklch, var(--border) 22%, transparent) 1px, transparent 1px);
    background-size: 3rem 100%;
  }
  .source-stage { display: grid; grid-template-columns: 1fr minmax(2.5rem, 0.35fr); align-items: center; padding-left: 1rem; }
  .source-node { position: relative; display: grid; grid-template-columns: 2rem 1fr; align-items: center; gap: 0.75rem; border: 1px solid var(--foreground); border-radius: 0.55rem; background: var(--foreground); padding: 1rem; color: var(--background); box-shadow: 0 10px 28px color-mix(in oklch, var(--foreground) 14%, transparent); }
  .source-node small, .destination-node small { display: block; font-family: var(--font-mono); font-size: 0.53rem; letter-spacing: 0.09em; opacity: 0.65; }
  .source-node strong { display: block; margin-top: 0.2rem; font-family: var(--font-mono); font-size: 1.5rem; line-height: 1; }
  .source-node em { display: block; margin-top: 0.25rem; font-size: 0.65rem; font-style: normal; opacity: 0.7; }
  .source-pulse { position: absolute; inset: -1px; border: 1px solid var(--primary); border-radius: inherit; animation: source-breathe 2.4s cubic-bezier(0.16, 1, 0.3, 1) infinite; }
  .source-trunk { position: relative; height: 2px; overflow: hidden; background: color-mix(in oklch, var(--primary) 38%, var(--border)); }
  .source-trunk span { position: absolute; inset: 0; transform: translateX(-100%); background: var(--primary); animation: trunk-flow 1.4s linear infinite; }
  .branch-stage { position: relative; display: grid; align-content: center; gap: 0.55rem; padding: 1.25rem 0; }
  .branch-stage::before { content: ""; position: absolute; inset-block: 2rem; left: 0; width: 1px; background: color-mix(in oklch, var(--primary) 45%, var(--border)); }
  .flow-branch { display: grid; grid-template-columns: minmax(3rem, 0.42fr) minmax(12rem, 1fr); align-items: center; min-height: 3.75rem; }
  .flow-rail { position: relative; container-type: inline-size; height: calc(1px + var(--branch-strength) * 5px); min-height: 2px; overflow: hidden; background: color-mix(in oklch, var(--primary) calc(20% + var(--branch-strength) * 42%), var(--border)); transform-origin: left; }
  .flow-particle { position: absolute; top: 50%; left: -0.5rem; width: calc(0.25rem + var(--branch-strength) * 0.22rem); height: calc(0.25rem + var(--branch-strength) * 0.22rem); border-radius: 50%; background: var(--primary); box-shadow: 0 0 0 3px color-mix(in oklch, var(--primary) 14%, transparent); animation: request-flow var(--flow-duration) linear infinite; animation-delay: var(--flow-delay); }
  .particle-b { animation-delay: calc(var(--flow-delay) - var(--flow-duration) / 2); }
  .particle-c { animation-delay: calc(var(--flow-delay) - var(--flow-duration) / 3); }
  .destination-node { position: relative; display: grid; grid-template-columns: minmax(0,1fr) auto; align-items: center; gap: 0.75rem; min-height: 3.75rem; border: 1px solid var(--border); border-right: 0; background: color-mix(in oklch, var(--card) 90%, transparent); padding: 0.65rem 1rem 0.75rem; transition: border-color 180ms ease, background-color 180ms ease; }
  .destination-node:hover { border-color: color-mix(in oklch, var(--primary) 55%, var(--border)); background: var(--card); }
  .destination-main { display: grid; grid-template-columns: 1.5rem minmax(0,1fr); align-items: center; gap: 0.65rem; min-width: 0; }
  .destination-rank { color: var(--primary); font-size: 0.62rem; }
  .destination-node strong { display: block; overflow: hidden; margin-top: 0.1rem; text-overflow: ellipsis; white-space: nowrap; font-size: 0.78rem; font-weight: 600; }
  .destination-node em { display: block; overflow: hidden; margin-top: 0.1rem; color: var(--muted-foreground); text-overflow: ellipsis; white-space: nowrap; font-size: 0.62rem; font-style: normal; }
  .destination-count { min-width: 3.5rem; text-align: right; }
  .destination-count strong { font-size: 1.5rem; line-height: 1; }
  .destination-count span { display: block; margin-top: 0.2rem; font-family: var(--font-mono); color: var(--muted-foreground); font-size: 0.58rem; }
  .destination-meter { position: absolute; right: 0; bottom: 0; left: 0; height: 2px; overflow: hidden; background: var(--muted); }
  .destination-meter span { display: block; width: 100%; height: 100%; transform-origin: left; background: var(--primary); transition: transform 700ms cubic-bezier(0.16, 1, 0.3, 1); }
  .destination-state { position: absolute; right: 4.9rem; top: 0.45rem; display: flex; gap: 0.5rem; font-family: var(--font-mono); font-size: 0.52rem; }
  .flow-paused .source-pulse, .flow-paused .source-trunk span, .flow-paused .flow-particle { animation-play-state: paused; }
  @keyframes request-flow { from { transform: translate3d(0,-50%,0); } to { transform: translate3d(calc(100cqw + 0.5rem),-50%,0); } }
  @keyframes trunk-flow { to { transform: translateX(100%); } }
  @keyframes source-breathe { 0%, 100% { opacity: 0.25; transform: scale(1); } 50% { opacity: 0; transform: scale(1.045, 1.12); } }
  .routing-row {
    display: grid;
    grid-template-columns: minmax(8.5rem, 0.8fr) 1rem minmax(10rem, 1fr) 1rem minmax(11rem, 1fr) 1rem minmax(10rem, 1fr) minmax(6.5rem, 0.5fr);
    align-items: center;
    gap: 0.65rem;
  }
  .route-node { display: flex; min-width: 0; align-items: center; gap: 0.65rem; }
  .route-node > span:last-child { min-width: 0; }
  .route-node small { display: block; margin-bottom: 0.22rem; font-family: var(--font-mono); font-size: 0.55rem; letter-spacing: 0.08em; color: var(--muted-foreground); }
  .route-node strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.78rem; font-weight: 600; }
  .route-node em { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 0.15rem; color: var(--muted-foreground); font-size: 0.65rem; font-style: normal; }
  .route-icon { display: grid; width: 2rem; height: 2rem; flex: 0 0 auto; place-items: center; border: 1px solid var(--border); border-radius: 0.45rem; background: var(--card); color: var(--primary); }
  .route-client .route-icon { background: var(--foreground); color: var(--background); border-color: var(--foreground); }
  .route-target .route-icon { border-color: color-mix(in oklch, var(--primary) 40%, var(--border)); background: color-mix(in oklch, var(--primary) 9%, var(--card)); }
  .route-arrow { color: var(--muted-foreground); }
  .route-state { display: grid; justify-items: end; gap: 0.15rem; }
  .route-state strong { font-size: 0.72rem; }
  .route-state span { font-size: 0.6rem; color: var(--muted-foreground); }
  .recent-row { display: grid; grid-template-columns: 0.45rem minmax(0,1fr) auto auto; align-items: center; gap: 0.9rem; min-height: 4rem; color: var(--foreground); transition: background-color 140ms ease; }
  .recent-row:hover { background: color-mix(in oklch, var(--muted) 55%, transparent); }
  .status-mark { width: 0.35rem; height: 1.7rem; border-radius: 999px; background: var(--muted-foreground); }
  .status-ok { background: var(--success); }
  .status-running { background: var(--warning); }
  .status-error, .status-timeout, .status-trial_limit { background: var(--destructive); }
  .policy-step { display: grid; grid-template-columns: 1.5rem 1fr; gap: 0.8rem; padding: 0.8rem 0; }
  .policy-step > span { font-family: var(--font-mono); font-size: 0.68rem; color: var(--primary); }
  .policy-step strong { font-size: 0.8rem; font-weight: 600; }
  .policy-step p { margin-top: 0.15rem; font-size: 0.7rem; line-height: 1.5; color: var(--muted-foreground); }
  @media (max-width: 1080px) {
    .distribution-diagram { grid-template-columns: minmax(10rem, 0.46fr) minmax(0, 1.54fr); }
    .flow-branch { grid-template-columns: minmax(2rem, 0.25fr) minmax(11rem, 1fr); }
    .routing-row { grid-template-columns: minmax(8rem, 1fr) 1rem minmax(9rem, 1fr) 1rem minmax(10rem, 1fr) minmax(6rem, 0.6fr); }
    .routing-row > :nth-child(6), .routing-row > :nth-child(7) { display: none; }
  }
  @media (max-width: 700px) {
    .distribution-diagram { display: block; min-height: 0; padding: 1rem 0 0; background-size: 2rem 100%; }
    .source-stage { grid-template-columns: minmax(0,1fr) 2rem; padding-left: 0; }
    .source-node { padding: 0.8rem; }
    .branch-stage { gap: 0.7rem; padding: 1rem 0; }
    .branch-stage::before { inset-block: 0; left: 2rem; }
    .flow-branch { grid-template-columns: 2rem minmax(0,1fr); }
    .destination-node { border-right: 1px solid var(--border); padding-right: 0.7rem; }
    .destination-state { display: none; }
    .routing-row { grid-template-columns: 1fr; gap: 0.75rem; }
    .route-arrow { display: none; }
    .routing-row > :nth-child(6), .routing-row > :nth-child(7) { display: flex; }
    .route-node { border-bottom: 1px solid var(--border); padding-bottom: 0.75rem; }
    .route-state { grid-template-columns: auto 1fr auto; justify-items: start; align-items: center; }
    .recent-row { grid-template-columns: 0.35rem minmax(0,1fr) auto; }
    .recent-row > :last-child { display: none; }
  }
  @media (prefers-reduced-motion: reduce) {
    .source-pulse, .source-trunk span, .flow-particle { animation: none; }
    .source-trunk span { transform: none; opacity: 0.65; }
    .flow-particle { left: calc(var(--branch-strength) * 72%); transform: translateY(-50%); box-shadow: none; }
    .destination-meter span { transition-duration: 120ms; }
  }
</style>
