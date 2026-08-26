<script lang="ts">
  import { mode, setMode } from "mode-watcher";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import SunIcon from "phosphor-svelte/lib/SunIcon";
  import MoonIcon from "phosphor-svelte/lib/MoonIcon";
  import DesktopIcon from "phosphor-svelte/lib/DesktopIcon";
</script>

<DropdownMenu.Root>
  <DropdownMenu.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="ghost" size="icon-sm" aria-label="Đổi giao diện sáng/tối">
        {#if mode.current === "dark"}
          <MoonIcon size={16} />
        {:else}
          <SunIcon size={16} />
        {/if}
      </Button>
    {/snippet}
  </DropdownMenu.Trigger>
  <DropdownMenu.Content align="end">
    <DropdownMenu.Item onclick={() => setMode("light")}>
      <SunIcon size={16} />
      <span>Sáng</span>
    </DropdownMenu.Item>
    <DropdownMenu.Item onclick={() => setMode("dark")}>
      <MoonIcon size={16} />
      <span>Tối</span>
    </DropdownMenu.Item>
    <DropdownMenu.Item onclick={() => setMode("system")}>
      <DesktopIcon size={16} />
      <span>Theo hệ thống</span>
    </DropdownMenu.Item>
  </DropdownMenu.Content>
</DropdownMenu.Root>
