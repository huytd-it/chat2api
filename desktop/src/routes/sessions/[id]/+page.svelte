<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";

  onMount(() => {
    location.replace("/sessions?open=" + encodeURIComponent(page.params.id ?? ""));
  });
</script>

<div class="flex flex-1 items-center justify-center gap-2 p-8 text-sm text-muted-foreground">
  <span class="size-2 animate-pulse rounded-full bg-warning" aria-hidden="true"></span>
  Đang mở session…
</div>
