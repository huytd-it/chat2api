<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  onMount(() => { void goto(`/websites/${page.params.site}`, { replaceState: true }); });
</script>

<a href={`/websites/${page.params.site}`} class="p-6 text-sm text-primary">Mở cấu hình automation</a>
