<script lang="ts">
  import RecipesTable from "$lib/components/RecipesTable.svelte";
</script>

<section class="view page">
  <div class="page-heading">
    <h1>Recipes</h1>
    <p>
      Kênh đang phục vụ router. Account nằm ở <a href="/accounts">trang Accounts</a> và dùng chung
      theo domain.
    </p>
  </div>
  <RecipesTable />
</section>
