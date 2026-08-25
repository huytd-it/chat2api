<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { recipes, recipesLoading, refreshRecipes, refreshModels } from "../sync";
  import { reloadRecipe, deleteRecipe } from "../api";

  let reloadingSlug = $state<string | null>(null);
  let deletingSlug = $state<string | null>(null);

  async function onReload(slug: string) {
    reloadingSlug = slug;
    try {
      await reloadRecipe($apiKey, slug);
      await refreshRecipes();
      await refreshModels();
    } finally {
      reloadingSlug = null;
    }
  }

  async function onDelete(slug: string) {
    if (!confirm("Xóa recipe " + slug + "?")) return;
    deletingSlug = slug;
    try {
      await deleteRecipe($apiKey, slug);
      await refreshRecipes();
      await refreshModels();
      showToast("Đã xóa recipe " + slug);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      deletingSlug = null;
    }
  }
</script>

<section class="panel recipes-panel">
  <div class="recipes-head">
    <div>
      <h2>Recipes hiện có</h2>
      <p>Reload cấu hình hoặc xóa provider tùy chỉnh.</p>
    </div>
    <button class="button secondary small" onclick={() => { refreshRecipes(); refreshModels(); }}>
      Làm mới
    </button>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Provider</th>
          <th>Models</th>
          <th>Trạng thái</th>
          <th aria-label="Thao tác"></th>
        </tr>
      </thead>
      <tbody>
        {#if $recipesLoading}
          <tr class="empty-row"><td colspan="4">Đang tải recipes...</td></tr>
        {:else if $recipes.length === 0}
          <tr class="empty-row"><td colspan="4">Chưa có recipe. Hãy tích hợp một website mới.</td></tr>
        {:else}
          {#each $recipes as rec (rec.slug)}
            <tr>
              <td>{rec.slug}</td>
              <td>{(rec.models || []).join(", ")}</td>
              <td>
                <span class="recipe-state" class:unhealthy={rec.unhealthy}>
                  {rec.unhealthy ? "Cần kiểm tra" : "Sẵn sàng"}
                </span>
              </td>
              <td class="recipe-actions">
                <button
                  class="button secondary small"
                  disabled={reloadingSlug === rec.slug}
                  onclick={() => onReload(rec.slug)}
                >
                  Reload
                </button>
                <button
                  class="button danger small"
                  disabled={deletingSlug === rec.slug}
                  onclick={() => onDelete(rec.slug)}
                >
                  Xóa
                </button>
              </td>
            </tr>
          {/each}
        {/if}
      </tbody>
    </table>
  </div>
</section>
