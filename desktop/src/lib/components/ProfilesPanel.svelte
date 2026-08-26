<script lang="ts">
  // Panel dưới cùng của trang Integrations (docs/design-v2.md §6): profile là
  // hạ tầng, không phải việc hằng ngày, nên nó nằm dưới hai panel kia.
  import { apiKey, showToast } from "../stores";
  import { profiles, profilesLoading, profilesMeta, refreshIntegrations } from "../sync";
  import {
    closeProfile,
    createProfile,
    deleteProfile,
    detectProfileDomains,
    openProfile,
    updateProfile,
    type ProfileInfo,
  } from "../api";
  import AccountDialog from "./AccountDialog.svelte";

  let creating = $state(false);
  let newName = $state("");
  let newMaxTabs = $state(4);
  let newHeadless = $state(true);
  let busyId = $state<number | null>(null);

  let editingId = $state<number | null>(null);
  let editMaxTabs = $state(4);
  let editHeadless = $state(true);
  let editNotes = $state("");

  let watchProfile = $state("");
  let suggestions = $state<Record<number, string[]>>({});
  let dialogProfile = $state<string | null>(null);

  function statusOf(p: ProfileInfo): { label: string; cls: string } {
    if (p.locked && !p.open) return { label: "bị khoá", cls: "fault" };
    if (p.open) return { label: `đang chạy · ${p.tabs} tab`, cls: "on" };
    return { label: "rảnh", cls: "" };
  }

  async function onCreate() {
    const name = newName.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
      showToast("Tên profile chỉ gồm chữ thường, số và dấu -");
      return;
    }
    busyId = -1;
    try {
      await createProfile($apiKey, name, { max_tabs: newMaxTabs, headless: newHeadless });
      showToast(`Đã tạo profile ${name}`);
      newName = "";
      creating = false;
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }

  function startEdit(p: ProfileInfo) {
    editingId = p.id;
    editMaxTabs = p.max_tabs;
    editHeadless = p.headless === 1;
    editNotes = p.notes ?? "";
  }

  async function saveEdit(p: ProfileInfo) {
    busyId = p.id;
    try {
      await updateProfile($apiKey, p.id, {
        max_tabs: editMaxTabs,
        headless: editHeadless,
        notes: editNotes,
      });
      editingId = null;
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }

  async function makeDefault(p: ProfileInfo) {
    busyId = p.id;
    try {
      await updateProfile($apiKey, p.id, { is_default: true });
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }

  async function onOpen(p: ProfileInfo) {
    busyId = p.id;
    try {
      const res = await openProfile($apiKey, p.id);
      watchProfile = p.name;
      showToast(res.headless
        ? `${p.name} đang chạy nền nên không có cửa sổ mới — bấm Đóng rồi Mở lại.`
        : `Đã mở cửa sổ ${p.name}. Đăng nhập rồi bấm “Dò domain”.`);
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }

  async function onDetect(p: ProfileInfo) {
    busyId = p.id;
    try {
      const res = await detectProfileDomains($apiKey, p.id);
      suggestions = { ...suggestions, [p.id]: res.suggested };
      if (!res.suggested.length) showToast(`${p.name}: không có domain nào chưa khai báo.`);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }

  async function onClose(p: ProfileInfo) {
    busyId = p.id;
    try {
      await closeProfile($apiKey, p.name);
      if (watchProfile === p.name) watchProfile = "";
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }

  async function onDelete(p: ProfileInfo) {
    // Thư mục Chromium giữ toàn bộ đăng nhập của profile — hỏi riêng, vì xoá
    // hàng DB thì khôi phục được, xoá thư mục thì không.
    if (!confirm(`Xóa profile ${p.name}?`)) return;
    const purge = confirm(`Xóa luôn thư mục ${p.user_data_dir}? Mọi đăng nhập trong đó mất hẳn.`);
    busyId = p.id;
    try {
      await deleteProfile($apiKey, p.id, purge);
      showToast(`Đã xóa profile ${p.name}`);
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busyId = null;
    }
  }
</script>

<section class="panel dash-card">
  <div class="panel-head">
    <div>
      <h2>Profile trình duyệt</h2>
      <p>
        Một profile = một thư mục Chromium giữ đăng nhập của mọi domain cùng lúc, mỗi recipe
        một tab.
      </p>
    </div>
    <button class="button secondary small" onclick={() => (creating = !creating)}>
      {creating ? "Hủy" : "+ Profile mới"}
    </button>
  </div>

  <div class="dash-body">
    {#if $profilesMeta && !$profilesMeta.persisted}
      <p class="alert amber">
        Kho SQLite chưa mở nên chưa quản lý được profile. Xem log khởi động để biết vì sao.
      </p>
    {:else if $profilesMeta}
      <p class="hint">
        Chế độ: <strong>{$profilesMeta.mode}</strong> · tối đa {$profilesMeta.max_profiles} profile
        mở cùng lúc · thư mục <span class="mono-sm">{$profilesMeta.profiles_dir}</span>
      </p>
      {#if $profilesMeta.mode === "storage_state"}
        <p class="hint">
          Router vẫn chạy bằng storage_state. Profile ở đây dùng được để đăng nhập tay và gom
          nhiều domain; đặt <span class="mono-sm">BROWSER_PROFILE_MODE=profile</span> nếu muốn
          recipe chạy trong profile.
        </p>
      {/if}
    {/if}

    {#if creating}
      <div class="profile-form">
        <div class="field">
          <label for="profile-name">Tên</label>
          <input id="profile-name" type="text" placeholder="main" bind:value={newName} />
        </div>
        <div class="field">
          <label for="profile-tabs">Số tab tối đa</label>
          <input id="profile-tabs" type="number" min="1" max="32" bind:value={newMaxTabs} />
        </div>
        <label class="headed-toggle">
          <input type="checkbox" bind:checked={newHeadless} />
          Chạy ẩn (headless)
        </label>
        <button class="button" disabled={busyId === -1} onclick={onCreate}>Tạo</button>
      </div>
    {/if}

    {#if $profilesLoading && !$profiles.length}
      <p class="hint">Đang nạp profiles…</p>
    {:else if !$profiles.length && $profilesMeta?.persisted}
      <p class="hint">Chưa có profile nào. Tạo một cái để gom đăng nhập nhiều domain.</p>
    {/if}

    {#each $profiles as p (p.id)}
      {@const status = statusOf(p)}
      <div class="profile-row">
        <div class="profile-line">
          <span class="dot {status.cls}"></span>
          <span class="site-slug">{p.name}</span>
          {#if p.is_default}<span class="login-badge">mặc định</span>{/if}
          <span class="hint">{p.domains} domain · {p.max_tabs} tab tối đa · {status.label}</span>
          <span class="recipe-actions">
            <button class="button secondary small" disabled={busyId === p.id} onclick={() => onOpen(p)}>
              Mở
            </button>
            <button class="button secondary small" disabled={busyId === p.id || !p.open}
                    onclick={() => onDetect(p)}>
              Dò domain
            </button>
            <button class="button secondary small" disabled={busyId === p.id}
                    onclick={() => (dialogProfile = p.name)}>
              + Account
            </button>
            <button class="button secondary small" disabled={busyId === p.id}
                    onclick={() => (editingId === p.id ? (editingId = null) : startEdit(p))}>
              Sửa
            </button>
            {#if p.open}
              <button class="button secondary small" disabled={busyId === p.id} onclick={() => onClose(p)}>
                Đóng
              </button>
            {/if}
            <button class="button danger small" disabled={busyId === p.id} onclick={() => onDelete(p)}>
              Xóa
            </button>
          </span>
        </div>

        {#if p.accounts.length}
          <div class="saved-accounts">
            {#each p.accounts as account (account.id)}
              <span class="saved-account">{account.host} / {account.label}</span>
            {/each}
          </div>
        {/if}

        {#if suggestions[p.id]?.length}
          <p class="alert amber">
            Còn đăng nhập chưa khai báo: {suggestions[p.id].join(", ")} — bấm “+ Account” để thêm.
          </p>
        {/if}

        {#if editingId === p.id}
          <div class="profile-form">
            <div class="field">
              <label for="edit-tabs-{p.id}">Số tab tối đa</label>
              <input id="edit-tabs-{p.id}" type="number" min="1" max="32" bind:value={editMaxTabs} />
            </div>
            <div class="field">
              <label for="edit-notes-{p.id}">Ghi chú</label>
              <input id="edit-notes-{p.id}" type="text" bind:value={editNotes} />
            </div>
            <label class="headed-toggle">
              <input type="checkbox" bind:checked={editHeadless} />
              Chạy ẩn (headless)
            </label>
            <button class="button" disabled={busyId === p.id} onclick={() => saveEdit(p)}>Lưu</button>
            {#if !p.is_default}
              <button class="button secondary" disabled={busyId === p.id} onclick={() => makeDefault(p)}>
                Đặt làm mặc định
              </button>
            {/if}
          </div>
        {/if}
      </div>
    {/each}

    {#if watchProfile}
      <div class="account-flow">
        <p>Cửa sổ profile <strong>{watchProfile}</strong> đang mở trên máy chạy server — đăng nhập rồi bấm “Dò domain”.</p>
        <button class="button secondary small" onclick={() => (watchProfile = "")}>Ẩn nhắc này</button>
      </div>
    {/if}
  </div>
</section>

{#if dialogProfile !== null}
  <AccountDialog profile={dialogProfile} onclose={() => (dialogProfile = null)} />
{/if}
