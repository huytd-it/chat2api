<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { accounts, accountsLoading, refreshAccounts, refreshRecipes } from "$lib/sync";
  import {
    startDomainLogin,
    completeDomainLogin,
    cancelAccountLogin,
    reopenDomainAccount,
    deleteDomainAccount,
  } from "$lib/api";
  import LiveView from "$lib/components/LiveView.svelte";

  // Một phiên đăng nhập đang mở: browser đã bật, chờ người dùng đăng nhập xong
  // rồi đặt tên để lưu state.
  let sessionId = $state<string | null>(null);
  let sessionDomain = $state("");
  let accountName = $state("");
  let nameLocked = $state(false);
  let saving = $state(false);

  let newDomain = $state("");
  let busyKey = $state<string | null>(null);

  onMount(() => {
    refreshAccounts();
  });

  function resetFlow() {
    sessionId = null;
    sessionDomain = "";
    accountName = "";
    nameLocked = false;
  }

  async function openLogin(domain: string, name = "") {
    const target = domain.trim().toLowerCase();
    if (!target) {
      showToast("Nhập domain trước, ví dụ chat.qwen.ai");
      return;
    }
    busyKey = name ? `${target}/${name}` : target;
    try {
      const started = name
        ? await reopenDomainAccount($apiKey, target, name)
        : await startDomainLogin($apiKey, target);
      sessionId = started.session_id;
      sessionDomain = started.domain ?? target;
      accountName = name;
      nameLocked = Boolean(name);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyKey = null;
    }
  }

  async function saveAccount() {
    const name = accountName.trim();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
      showToast("Tên account chỉ gồm chữ thường, số và dấu -");
      return;
    }
    if (!sessionId) return;
    saving = true;
    try {
      await completeDomainLogin($apiKey, sessionId, sessionDomain, name);
      showToast(`Đã lưu ${sessionDomain}/${name}`);
      resetFlow();
      newDomain = "";
      await Promise.all([refreshAccounts(), refreshRecipes()]);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      saving = false;
    }
  }

  async function cancelFlow() {
    if (sessionId) await cancelAccountLogin($apiKey, sessionDomain, sessionId).catch(() => {});
    resetFlow();
  }

  async function removeAccount(domain: string, name: string) {
    if (!confirm(`Xóa account ${domain}/${name}? Recipe dùng domain này sẽ mất phiên đăng nhập.`))
      return;
    busyKey = `${domain}/${name}`;
    try {
      await deleteDomainAccount($apiKey, domain, name);
      showToast(`Đã xóa ${domain}/${name}`);
      await Promise.all([refreshAccounts(), refreshRecipes()]);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyKey = null;
    }
  }

  function formatWhen(seconds: number): string {
    return new Date(seconds * 1000).toLocaleString();
  }
</script>

<section class="view page">
  <div class="page-heading">
    <h1>Accounts</h1>
    <p>
      Account thuộc về <strong>domain</strong>, không thuộc recipe. Đăng nhập một lần là mọi recipe
      trên cùng domain dùng lại được ngay.
    </p>
  </div>

  <article class="panel dash-card">
    <div class="panel-head">
      <div>
        <h2>Thêm account</h2>
        <p>Mở browser trên máy chạy server để bạn đăng nhập thủ công.</p>
      </div>
    </div>
    <div class="dash-body">
      <div class="url-row">
        <input
         
          type="text"
          placeholder="chat.qwen.ai"
          bind:value={newDomain}
          disabled={Boolean(sessionId)}
        />
        <button
          class="button"
          disabled={Boolean(sessionId) || busyKey === newDomain.trim().toLowerCase()}
          onclick={() => openLogin(newDomain)}
        >
          Mở browser đăng nhập
        </button>
      </div>

      {#if sessionId}
        <div class="account-flow">
          <p>
            Browser đã mở cho <strong>{sessionDomain}</strong>. Đăng nhập xong thì đặt tên rồi bấm
            Lưu — state sẽ dùng chung cho mọi recipe của domain này.
          </p>
          <div class="url-row">
            <input
             
              type="text"
              placeholder="ten-account"
              bind:value={accountName}
              disabled={nameLocked}
            />
            <button class="button" disabled={saving} onclick={saveAccount}>Lưu</button>
          </div>
          <button class="button secondary small" onclick={cancelFlow}>Hủy</button>
          <LiveView watchId={sessionId} />
        </div>
      {/if}
    </div>
  </article>

  {#if $accountsLoading && !$accounts.length}
    <p class="hint">Đang nạp accounts…</p>
  {:else if !$accounts.length}
    <p class="hint">Chưa có domain nào. Thêm account đầu tiên ở trên.</p>
  {/if}

  {#each $accounts as domain (domain.domain)}
    <article class="panel dash-card">
      <div class="panel-head">
        <div>
          <h2>{domain.domain}</h2>
          <p>
            {#if domain.recipes.length}
              Dùng bởi: {domain.recipes.join(", ")}
            {:else}
              Chưa recipe nào dùng domain này.
            {/if}
          </p>
        </div>
        <button
          class="button secondary small"
          disabled={Boolean(sessionId)}
          onclick={() => openLogin(domain.domain)}
        >
          Thêm account
        </button>
      </div>
      <div class="dash-body">
        {#if domain.accounts.length}
          <table class="data-table">
            <thead>
              <tr>
                <th>Account</th>
                <th>Cập nhật</th>
                <th class="col-actions">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {#each domain.accounts as account (account.name)}
                <tr>
                  <td><span class="mono-sm">{account.name}</span></td>
                  <td class="hint">{formatWhen(account.updated_at)}</td>
                  <td class="recipe-actions">
                    <button
                      class="button secondary small"
                      disabled={Boolean(sessionId) ||
                        busyKey === `${domain.domain}/${account.name}`}
                      onclick={() => openLogin(domain.domain, account.name)}
                    >
                      Đăng nhập lại
                    </button>
                    <button
                      class="button danger small"
                      disabled={busyKey === `${domain.domain}/${account.name}`}
                      onclick={() => removeAccount(domain.domain, account.name)}
                    >
                      Xóa
                    </button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        {:else}
          <p class="alert amber">
            Chưa có account — recipe của domain này đang chạy ẩn danh và sẽ hết lượt dùng thử.
          </p>
        {/if}
      </div>
    </article>
  {/each}
</section>
