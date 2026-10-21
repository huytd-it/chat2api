<script lang="ts">
  import { page } from "$app/state";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import GaugeIcon from "phosphor-svelte/lib/GaugeIcon";
  import ChatCircleTextIcon from "phosphor-svelte/lib/ChatCircleTextIcon";
  import { Globe, Plus } from "phosphor-svelte";
  import BrowserIcon from "phosphor-svelte/lib/BrowserIcon";
  import ShuffleIcon from "phosphor-svelte/lib/ShuffleIcon";
  import StackIcon from "phosphor-svelte/lib/StackIcon";
  import ScrollIcon from "phosphor-svelte/lib/ScrollIcon";
  import GearSixIcon from "phosphor-svelte/lib/GearSixIcon";
  import { serverStatus } from "$lib/stores";
  import { recipes } from "$lib/sync";
  import { cn } from "$lib/utils";
  import { websites } from "$lib/websites";
  import ProviderIcon from "./sessions/ProviderIcon.svelte";

  const links = [
    { href: "/profiles", label: "Profiles & account", icon: StackIcon },
    { href: "/providers", label: "API & tích hợp", icon: BrowserIcon },
    { href: "/combos", label: "Combos", icon: ShuffleIcon },
    { href: "/sessions", label: "Lịch sử & API", icon: ChatCircleTextIcon },
    { href: "/overview", label: "Hệ thống", icon: GaugeIcon },
    { href: "/logs", label: "Nhật ký", icon: ScrollIcon },
  ];

  function isActive(href: string): boolean {
    const path = page.url.pathname.replace(/\/+$/, "") || "/";
    return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  }

  const settingsActive = $derived(isActive("/settings"));

  const statusLabels: Record<"loading" | "ok" | "error", string> = {
    loading: "Đang kết nối",
    ok: "Server sẵn sàng",
    error: "Mất kết nối",
  };

  const statusDotClass = $derived(
    $serverStatus.state === "ok"
      ? "bg-success"
      : $serverStatus.state === "error"
        ? "bg-destructive"
        : "animate-pulse bg-warning",
  );
</script>

<Sidebar.Root variant="floating" collapsible="icon">
  <Sidebar.Header>
    <div
      class="flex items-center gap-2.5 px-3 py-2 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0"
    >
      <div
        class="flex size-8 shrink-0 cursor-default select-none items-center justify-center rounded-lg bg-sidebar-primary text-xs font-bold tracking-tight text-sidebar-primary-foreground"
      >
        c2
      </div>
      <div class="grid min-w-0 flex-1 leading-tight group-data-[collapsible=icon]:hidden">
        <span class="truncate text-sm font-semibold">chat2api</span>
        <span class="truncate text-[11px] text-muted-foreground">website automation</span>
      </div>
    </div>
  </Sidebar.Header>

  <Sidebar.Content>
    <Sidebar.Group>
      <Sidebar.GroupContent>
        <Sidebar.Menu>
          <Sidebar.MenuItem>
            <Sidebar.MenuButton isActive={isActive("/")} tooltipContent="Tất cả website">
              {#snippet child({ props })}<a href="/" {...props}><Globe size={18} /><span>Tất cả website</span></a>{/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        </Sidebar.Menu>
      </Sidebar.GroupContent>
    </Sidebar.Group>
    <Sidebar.Group>
      <Sidebar.GroupLabel>Workspaces</Sidebar.GroupLabel>
      <Sidebar.GroupContent><Sidebar.Menu>
        {#each $websites as site (site.id)}
          <Sidebar.MenuItem>
            <Sidebar.MenuButton isActive={isActive(`/websites/${site.id}`)} tooltipContent={site.title}>
              {#snippet child({ props })}
                <a href={`/websites/${site.id}`} {...props}>
                  <ProviderIcon model={site.slug} size={18} /><span>{site.title}</span>
                  {#if !site.models.length}<span class="ml-auto size-1.5 rounded-full bg-muted-foreground/40 group-data-[collapsible=icon]:hidden" title="Chưa có automation đang nạp"></span>{/if}
                </a>
              {/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        {/each}
      </Sidebar.Menu></Sidebar.GroupContent>
    </Sidebar.Group>
    <Sidebar.Group>
      <Sidebar.GroupLabel>Quản trị</Sidebar.GroupLabel>
      <Sidebar.GroupContent>
        <Sidebar.Menu>
          {#each links as link (link.href)}
            <Sidebar.MenuItem>
              <Sidebar.MenuButton isActive={isActive(link.href)} tooltipContent={link.label}>
                {#snippet child({ props })}
                  <a href={link.href} {...props}>
                    <link.icon size={18} />
                    <span>{link.label}</span>
                  </a>
                {/snippet}
              </Sidebar.MenuButton>
            </Sidebar.MenuItem>
          {/each}
          <Sidebar.MenuItem>
            <Sidebar.MenuButton isActive={isActive("/integrations")} tooltipContent="Kết nối website">
              {#snippet child({ props })}<a href="/integrations" {...props}><Plus size={18} /><span>Kết nối website</span></a>{/snippet}
            </Sidebar.MenuButton>
          </Sidebar.MenuItem>
        </Sidebar.Menu>
      </Sidebar.GroupContent>
    </Sidebar.Group>
  </Sidebar.Content>

  <Sidebar.Footer>
    <Sidebar.Menu>
      <Sidebar.MenuItem>
        <Sidebar.MenuButton isActive={settingsActive} tooltipContent="Cài đặt">
          {#snippet child({ props })}
            <a href="/settings" {...props}>
              <GearSixIcon size={18} />
              <span>Cài đặt</span>
            </a>
          {/snippet}
        </Sidebar.MenuButton>
      </Sidebar.MenuItem>
    </Sidebar.Menu>

    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <div
            {...props}
            data-state={$serverStatus.state}
            class="flex h-8 items-center gap-2 rounded-md border border-sidebar-border px-2 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:border-transparent group-data-[collapsible=icon]:px-0"
          >
            <span class={cn("size-2 shrink-0 rounded-full", statusDotClass)}></span>
            <span
              class="min-w-0 flex-1 truncate text-xs font-medium group-data-[collapsible=icon]:hidden"
            >
              {statusLabels[$serverStatus.state]}
            </span>
            <span
              class="font-data text-xs text-muted-foreground tabular-nums group-data-[collapsible=icon]:hidden"
            >
              {$serverStatus.contexts}
            </span>
          </div>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content side="right" align="end" class="font-data text-xs">
        <div class="grid gap-1">
          <div>engine: {$serverStatus.engine}</div>
          <div>contexts: {$serverStatus.contexts}</div>
          <div>recipes: {$recipes.length}</div>
        </div>
      </Tooltip.Content>
    </Tooltip.Root>
  </Sidebar.Footer>

  <Sidebar.Rail />
</Sidebar.Root>
