<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { recipes, recipesLoading, refreshRecipes, refreshModels } from "../sync";
  import { reloadRecipe, deleteRecipe, startAccountLogin, completeAccountLogin, cancelAccountLogin } from "../api";

  let reloadingSlug = $state<string | null>(null);
  let deletingSlug = $state<string | null>(null);

  let accountSlug = $state<string | null>(null);
  let accountSessionId = $state<string | null>(null);
  let accountFlowStatus = $state("");
  let accountName = $state("");
  let accountSaving = $state(false);

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

  function resetAccountFlow() {
    accountSlug = null;
    accountSessionId = null;
    accountName = "";
  }

  async function onAddAccount(slug: string) {
    if (accountSessionId) {
      showToast("Đang có phiên thêm account khác, hãy hoàn tất hoặc hủy trước.");
      return;
    }
    try {
      const data = await startAccountLogin($apiKey, slug);
      accountSlug = slug;
      accountSessionId = data.session_id;
      accountFlowStatus = "Chrome đã mở cho " + slug + ". Đăng nhập xong, đặt tên account rồi bấm Lưu.";
    } catch (e) {
      showToast((e as Error).message);
    }
  }

  async function onSaveAccount() {
    if (!accountSessionId || !accountSlug) return;
    const name = accountName.trim();
    if (!name) {
      showToast("Nhập tên account.");
      return;
    }
    accountSaving = true;
    try {
      await completeAccountLogin($apiKey, accountSlug, accountSessionId, name);
      showToast("Đã thêm account " + name + " cho " + accountSlug);
      resetAccountFlow();
      await refreshRecipes();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      accountSaving = false;
    }
  }

  async function onCancelAccount() {
    const slug = accountSlug, sessionId = accountSessionId;
    resetAccountFlow();
    if (slug && sessionId) {
      try {
        await cancelAccountLogin($apiKey, slug, sessionId);
      } catch {
        /* best effort */
      }
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
          <th>Đăng nhập</th>
          <th aria-label="Thao tác"></th>
        </tr>
      </thead>
      <tbody>
        {#if $recipesLoading}
          <tr class="empty-row"><td colspan="5">Đang tải recipes...</td></tr>
        {:else if $recipes.length === 0}
          <tr class="empty-row"><td colspan="5">Chưa có recipe. Hãy tích hợp một website mới.</td></tr>
        {:else}
          {#each $recipes as rec (rec.slug)}
            {@const isBrowserRecipe = rec.type === "BrowserRecipe"}
            <tr>
              <td>{rec.slug}</td>
              <td>{(rec.models || []).join(", ")}</td>
              <td>
                <span class="recipe-state" class:unhealthy={rec.unhealthy}>
                  {rec.unhealthy ? "Cần kiểm tra" : "Sẵn sàng"}
                </span>
              </td>
              <td>
                {#if isBrowserRecipe}
                  {#if rec.trial}
                    <span class="login-badge trial">Dùng thử {rec.trial.used}/{rec.trial.limit}</span>
                  {:else}
                    <span class="login-badge">{rec.accounts ?? 0} account{(rec.accounts ?? 0) === 1 ? "" : "s"}</span>
                  {/if}
                {:else}
                  -
                {/if}
              </td>
              <td class="recipe-actions">
                <button
                  class="button secondary small"
                  disabled={reloadingSlug === rec.slug}
                  onclick={() => onReload(rec.slug)}
                >
                  Reload
                </button>
                {#if isBrowserRecipe}
                  <button class="button secondary small" onclick={() => onAddAccount(rec.slug)}>
                    Thêm account
                  </button>
                {/if}
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
  {#if accountSessionId}
    <div class="account-flow">
      <p>{accountFlowStatus}</p>
      <div class="url-row">
        <input
          type="text"
          inputmode="text"
          placeholder="ten-account"
          aria-label="Tên account"
          bind:value={accountName}
        />
        <button class="button" disabled={accountSaving} onclick={onSaveAccount}>Lưu</button>
      </div>
      <button class="button secondary small" onclick={onCancelAccount}>Hủy</button>
    </div>
  {/if}
</section>
