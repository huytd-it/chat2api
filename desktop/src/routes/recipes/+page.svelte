<script lang="ts">
  // Route Recipe cũ đã ẩn — chuyển sang Flows (module thay thế).
  import { goto } from "$app/navigation";
  import { onMount } from "svelte";

  onMount(() => {
    goto("/flows", { replaceState: true });
  });
</script>

<div class="flex min-h-0 flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
  Recipe đã chuyển thành Flows — đang chuyển hướng…
</div>
