<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, headedBrowser, showToast } from "$lib/stores";
  import {
    closeProfile,
    fetchProfiles,
    fetchSettings,
    saveSettings,
    type ProfileList,
    type SettingField,
  } from "$lib/api";
  import { refreshModels, refreshRecipes } from "$lib/sync";

  let fields = $state<SettingField[]>([]);
  let values = $state<Record<string, string>>({});
  let envPath = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let restartKeys = $state<string[]>([]);

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
      values = Object.fromEntries(fields.map((f) => [f.key, f.value]));
      restartKeys = [];
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
</script>

<section class="view page">
  <div class="page-heading">
    <h1>Settings</h1>
    <p>
      Ghi thẳng vào <span class="mono-sm">{envPath || ".env"}</span>. Mục
      <em>reload</em> có hiệu lực ngay; mục <em>restart</em> cần chạy lại server.
    </p>
  </div>

  {#if restartKeys.length}
    <p class="alert amber">
      Đã lưu, nhưng {restartKeys.join(", ")} cần khởi động lại chat2api mới có hiệu lực.
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
