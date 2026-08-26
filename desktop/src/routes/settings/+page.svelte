<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, headedBrowser, showToast } from "$lib/stores";
  import {
    closeProfile,
    createApiKey,
    deleteApiKey,
    fetchApiKeys,
    fetchProfiles,
    fetchSettings,
    saveSettings,
    type ApiKeyInfo,
    type ApiKeyList,
    type ProfileList,
    type SettingField,
  } from "$lib/api";
  import { refreshModels, refreshRecipes } from "$lib/sync";

  let fields = $state<SettingField[]>([]);
  let values = $state<Record<string, string>>({});
  let envPath = $state("");
  let persisted = $state(true);
  let loading = $state(true);
  let saving = $state(false);
  let restartKeys = $state<string[]>([]);
  let shadowedKeys = $state<string[]>([]);

  // Bearer token của client này — khác hẳn khối `fields` bên dưới: nó không
  // nằm trong .env của server mà chỉ lưu cục bộ, nên có ô riêng ở trên cùng.
  let keyVisible = $state(false);
  let keyInput = $state($apiKey);

  function commitKey() {
    apiKey.set(keyInput.trim());
    refreshModels();
    refreshRecipes();
  }

  const groups = $derived([...new Set(fields.map((f) => f.group))]);

  onMount(load);

  async function load() {
    loading = true;
    try {
      const data = await fetchSettings($apiKey);
      fields = data.fields;
      envPath = data.env_path;
      persisted = data.persisted;
      values = Object.fromEntries(fields.map((f) => [f.key, f.value]));
      restartKeys = [];
      shadowedKeys = [];
    } catch (e) {
      showToast("Không nạp được settings: " + (e as Error).message);
    } finally {
      loading = false;
    }
  }

  async function save() {
    saving = true;
    try {
      const result = await saveSettings($apiKey, values);
      restartKeys = result.needs_restart;
      shadowedKeys = result.shadowed ?? [];
      showToast(`Đã lưu ${result.saved.length} thiết lập`);
      await refreshRecipes();
      // Nạp lại để ô secret hiển thị đúng trạng thái đã đặt hay chưa.
      const data = await fetchSettings($apiKey);
      fields = data.fields;
      values = Object.fromEntries(fields.map((f) => [f.key, f.value]));
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      saving = false;
    }
  }

  function fieldsOf(group: string): SettingField[] {
    return fields.filter((f) => f.group === group);
  }

  let profileData = $state<ProfileList | null>(null);

  async function loadProfiles() {
    try {
      profileData = await fetchProfiles($apiKey);
    } catch {
      profileData = null;
    }
  }

  async function shutProfile(name: string) {
    await closeProfile($apiKey, name);
    showToast(`Đã đóng profile ${name}`);
    await loadProfiles();
  }

  function lastUsed(ts: number | null): string {
    if (!ts) return "chưa dùng";
    const delta = Date.now() - ts;
    if (delta < 60_000) return "vừa xong";
    if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} phút trước`;
    if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} giờ trước`;
    return new Date(ts).toLocaleDateString();
  }

  onMount(loadProfiles);

  // --------------------------------------------------------------- API key
  let keyData = $state<ApiKeyList | null>(null);
  let newLabel = $state("");
  let newScopes = $state("chat,admin");
  // Key thô server trả về đúng một lần. Giữ trên màn hình cho tới khi người
  // dùng tự đóng — đóng sớm là mất hẳn, phải tạo key khác.
  let freshKey = $state<{ label: string; key: string } | null>(null);
  let keyBusy = $state(false);

  async function loadKeys() {
    try {
      keyData = await fetchApiKeys($apiKey);
    } catch {
      keyData = null;
    }
  }

  async function addKey() {
    const label = newLabel.trim();
    if (!label) {
      showToast("Đặt nhãn cho key để sau này biết nó của ai");
      return;
    }
    keyBusy = true;
    try {
      const created = await createApiKey($apiKey, label, newScopes);
      freshKey = { label: created.label, key: created.key };
      newLabel = "";
      // Key đầu tiên bật xác thực cho toàn server. Nạp thẳng vào ô key của
      // client này, nếu không lần gọi kế tiếp sẽ tự khoá mình ra ngoài.
      if (!$apiKey) {
        keyInput = created.key;
        commitKey();
      }
      await loadKeys();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      keyBusy = false;
    }
  }

  async function dropKey(row: ApiKeyInfo) {
    const purge = Boolean(row.revoked_at);
    const question = purge
      ? `Xóa hẳn key "${row.label}"? request_log sẽ không truy ngược được nữa.`
      : `Thu hồi key "${row.label}"? Client đang dùng nó sẽ nhận 401 ngay.`;
    if (!confirm(question)) return;
    keyBusy = true;
    try {
      await deleteApiKey($apiKey, row.id, purge);
      await loadKeys();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      keyBusy = false;
    }
  }

  onMount(loadKeys);
</script>

<section class="view page">
  <div class="page-heading">
    <h1>Settings</h1>
    <p>
      {#if persisted}
        Lưu trong kho SQLite của server. Mục <em>reload</em> có hiệu lực ngay; mục
        <em>restart</em> cần chạy lại server.
      {:else}
        Kho SQLite chưa mở nên đang ghi thẳng vào
        <span class="mono-sm">{envPath || ".env"}</span>. Mục <em>reload</em> có hiệu lực
        ngay; mục <em>restart</em> cần chạy lại server.
      {/if}
    </p>
  </div>

  {#if restartKeys.length}
    <p class="alert amber">
      Đã lưu, nhưng {restartKeys.join(", ")} cần khởi động lại chat2api mới có hiệu lực.
    </p>
  {/if}

  {#if shadowedKeys.length}
    <p class="alert amber">
      {shadowedKeys.join(", ")} đang được <span class="mono-sm">{envPath || ".env"}</span>
      ghim nên giá trị vừa lưu chưa dùng tới. Xóa dòng tương ứng khỏi .env rồi khởi động
      lại nếu muốn dùng giá trị trong kho.
    </p>
  {/if}

  <article class="panel dash-card">
    <div class="panel-head">
      <div>
        <h2>Client này</h2>
        <p>Chỉ lưu trên máy này, không ghi vào .env.</p>
      </div>
    </div>
    <div class="dash-body settings-grid">
      <div class="field">
        <label for="client-key">API key gửi kèm request</label>
        <div class="key-row">
          <input
            id="client-key"
            type={keyVisible ? "text" : "password"}
            autocomplete="off"
            placeholder="Bearer token"
            bind:value={keyInput}
            onchange={commitKey}
          />
          <button class="button secondary small" type="button" onclick={() => (keyVisible = !keyVisible)}>
            {keyVisible ? "Ẩn" : "Hiện"}
          </button>
        </div>
        <p class="field-help">Để trống nếu server chưa bật CHAT2API_KEYS.</p>
      </div>
      <div class="field">
        <label for="headed-default">Hiện cửa sổ browser khi chat</label>
        <select id="headed-default" bind:value={$headedBrowser}>
          <option value={false}>Chạy ẩn (headless)</option>
          <option value={true}>Hiện cửa sổ Chromium</option>
        </select>
        <p class="field-help">Áp dụng cho request gửi từ trang Sessions.</p>
      </div>
    </div>
  </article>

  <article class="panel dash-card">
    <div class="panel-head">
      <div>
        <h2>API key của server</h2>
        <p>
          {#if keyData?.enforced}
            Server đang yêu cầu Bearer token cho mọi request ngoài <code>/health</code>.
          {:else}
            Chưa có key nào — server đang mở cho bất kỳ ai gọi được cổng này.
          {/if}
        </p>
      </div>
      <button class="button secondary small" onclick={loadKeys}>Làm mới</button>
    </div>
    <div class="dash-body">
      {#if keyData && !keyData.persisted}
        <p class="alert amber">
          Kho SQLite chưa mở nên chưa tạo được key. Dùng
          <span class="mono-sm">CHAT2API_KEYS</span> trong .env, hoặc xem log khởi động.
        </p>
      {:else}
        {#if keyData?.bootstrap_keys}
          <p class="hint">
            Thêm {keyData.bootstrap_keys} key từ <span class="mono-sm">CHAT2API_KEYS</span>:
            key bootstrap không có hàng trong kho nên không liệt kê và không thu hồi được từ đây.
          </p>
        {/if}

        {#if freshKey}
          <div class="alert">
            <p>
              Key của <strong>{freshKey.label}</strong> — server chỉ lưu bản băm nên đây là
              lần duy nhất đọc được. Chép đi trước khi đóng.
            </p>
            <p class="mono-sm">{freshKey.key}</p>
            <button class="button secondary small" onclick={() => (freshKey = null)}>
              Đã chép, đóng
            </button>
          </div>
        {/if}

        <div class="profile-form">
          <div class="field">
            <label for="key-label">Nhãn</label>
            <input id="key-label" type="text" placeholder="desktop, ci, n8n…" bind:value={newLabel} />
          </div>
          <div class="field">
            <label for="key-scopes">Quyền</label>
            <select id="key-scopes" bind:value={newScopes}>
              <option value="chat,admin">chat + admin</option>
              <option value="chat">chỉ chat (/v1/*)</option>
              <option value="admin">chỉ admin (/admin/*)</option>
            </select>
          </div>
          <button class="button" disabled={keyBusy} onclick={addKey}>Tạo key</button>
        </div>

        {#if keyData?.keys.length}
          <ul class="profile-list">
            {#each keyData.keys as row (row.id)}
              <li>
                <span class="dot" class:on={!row.revoked_at} class:fault={!!row.revoked_at}></span>
                <span class="profile-body">
                  <span class="profile-name">
                    {row.label}
                    {#if row.revoked_at}<em>đã thu hồi</em>{/if}
                  </span>
                  <span class="profile-meta">
                    <code>{row.key_prefix}…</code>
                    <code>{row.scopes.join(" + ")}</code>
                    <code>{lastUsed(row.last_used_at)}</code>
                  </span>
                </span>
                <button class="button danger small" disabled={keyBusy} onclick={() => dropKey(row)}>
                  {row.revoked_at ? "Xóa hẳn" : "Thu hồi"}
                </button>
              </li>
            {/each}
          </ul>
        {:else}
          <p class="hint">Chưa có key nào trong kho.</p>
        {/if}
      {/if}
    </div>
  </article>

  {#if profileData}
    <article class="panel dash-card">
      <div class="panel-head">
        <div>
          <h2>Profile trình duyệt</h2>
          <p>
            {#if profileData.mode === "profile"}
              Một profile giữ đăng nhập của mọi domain, mỗi recipe một tab.
            {:else}
              Đang chạy <span class="mono-sm">storage_state</span> — mỗi recipe một context riêng.
            {/if}
          </p>
        </div>
        <button class="button secondary small" onclick={loadProfiles}>Làm mới</button>
      </div>
      <div class="dash-body">
        {#if profileData.mode === "storage_state"}
          <p class="alert amber">
            Chế độ profile đang tắt. Đặt <span class="mono-sm">BROWSER_PROFILE_MODE=profile</span>
            trong <span class="mono-sm">.env</span> rồi khởi động lại nếu muốn một profile đăng nhập
            nhiều domain và chạy nhiều tab song song.
          </p>
        {/if}
        {#if profileData.profiles.length}
          <ul class="profile-list">
            {#each profileData.profiles as profile (profile.id)}
              <li>
                <span class="dot" class:on={profile.open} class:fault={profile.locked && !profile.open}></span>
                <span class="profile-body">
                  <span class="profile-name">
                    {profile.name}
                    {#if profile.is_default}<em>mặc định</em>{/if}
                  </span>
                  <span class="profile-meta">
                    <code>{profile.domains} domain</code>
                    <code>{profile.tabs}/{profile.max_tabs} tab</code>
                    <code>{lastUsed(profile.last_used_at)}</code>
                  </span>
                </span>
                {#if profile.open}
                  <button class="button secondary small" onclick={() => shutProfile(profile.name)}>
                    Đóng
                  </button>
                {:else if profile.locked}
                  <span class="hint">tiến trình khác giữ</span>
                {/if}
              </li>
            {/each}
          </ul>
          <p class="hint">
            Tối đa {profileData.max_profiles} profile mở cùng lúc ·
            <span class="mono-sm">{profileData.profiles_dir}</span>
          </p>
        {:else}
          <p class="hint">Chưa có profile nào. Profile được tạo ở request đầu tiên.</p>
        {/if}
      </div>
    </article>
  {/if}

  {#if loading}
    <p class="hint">Đang nạp…</p>
  {:else}
    {#each groups as group (group)}
      <article class="panel dash-card">
        <div class="panel-head">
          <div><h2>{group}</h2></div>
        </div>
        <div class="dash-body settings-grid">
          {#each fieldsOf(group) as field (field.key)}
            <div class="field">
              <label for={"set-" + field.key}>
                {field.label}
                <span class="apply-tag" class:restart={field.apply === "restart"}>
                  {field.apply}
                </span>
                {#if field.env_locked}
                  <span class="apply-tag restart">.env</span>
                {/if}
              </label>

              {#if field.type === "bool"}
                <select id={"set-" + field.key} bind:value={values[field.key]}>
                  <option value="true">Bật</option>
                  <option value="false">Tắt</option>
                </select>
              {:else if field.type === "choice"}
                <select id={"set-" + field.key} bind:value={values[field.key]}>
                  {#each field.choices ?? [] as choice (choice)}
                    <option value={choice}>{choice}</option>
                  {/each}
                </select>
              {:else if field.type === "secret"}
                <input
                  id={"set-" + field.key}
                 
                  type="password"
                  placeholder={field.is_set ? "••••• (để trống = giữ nguyên)" : "chưa đặt"}
                  bind:value={values[field.key]}
                />
              {:else}
                <input
                  id={"set-" + field.key}
                 
                  type={field.type === "int" ? "number" : "text"}
                  min={field.type === "int" ? 0 : undefined}
                  bind:value={values[field.key]}
                />
              {/if}

              {#if field.env_locked}
                <p class="field-help">
                  Đang lấy từ .env — sửa ở đây sẽ được lưu nhưng .env vẫn thắng.
                </p>
              {/if}
              {#if field.help}
                <p class="field-help">{field.help}</p>
              {/if}
            </div>
          {/each}
        </div>
      </article>
    {/each}

    <div class="shortcut-row">
      <button class="button" disabled={saving} onclick={save}>Lưu thay đổi</button>
      <button class="button secondary" disabled={saving} onclick={load}>Hoàn tác</button>
    </div>
  {/if}
</section>
