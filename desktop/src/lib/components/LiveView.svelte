<script lang="ts">
  import { apiKey } from "../stores";
  import { fetchScreenshot } from "../api";

  let { watchId }: { watchId: string | null } = $props();

  let imgUrl = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;

  async function poll(id: string) {
    const blob = await fetchScreenshot($apiKey, id);
    if (watchId !== id) return;
    if (blob) {
      const url = URL.createObjectURL(blob);
      const old = imgUrl;
      imgUrl = url;
      if (old) URL.revokeObjectURL(old);
    }
    if (watchId === id) timer = setTimeout(() => poll(id), 700);
  }

  $effect(() => {
    const id = watchId;
    if (!id) return;
    poll(id);
    return () => {
      if (timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
      if (imgUrl) {
        URL.revokeObjectURL(imgUrl);
        imgUrl = null;
      }
    };
  });
</script>

{#if imgUrl}
  <div class="live-view">
    <p class="live-view-label">Live view — browser đang chạy</p>
    <img src={imgUrl} alt="Live view của browser đang chạy recipe" />
  </div>
{/if}
