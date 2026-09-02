<script lang="ts">
  import { page } from "$app/state";
  import * as Sidebar from "$lib/components/ui/sidebar/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import ServerStatus from "./ServerStatus.svelte";
  import ThemeToggle from "./ThemeToggle.svelte";

  const titles: Record<string, string> = {
    "/": "Overview",
    "/sessions": "Sessions",
    "/recipes": "Recipes",
    "/providers": "Providers",
    "/combos": "Combos",
    "/profiles": "Profiles",
    "/logs": "Logs",
    "/settings": "Settings",
  };

  const title = $derived.by(() => {
    const path = page.url.pathname.replace(/\/+$/, "") || "/";
    if (titles[path]) return titles[path];
    const section = Object.keys(titles).find((key) => key !== "/" && path.startsWith(key));
    return section ? titles[section] : "chat2api";
  });
</script>

<header
  class="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80"
>
  <Sidebar.Trigger />
  <Separator orientation="vertical" class="h-5" />
  <h1 class="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{title}</h1>
  <ServerStatus />
  <ThemeToggle />
</header>
