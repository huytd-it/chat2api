<script lang="ts">
  import { onMount } from "svelte";
  import { serverStatus } from "$lib/stores";
  import {
    overview,
    recipes,
    accounts,
    refreshOverview,
    refreshRecipes,
    refreshAccounts,
    refreshModels,
  } from "$lib/sync";

  onMount(() => {
    refreshOverview();
  });

  async function refreshAll() {
    await Promise.all([refreshOverview(), refreshRecipes(), refreshAccounts(), refreshModels()]);
  }

  const unhealthy = $derived($overview?.unhealthy ?? []);
  const openBrowsers = $derived($overview?.open_browsers ?? []);
  // Domain có recipe nhưng chưa có account nào: recipe đó đang chạy ẩn danh.
  const domainsWithoutAccounts = $derived(
    $accounts.filter((d) => d.recipes.length > 0 && d.accounts.length === 0),
  );
</script>

<section class="view page">
  <div class="page-heading">
    <h1>Tổng quan</h1>
    <p>Trạng thái server, kênh đang phục vụ và những thứ cần chú ý.</p>
  </div>

  <div class="stat-grid">
    <div class="stat">
      <strong>{$overview?.models ?? "-"}</strong>
      <span>Models sẵn sàng</span>
    </div>
    <div class="stat">
      <strong>{$overview?.recipes ?? "-"}</strong>
      <span>Recipes</span>
    </div>
    <div class="stat">
      <strong>{$overview?.accounts ?? "-"}</strong>
      <span>Accounts</span>
    </div>
    <div class="stat">
      <strong>{$overview?.domains ?? "-"}</strong>
      <span>Domains</span>
    </div>
    <div class="stat">
      <strong>{$overview?.contexts ?? "-"}</strong>
      <span>Browser context</span>
    </div>
    <div class="stat">
      <strong class="mono-sm">{$overview?.engine ?? "-"}</strong>
      <span>Engine</span>
    </div>
  </div>

  <div class="dash-grid">
    <article class="panel dash-card">
      <div class="panel-head">
        <div>
          <h2>Cần chú ý</h2>
          <p>Recipe hỏng và domain chưa có account.</p>
        </div>
        <button class="button secondary small" onclick={refreshAll}>Làm mới</button>
      </div>
      <div class="dash-body">
        {#if $serverStatus.state === "error"}
          <p class="alert fault">Mất kết nối tới server. Kiểm tra sidecar còn chạy không.</p>
        {/if}
        {#if unhealthy.length}
          <p class="alert fault">
            Recipe lỗi liên tiếp: {unhealthy.join(", ")}. Mở trang Recipes để reload hoặc sửa
            selector.
          </p>
        {/if}
        {#each domainsWithoutAccounts as domain (domain.domain)}
          <p class="alert amber">
            <strong>{domain.domain}</strong> chưa có account — {domain.recipes.join(", ")} đang chạy
            ẩn danh và sẽ hết lượt dùng thử.
          </p>
        {/each}
        {#if $serverStatus.state !== "error" && !unhealthy.length && !domainsWithoutAccounts.length}
          <p class="alert ok">Không có vấn đề nào. Mọi recipe đang khoẻ.</p>
        {/if}
      </div>
    </article>

    <article class="panel dash-card">
      <div class="panel-head">
        <div>
          <h2>Browser đang mở</h2>
          <p>Cửa sổ được giữ nguyên tới khi bạn tự tắt.</p>
        </div>
      </div>
      <div class="dash-body">
        {#if openBrowsers.length}
          <ul class="plain-list">
            {#each openBrowsers as slug (slug)}
              <li><span class="dot on"></span>{slug}</li>
            {/each}
          </ul>
          <p class="hint">Tắt bằng nút “Tắt browser” ở trang Recipes.</p>
        {:else}
          <p class="hint">Chưa có browser nào mở. Cửa sổ sẽ mở ở request đầu tiên.</p>
        {/if}
      </div>
    </article>

    <article class="panel dash-card">
      <div class="panel-head">
        <div>
          <h2>Lối tắt</h2>
          <p>Những việc hay làm nhất.</p>
        </div>
      </div>
      <div class="dash-body shortcut-row">
        <a class="button secondary small" href="/playground">Thử một prompt</a>
        <a class="button secondary small" href="/integrations">Thêm web chat mới</a>
        <a class="button secondary small" href="/accounts">Quản lý account</a>
        <a class="button secondary small" href="/settings">Chỉnh delay</a>
      </div>
    </article>
  </div>

  <article class="panel dash-card">
    <div class="panel-head">
      <div>
        <h2>Kênh đang phục vụ</h2>
        <p>{$recipes.length} recipe đã nạp.</p>
      </div>
      <a class="button secondary small" href="/recipes">Mở trang Recipes</a>
    </div>
    <div class="dash-body">
      {#if $recipes.length}
        <ul class="channel-list">
          {#each $recipes as recipe (recipe.slug)}
            <li>
              <span class="dot" class:fault={recipe.unhealthy} class:on={!recipe.unhealthy}></span>
              <strong>{recipe.slug}</strong>
              <span class="hint">{recipe.models.join(", ")}</span>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="hint">Chưa có recipe nào. Bắt đầu ở trang Integrate.</p>
      {/if}
    </div>
  </article>
</section>
