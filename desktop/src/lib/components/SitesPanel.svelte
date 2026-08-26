<script lang="ts">
  // Panel giữa của trang Integrations (docs/design-v2.md §6): recipe là hàng mở
  // rộng được, và account nằm NGAY TRONG hàng recipe — gom theo domain của
  // recipe, vì đó là chỗ người dùng thật sự đi tìm chúng.
  import { apiKey, showToast } from "../stores";
  import { accounts, recipes, recipesLoading, refreshIntegrations, refreshModels } from "../sync";
  import {
    cancelAccountLogin,
    closeRecipeBrowser,
    completeDomainLogin,
    deleteDomainAccount,
    deleteRecipe,
    reloadRecipe,
    reopenDomainAccount,
    type AccountInfo,
  } from "../api";
  import AccountDialog from "./AccountDialog.svelte";

  let expanded = $state<Record<string, boolean>>({});
  let busySlug = $state<string | null>(null);
  let busyAccount = $state<string | null>(null);
  // Dialog thêm account: null = đóng. Domain đi kèm để khoá ô domain lại.
  let dialogDomain = $state<string | null>(null);
  // Đăng nhập lại một account đã có: domain và nhãn đã biết nên không cần
  // dialog, chỉ cần cửa sổ để đăng nhập rồi ghi đè state cũ.
  let reopenSession = $state<string | null>(null);
  let reopenDomain = $state("");
  let reopenName = $state("");
  let reopenBusy = $state(false);

  function accountsOf(domain: string | undefined): AccountInfo[] {
    if (!domain) return [];
    return $accounts.find((d) => d.domain === domain)?.accounts ?? [];
  }

  function toggle(slug: string) {
    expanded = { ...expanded, [slug]: !expanded[slug] };
  }

  async function onReload(slug: string) {
    busySlug = slug;
    try {
      await reloadRecipe($apiKey, slug);
      await Promise.all([refreshIntegrations(), refreshModels()]);
    } finally {
      busySlug = null;
    }
  }

  async function onCloseBrowser(slug: string) {
    busySlug = slug;
    try {
      const closed = await closeRecipeBrowser($apiKey, slug);
      showToast(closed ? `Đã tắt browser của ${slug}` : `Browser của ${slug} chưa mở`);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busySlug = null;
    }
  }

  async function onDelete(slug: string) {
    if (!confirm(`Xóa recipe ${slug}?`)) return;
    busySlug = slug;
    try {
      await deleteRecipe($apiKey, slug);
      showToast(`Đã xóa recipe ${slug}`);
      await Promise.all([refreshIntegrations(), refreshModels()]);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busySlug = null;
    }
  }

  async function onReopen(domain: string, name: string) {
    busyAccount = `${domain}/${name}`;
    try {
      const res = await reopenDomainAccount($apiKey, domain, name);
      reopenSession = res.session_id;
      reopenDomain = domain;
      reopenName = name;
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyAccount = null;
    }
  }

  /** Ghi đè state cũ bằng phiên vừa đăng nhập lại — đúng domain, đúng nhãn. */
  async function saveReopen() {
    if (!reopenSession) return;
    reopenBusy = true;
    try {
      await completeDomainLogin($apiKey, reopenSession, reopenDomain, reopenName);
      showToast(`Đã cập nhật ${reopenDomain}/${reopenName}`);
      reopenSession = null;
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      reopenBusy = false;
    }
  }

  async function cancelReopen() {
    const session = reopenSession;
    reopenSession = null;
    if (session) await cancelAccountLogin($apiKey, reopenDomain, session).catch(() => {});
  }

  async function onDeleteAccount(domain: string, name: string) {
    if (!confirm(`Xóa account ${domain}/${name}? Recipe dùng domain này sẽ mất phiên đăng nhập.`))
      return;
    busyAccount = `${domain}/${name}`;
    try {
      await deleteDomainAccount($apiKey, domain, name);
      showToast(`Đã xóa ${domain}/${name}`);
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyAccount = null;
    }
  }

  function formatWhen(seconds: number): string {
    return new Date(seconds * 1000).toLocaleString();
  }

  // Domain có account nhưng không recipe nào dùng: vẫn phải hiện ra, nếu không
  // account đăng nhập rồi sẽ biến mất khỏi UI khi recipe bị xóa.
  const orphanDomains = $derived(
    $accounts.filter((d) => d.recipes.length === 0 && d.accounts.length > 0),
  );
</script>

<section class="panel dash-card">
  <div class="panel-head">
    <div>
      <h2>Site đã tích hợp</h2>
      <p>Mở một hàng để xem model, account và các thao tác của recipe đó.</p>
    </div>
    <button class="button secondary small" onclick={() => refreshIntegrations()}>Làm mới</button>
  </div>

  <div class="site-list">
    {#if $recipesLoading && !$recipes.length}
      <p class="site-empty">Đang tải recipes…</p>
    {:else if !$recipes.length}
      <p class="site-empty">Chưa có recipe nào. Phân tích một web chat ở panel trên.</p>
    {/if}

    {#each $recipes as rec (rec.slug)}
      {@const isBrowser = rec.type === "BrowserRecipe"}
      {@const list = accountsOf(rec.domain)}
      <div class="site-row" class:open={expanded[rec.slug]}>
        <button class="site-summary" onclick={() => toggle(rec.slug)} aria-expanded={expanded[rec.slug] ?? false}>
          <span class="site-caret" aria-hidden="true">{expanded[rec.slug] ? "▾" : "▸"}</span>
          <span class="site-slug">{rec.slug}</span>
          <span class="site-domain mono-sm">{rec.domain ?? "—"}</span>
          <span class="hint">{rec.models.length} model</span>
          <span class="recipe-state" class:unhealthy={rec.unhealthy}>
            {rec.unhealthy ? "Cần kiểm tra" : "Sẵn sàng"}
          </span>
          {#if isBrowser}
            {#if rec.trial}
              <span class="login-badge trial">Dùng thử {rec.trial.used}/{rec.trial.limit}</span>
            {:else}
              <span class="login-badge">{list.length} account</span>
            {/if}
          {/if}
        </button>

        {#if expanded[rec.slug]}
          <div class="site-detail">
            <div class="detail-line">
              <span class="detail-label">Models</span>
              <span class="mono-sm">{rec.models.join(", ") || "—"}</span>
            </div>
            {#if rec.url}
              <div class="detail-line">
                <span class="detail-label">URL</span>
                <span class="mono-sm">{rec.url}</span>
              </div>
            {/if}
            <div class="recipe-actions">
              <button class="button secondary small" disabled={busySlug === rec.slug} onclick={() => onReload(rec.slug)}>
                Reload
              </button>
              {#if isBrowser}
                <button class="button secondary small" disabled={busySlug === rec.slug} onclick={() => onCloseBrowser(rec.slug)}>
                  Đóng browser
                </button>
              {/if}
              <button class="button danger small" disabled={busySlug === rec.slug} onclick={() => onDelete(rec.slug)}>
                Xóa
              </button>
            </div>

            {#if isBrowser}
              <div class="detail-line">
                <span class="detail-label">Accounts</span>
                <span class="hint">theo domain {rec.domain}</span>
              </div>
              {#if list.length}
                <table class="data-table">
                  <thead>
                    <tr><th>Account</th><th>Cập nhật</th><th class="col-actions">Thao tác</th></tr>
                  </thead>
                  <tbody>
                    {#each list as account (account.name)}
                      {@const key = `${rec.domain}/${account.name}`}
                      <tr>
                        <td><span class="mono-sm">{account.name}</span></td>
                        <td class="hint">{formatWhen(account.updated_at)}</td>
                        <td class="recipe-actions">
                          <button class="button secondary small" disabled={busyAccount === key}
                                  onclick={() => onReopen(rec.domain ?? "", account.name)}>
                            Đăng nhập lại
                          </button>
                          <button class="button danger small" disabled={busyAccount === key}
                                  onclick={() => onDeleteAccount(rec.domain ?? "", account.name)}>
                            Xóa
                          </button>
                        </td>
                      </tr>
                    {/each}
                  </tbody>
                </table>
              {:else}
                <p class="alert amber">
                  Chưa có account — recipe này đang chạy ẩn danh và sẽ hết lượt dùng thử.
                </p>
              {/if}
              <button class="button secondary small" onclick={() => (dialogDomain = rec.domain ?? "")}>
                + Thêm account
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#each orphanDomains as d (d.domain)}
      <div class="site-row orphan">
        <div class="site-summary static">
          <span class="site-slug">{d.domain}</span>
          <span class="hint">chưa recipe nào dùng</span>
          <span class="login-badge">{d.accounts.length} account</span>
          <span class="recipe-actions">
            {#each d.accounts as account (account.name)}
              <button class="button danger small" disabled={busyAccount === `${d.domain}/${account.name}`}
                      onclick={() => onDeleteAccount(d.domain, account.name)}>
                Xóa {account.name}
              </button>
            {/each}
          </span>
        </div>
      </div>
    {/each}
  </div>

  {#if reopenSession}
    <div class="account-flow">
      <p>
        Đang mở lại <strong>{reopenDomain}/{reopenName}</strong>. Đăng nhập xong thì bấm Lưu —
        state cũ bị ghi đè, nhãn giữ nguyên.
      </p>
      <div class="recipe-actions">
        <button class="button" disabled={reopenBusy} onclick={saveReopen}>Lưu</button>
        <button class="button secondary" onclick={cancelReopen}>Hủy</button>
      </div>
    </div>
  {/if}
</section>

{#if dialogDomain !== null}
  <AccountDialog domain={dialogDomain} lockDomain={Boolean(dialogDomain)} onclose={() => (dialogDomain = null)} />
{/if}
