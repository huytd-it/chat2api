<script lang="ts">
  import SessionWorkspace from "$lib/components/SessionWorkspace.svelte";
</script>

<!-- Không dùng wrapper cuộn + max-width như các route khác: workbench là bố cục
     ba rail tự quản chiều cao, phần cuộn nằm trong từng rail. -->
<SessionWorkspace />
