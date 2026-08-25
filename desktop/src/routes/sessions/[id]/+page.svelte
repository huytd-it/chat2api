<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";

  onMount(() => {
    location.replace("/sessions?open=" + encodeURIComponent(page.params.id ?? ""));
  });
</script>

<p class="hint">Đang mở session…</p>
