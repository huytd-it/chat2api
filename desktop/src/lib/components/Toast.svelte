<script lang="ts">
  import { toastMessage } from "../stores";
</script>

{#if $toastMessage}
  <div class="toast" role="status" aria-live="polite">{$toastMessage}</div>
{/if}
