<script lang="ts">
  import { page } from "$app/state";
  import ServerStatus from "./ServerStatus.svelte";
  import ThemeToggle from "./ThemeToggle.svelte";
  import GaugeIcon from "phosphor-svelte/lib/GaugeIcon";
  import ChatCircleTextIcon from "phosphor-svelte/lib/ChatCircleTextIcon";
  import PlugsConnectedIcon from "phosphor-svelte/lib/PlugsConnectedIcon";
  import ScrollIcon from "phosphor-svelte/lib/ScrollIcon";
  import GearSixIcon from "phosphor-svelte/lib/GearSixIcon";

  const links = [
    { href: "/", label: "Overview", note: "System pulse", icon: GaugeIcon },
    { href: "/sessions", label: "Sessions", note: "Live traffic", icon: ChatCircleTextIcon },
    { href: "/integrations", label: "Integrations", note: "Channels", icon: PlugsConnectedIcon },
    { href: "/logs", label: "Logs", note: "Event stream", icon: ScrollIcon },
    { href: "/settings", label: "Settings", note: "Runtime", icon: GearSixIcon },
  ];

  function isActive(href: string): boolean {
    const path = page.url.pathname.replace(/\/+$/, "") || "/";
    return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  }
</script>

<a
  href="#main-content"
  class="fixed left-3 top-3 z-50 -translate-y-20 bg-foreground px-3 py-2 text-xs font-semibold text-background transition-transform focus:translate-y-0"
>
  Bỏ qua điều hướng
</a>

<header class="app-masthead shrink-0 border-b border-border bg-background" aria-label="Điều hướng chính">
  <div class="flex h-12 items-center gap-4 border-b border-border px-4 lg:px-6">
    <a href="/" class="group flex shrink-0 items-center gap-2.5" aria-label="chat2api overview">
      <span class="brand-mark" aria-hidden="true">C2</span>
      <span class="hidden sm:block">
        <span class="block text-sm font-semibold leading-none tracking-[-0.02em]">chat2api</span>
        <span class="mt-1 block font-data text-[9px] leading-none tracking-[0.12em] text-muted-foreground">DISPATCH CONSOLE</span>
      </span>
    </a>

    <div class="hidden h-5 w-px bg-border md:block"></div>
    <p class="hidden min-w-0 flex-1 truncate text-xs text-muted-foreground md:block">
      Web chat requests, accounts and browser contexts — một nơi vận hành.
    </p>

    <div class="ml-auto flex items-center gap-2">
      <ServerStatus />
      <ThemeToggle />
    </div>
  </div>

  <nav class="route-strip flex min-h-14 overflow-x-auto px-2 sm:px-4 lg:px-6" aria-label="Khu vực hệ thống">
    {#each links as link (link.href)}
      <a
        href={link.href}
        class:active={isActive(link.href)}
        aria-current={isActive(link.href) ? "page" : undefined}
        class="route-link group flex min-w-fit items-center gap-2.5 border-r border-border px-3 py-2.5 transition-colors first:border-l hover:bg-muted/70 sm:min-w-32 sm:px-4"
      >
        <link.icon size={17} weight={isActive(link.href) ? "fill" : "regular"} />
        <span>
          <span class="block text-xs font-semibold leading-none">{link.label}</span>
          <span class="mt-1 hidden font-data text-[9px] leading-none tracking-[0.08em] text-muted-foreground sm:block">{link.note}</span>
        </span>
      </a>
    {/each}
  </nav>
</header>
