<script lang="ts">
  // Pha 5 (docs/design-v2.md §6): Recipes + Accounts + Integrate gộp thành một
  // trang, ba panel xếp dọc theo đúng thứ tự công việc — thêm site, xem site đã
  // có, rồi mới tới hạ tầng profile.
  import { onMount } from "svelte";
  import IntegratePanel from "$lib/components/IntegratePanel.svelte";
  import SitesPanel from "$lib/components/SitesPanel.svelte";
  import ProfilesPanel from "$lib/components/ProfilesPanel.svelte";
  import { refreshIntegrations } from "$lib/sync";

  onMount(() => {
    refreshIntegrations();
  });
</script>

<section class="view page">
  <div class="page-heading">
    <h1>Integrations</h1>
    <p>
      Biến một web chat thành API, rồi quản lý luôn account và profile trình duyệt của nó —
      tất cả ở một chỗ.
    </p>
  </div>

  <IntegratePanel />
  <SitesPanel />
  <ProfilesPanel />
</section>
