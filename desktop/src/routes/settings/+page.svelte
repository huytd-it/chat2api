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
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Badge } from "$lib/components/ui/badge";
  import { Skeleton } from "$lib/components/ui/skeleton";
  import * as Card from "$lib/components/ui/card";
  import * as Tabs from "$lib/components/ui/tabs";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import {
    Browser,
    CircleNotch,
    Copy,
    Eye,
    EyeSlash,
    Gauge,
    Key,
    Repeat,
    ShieldCheck,
    Trash,
    UserCircle,
    Warning,
    WarningCircle,
    X,
  } from "phosphor-svelte";

  let fields = $state<SettingField[]>([]);
  let values = $state<Record<string, string>>({});
  let envPath = $state("");
  let persisted = $state(true);
  let loading = $state(true);
  let loadError = $state("");
  let saving = $state(false);
  let restartKeys = $state<string[]>([]);
  let shadowedKeys = $state<string[]>([]);

  let activeTab = $state("client");

  // Bearer token của client này — khác hẳn khối `fields` bên dưới: nó không
  // nằm trong .env của server mà chỉ lưu cục bộ, nên có ô riêng ở trên cùng.
  let keyVisible = $state(false);
  let keyInput = $state($apiKey);

  function commitKey() {
    apiKey.set(keyInput.trim());
    refreshModels();
    refreshRecipes();
  }

  const reloadGroups = $derived([...new Set(fields.filter((f) => f.apply !== "restart").map((f) => f.group))]);
  const restartGroups = $derived([...new Set(fields.filter((f) => f.apply === "restart").map((f) => f.group))]);
  const hasRestartFields = $derived(restartGroups.length > 0);

  onMount(load);

  async function load() {
    loading = true;
    loadError = "";
    try {
      const data = await fetchSettings($apiKey);
      fields = data.fields;
      envPath = data.env_path;
      persisted = data.persisted;
      values = Object.fromEntries(fields.map((f) => [f.key, f.value]));
      restartKeys = [];
      shadowedKeys = [];
    } catch (e) {
      loadError = "Không nạp được settings: " + (e as Error).message;
      showToast(loadError);
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

  function fieldsOf(group: string, only: "reload" | "restart" = "reload"): SettingField[] {
    return fields.filter((f) => f.group === group && f.apply === (only === "restart" ? "restart" : "reload"));
  }

  let revealedSecrets = $state<Record<string, boolean>>({});

  let profileData = $state<ProfileList | null>(null);
  let profilesLoading = $state(true);
  let profilesError = $state("");
  let profileBusy = $state<string | null>(null);

  async function loadProfiles() {
    profilesLoading = true;
    profilesError = "";
    try {
      profileData = await fetchProfiles($apiKey);
    } catch (e) {
      profileData = null;
      profilesError = "Không nạp được browser profiles: " + (e as Error).message;
    } finally {
      profilesLoading = false;
    }
  }

  async function shutProfile(name: string) {
    profileBusy = name;
    profilesError = "";
    try {
      await closeProfile($apiKey, name);
      showToast(`Đã đóng profile ${name}`);
      await loadProfiles();
    } catch (e) {
      profilesError = (e as Error).message;
      showToast(profilesError);
    } finally {
      profileBusy = null;
    }
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
  let freshReveal = $state(false);
  let keyBusy = $state(false);
  let keysLoading = $state(true);
  let keysError = $state("");
  let dropTarget = $state<ApiKeyInfo | null>(null);

  async function loadKeys() {
    keysLoading = true;
    keysError = "";
    try {
      keyData = await fetchApiKeys($apiKey);
    } catch (e) {
      keyData = null;
      keysError = "Không nạp được API keys: " + (e as Error).message;
    } finally {
      keysLoading = false;
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
      freshReveal = false;
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

  async function confirmDropKey() {
    const row = dropTarget;
    if (!row) return;
    dropTarget = null;
    keyBusy = true;
    try {
      await deleteApiKey($apiKey, row.id, Boolean(row.revoked_at));
      await loadKeys();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      keyBusy = false;
    }
  }

  async function copyFreshKey() {
    if (!freshKey) return;
    try {
      await navigator.clipboard.writeText(freshKey.key);
      showToast("Đã chép key vào clipboard");
    } catch {
      showToast("Không chép được — hãy tự bôi đen key");
    }
  }

  onMount(loadKeys);
</script>

{#snippet fieldRow(field: SettingField)}
  <div class="grid gap-1.5">
    <label for={"set-" + field.key} class="flex flex-wrap items-center gap-1.5 text-sm font-medium">
      {field.label}
      <Badge variant={field.apply === "restart" ? "secondary" : "outline"} class="font-normal">
        {field.apply}
      </Badge>
      {#if field.env_locked}
        <Badge variant="secondary" class="font-data font-normal">.env</Badge>
      {/if}
    </label>

    {#if field.type === "bool"}
      <select
        id={"set-" + field.key}
        class="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        bind:value={values[field.key]}
      >
        <option value="true">Bật</option>
        <option value="false">Tắt</option>
      </select>
    {:else if field.type === "choice"}
      <select
        id={"set-" + field.key}
        class="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
        bind:value={values[field.key]}
      >
        {#each field.choices ?? [] as choice (choice)}
          <option value={choice}>{choice}</option>
        {/each}
      </select>
    {:else if field.type === "secret"}
      <div class="flex gap-1.5">
        <Input
          id={"set-" + field.key}
          type={revealedSecrets[field.key] ? "text" : "password"}
          autocomplete="off"
          class="font-data"
          placeholder={field.is_set ? "••••• (để trống = giữ nguyên)" : "chưa đặt"}
          bind:value={values[field.key]}
        />
        <Button
          variant="outline"
          size="icon-sm"
          type="button"
          aria-label={revealedSecrets[field.key] ? "Ẩn bí mật" : "Hiện bí mật"}
          aria-pressed={revealedSecrets[field.key]}
          onclick={() => (revealedSecrets = { ...revealedSecrets, [field.key]: !revealedSecrets[field.key] })}
        >
          {#if revealedSecrets[field.key]}<EyeSlash />{:else}<Eye />{/if}
        </Button>
      </div>
    {:else}
      <Input
        id={"set-" + field.key}
        type={field.type === "int" ? "number" : "text"}
        min={field.type === "int" ? 0 : undefined}
        bind:value={values[field.key]}
      />
    {/if}

    {#if field.env_locked}
      <p class="text-xs text-muted-foreground">
        Đang lấy từ .env — sửa ở đây sẽ được lưu nhưng .env vẫn thắng.
      </p>
    {/if}
    {#if field.help}
      <p class="text-xs text-muted-foreground">{field.help}</p>
    {/if}
  </div>
{/snippet}

{#snippet saveBar()}
  <div class="flex items-center justify-between gap-3 rounded-lg border bg-card p-3 sm:p-4" aria-live="polite">
    <p class="text-xs text-muted-foreground">
      {#if saving}
        Đang lưu…
      {:else}
        Mục <em>reload</em> có hiệu lực ngay; mục <em>restart</em> cần chạy lại server.
      {/if}
    </p>
    <div class="flex shrink-0 gap-2">
      <Button variant="outline" disabled={saving} onclick={load}>Hoàn tác</Button>
      <Button disabled={saving} onclick={save}>
        {#if saving}<CircleNotch class="animate-spin" />{/if}
        {saving ? "Đang lưu" : "Lưu thay đổi"}
      </Button>
    </div>
  </div>
{/snippet}

<section class="h-full overflow-y-auto" aria-labelledby="settings-title">
  <div class="mx-auto flex w-full max-w-5xl flex-col gap-5 p-4 sm:p-6 lg:p-8">
    <header>
      <h1 id="settings-title" class="text-xl font-semibold tracking-tight">Settings</h1>
      <p class="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">
        {#if persisted}
          Lưu trong kho SQLite của server.
        {:else}
          Kho SQLite chưa mở nên đang ghi thẳng vào
          <span class="font-data">{envPath || ".env"}</span>.
        {/if}
      </p>
    </header>

    <div class="flex flex-col gap-3" aria-live="polite">
      {#if restartKeys.length}
        <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="status">
          <WarningCircle class="mt-0.5 shrink-0" />
          <span>
            Đã lưu, nhưng {restartKeys.join(", ")} cần khởi động lại chat2api mới có hiệu lực.
          </span>
        </div>
      {/if}
      {#if shadowedKeys.length}
        <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="status">
          <WarningCircle class="mt-0.5 shrink-0" />
          <span>
            {shadowedKeys.join(", ")} đang được <span class="font-data">{envPath || ".env"}</span>
            ghim nên giá trị vừa lưu chưa dùng tới. Xóa dòng tương ứng khỏi .env rồi khởi động
            lại nếu muốn dùng giá trị trong kho.
          </span>
        </div>
      {/if}
    </div>

    <Tabs.Root bind:value={activeTab} class="w-full">
      <Tabs.List class="w-full max-w-full overflow-x-auto sm:w-fit">
        <Tabs.Trigger value="client"><Key /> Client</Tabs.Trigger>
        <Tabs.Trigger value="general"><Gauge /> Runtime</Tabs.Trigger>
        <Tabs.Trigger value="profiles"><Browser /> Browser profiles</Tabs.Trigger>
        <Tabs.Trigger value="keys"><ShieldCheck /> API keys</Tabs.Trigger>
        {#if hasRestartFields}
          <Tabs.Trigger value="restart"><Warning /> Restart changes</Tabs.Trigger>
        {/if}
      </Tabs.List>

      <!-- Client authentication -->
      <Tabs.Content value="client" class="mt-3">
        <Card.Root aria-labelledby="client-title">
          <Card.Header class="border-b">
            <div class="flex items-start gap-3">
              <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Key size={19} />
              </div>
              <div>
                <Card.Title id="client-title">Client authentication</Card.Title>
                <Card.Description>
                  Chỉ lưu trên máy này, không ghi vào .env. Để trống nếu server chưa bật CHAT2API_KEYS.
                </Card.Description>
              </div>
            </div>
          </Card.Header>
          <Card.Content class="grid gap-4 p-4 sm:p-6">
            <div class="grid gap-1.5">
              <label for="client-key" class="text-sm font-medium">API key gửi kèm request</label>
              <div class="flex gap-1.5">
                <Input
                  id="client-key"
                  type={keyVisible ? "text" : "password"}
                  autocomplete="off"
                  placeholder="Bearer token"
                  class="font-data"
                  bind:value={keyInput}
                  onchange={commitKey}
                />
                <Button
                  variant="outline"
                  size="icon-sm"
                  type="button"
                  aria-label={keyVisible ? "Ẩn API key" : "Hiện API key"}
                  aria-pressed={keyVisible}
                  onclick={() => (keyVisible = !keyVisible)}
                >
                  {#if keyVisible}<EyeSlash />{:else}<Eye />{/if}
                </Button>
              </div>
              <p class="text-xs text-muted-foreground" aria-live="polite">
                {$apiKey
                  ? "Key này đang dùng cho mọi request chat + admin từ máy này."
                  : "Chưa có key — mọi request hiện không có Bearer token."}
              </p>
            </div>
          </Card.Content>
        </Card.Root>
      </Tabs.Content>

      <!-- Runtime / general settings -->
      <Tabs.Content value="general" class="mt-3">
        <div class="flex flex-col gap-4">
          <Card.Root aria-labelledby="runtime-title">
            <Card.Header class="border-b">
              <div class="flex items-start gap-3">
                <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Gauge size={19} />
                </div>
                <div>
                  <Card.Title id="runtime-title">Runtime</Card.Title>
                  <Card.Description>Các thiết lập tác động ngay đến cách server chạy.</Card.Description>
                </div>
              </div>
            </Card.Header>
            <Card.Content class="grid gap-4 p-4 sm:p-6">
              <div class="grid gap-1.5">
                <label for="headed-default" class="text-sm font-medium">Hiện cửa sổ browser khi chat</label>
                <select
                  id="headed-default"
                  class="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30 sm:w-72"
                  bind:value={$headedBrowser}
                >
                  <option value={false}>Chạy ẩn (headless)</option>
                  <option value={true}>Hiện cửa sổ Chromium</option>
                </select>
                <p class="text-xs text-muted-foreground">Áp dụng cho request gửi từ trang Sessions.</p>
              </div>
            </Card.Content>
          </Card.Root>

          {#if loading}
            <div class="grid gap-4" aria-label="Đang nạp settings" aria-busy="true">
              <Card.Root>
                <Card.Content class="grid gap-4 p-4 sm:p-6">
                  <div class="grid gap-2">
                    <Skeleton class="h-4 w-32" />
                    <Skeleton class="h-8 w-full" />
                    <Skeleton class="h-3 w-2/3" />
                  </div>
                  <div class="grid gap-2">
                    <Skeleton class="h-4 w-32" />
                    <Skeleton class="h-8 w-full" />
                    <Skeleton class="h-3 w-1/2" />
                  </div>
                </Card.Content>
              </Card.Root>
            </div>
          {:else if loadError}
            <div class="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert">
              <span>{loadError}</span>
              <Button variant="outline" size="sm" onclick={load}><Repeat /> Thử lại</Button>
            </div>
          {:else if !reloadGroups.length}
            <div class="flex min-h-36 flex-col items-center justify-center rounded-lg border bg-card p-6 text-center">
              <Gauge class="mb-2 text-muted-foreground" size={28} />
              <p class="font-medium">Không có thiết lập áp dụng ngay</p>
              <p class="mt-1 text-sm text-muted-foreground">Xem tab Restart changes cho các mục cần khởi động lại.</p>
            </div>
          {:else}
            {#each reloadGroups as group (group)}
              <Card.Root>
                <Card.Header class="border-b">
                  <Card.Title class="text-base">{group}</Card.Title>
                </Card.Header>
                <Card.Content class="grid gap-5 p-4 sm:grid-cols-2 sm:p-6">
                  {#each fieldsOf(group, "reload") as field (field.key)}
                    {@render fieldRow(field)}
                  {/each}
                </Card.Content>
              </Card.Root>
            {/each}
            {@render saveBar()}
          {/if}
        </div>
      </Tabs.Content>

      <!-- Browser profiles -->
      <Tabs.Content value="profiles" class="mt-3">
        <Card.Root aria-labelledby="profiles-title">
          <Card.Header class="flex-row items-center justify-between gap-4 border-b">
            <div class="flex items-start gap-3">
              <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Browser size={19} />
              </div>
              <div>
                <Card.Title id="profiles-title">Browser profiles</Card.Title>
                <Card.Description>
                  {#if profileData}
                    {#if profileData.mode === "profile"}
                      Một profile giữ đăng nhập của mọi domain, mỗi recipe một tab.
                    {:else}
                      Đang chạy <span class="font-data">storage_state</span> — mỗi recipe một context riêng.
                    {/if}
                  {:else}
                    Hạ tầng Chromium dùng chung đăng nhập cho nhiều domain.
                  {/if}
                </Card.Description>
              </div>
            </div>
            <Button variant="outline" size="sm" disabled={profilesLoading} onclick={loadProfiles}>
              <Repeat class={profilesLoading ? "animate-spin" : ""} /> {profilesLoading ? "Đang tải" : "Làm mới"}
            </Button>
          </Card.Header>
          <Card.Content class="grid gap-4 p-4 sm:p-6">
            {#if profilesError}
              <div class="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert">
                <span>{profilesError}</span>
                <Button variant="outline" size="sm" onclick={loadProfiles}><Repeat /> Thử lại</Button>
              </div>
            {:else if profilesLoading}
              <div class="grid gap-3" role="status" aria-live="polite" aria-busy="true">
                {#each [0, 1, 2] as _, i (i)}
                  <div class="rounded-lg border bg-card p-4">
                    <div class="flex items-start gap-3">
                      <Skeleton class="size-2.5 rounded-full" />
                      <div class="flex-1 gap-2">
                        <Skeleton class="h-4 w-32" />
                        <Skeleton class="mt-2 h-3 w-48" />
                      </div>
                    </div>
                  </div>
                {/each}
              </div>
            {:else if !profileData}
              <div class="flex min-h-36 flex-col items-center justify-center rounded-lg border bg-muted/10 p-6 text-center">
                <Browser class="mb-2 text-muted-foreground" size={28} />
                <p class="font-medium">Chưa nạp được profiles</p>
                <p class="mt-1 text-sm text-muted-foreground">Bấm “Làm mới” để thử lại.</p>
              </div>
            {:else if !profileData.persisted}
              <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="status">
                <WarningCircle class="mt-0.5 shrink-0" />
                <span>
                  Kho SQLite chưa mở nên chưa quản lý được profile. Xem log khởi động để biết vì sao.
                </span>
              </div>
            {:else}
              {#if profileData.mode === "storage_state"}
                <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="status">
                  <WarningCircle class="mt-0.5 shrink-0" />
                  <span>
                    Chế độ profile đang tắt. Đặt <span class="font-data">BROWSER_PROFILE_MODE=profile</span>
                    trong <span class="font-data">.env</span> rồi khởi động lại nếu muốn một profile đăng nhập
                    nhiều domain và chạy nhiều tab song song.
                  </span>
                </div>
              {/if}
              {#if profileData.profiles.length}
                <ul class="grid gap-3">
                  {#each profileData.profiles as profile (profile.id)}
                    <li class="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:flex-row sm:items-center">
                      <div class="flex min-w-0 flex-1 items-start gap-3">
                        <span
                          class:bg-success={profile.open}
                          class:bg-destructive={profile.locked && !profile.open}
                          class:bg-muted-foreground={!profile.open && !profile.locked}
                          class="mt-1.5 size-2.5 shrink-0 rounded-full"
                          aria-hidden="true"
                        ></span>
                        <div class="min-w-0">
                          <div class="flex flex-wrap items-center gap-2">
                            <span class="font-data text-sm font-semibold">{profile.name}</span>
                            {#if profile.is_default}<Badge variant="secondary">Mặc định</Badge>{/if}
                            {#if profile.locked && !profile.open}<Badge variant="destructive">Bị khoá</Badge>{/if}
                          </div>
                          <p class="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                            <code>{profile.domains} domain</code>
                            <code>{profile.tabs}/{profile.max_tabs} tab</code>
                            <code>{lastUsed(profile.last_used_at)}</code>
                          </p>
                        </div>
                      </div>
                      <div class="flex shrink-0 items-center gap-2">
                        {#if profile.open}
                          <Button
                            variant="secondary"
                            size="sm"
                            disabled={profileBusy === profile.name}
                            onclick={() => shutProfile(profile.name)}
                          >
                            {#if profileBusy === profile.name}<CircleNotch class="animate-spin" />{/if}
                            Đóng
                          </Button>
                        {:else if profile.locked}
                          <span class="text-xs text-muted-foreground">tiến trình khác giữ</span>
                        {/if}
                      </div>
                    </li>
                  {/each}
                </ul>
                <p class="text-xs leading-5 text-muted-foreground">
                  Tối đa {profileData.max_profiles} profile mở cùng lúc ·
                  <span class="break-all font-data">{profileData.profiles_dir}</span>
                </p>
              {:else}
                <div class="flex min-h-36 flex-col items-center justify-center rounded-lg border bg-muted/10 p-6 text-center">
                  <UserCircle class="mb-2 text-muted-foreground" size={28} />
                  <p class="font-medium">Chưa có profile</p>
                  <p class="mt-1 text-sm text-muted-foreground">Profile được tạo ở request đầu tiên.</p>
                </div>
              {/if}
            {/if}
          </Card.Content>
        </Card.Root>
      </Tabs.Content>

      <!-- API keys -->
      <Tabs.Content value="keys" class="mt-3">
        <Card.Root aria-labelledby="keys-title">
          <Card.Header class="flex-row items-center justify-between gap-4 border-b">
            <div class="flex items-start gap-3">
              <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <ShieldCheck size={19} />
              </div>
              <div>
                <Card.Title id="keys-title">API keys</Card.Title>
                <Card.Description>
                  {#if keyData}
                    {#if keyData.enforced}
                      Server đang yêu cầu Bearer token cho mọi request ngoài <code>/health</code>.
                    {:else}
                      Chưa có key nào — server đang mở cho bất kỳ ai gọi được cổng này.
                    {/if}
                  {:else}
                    Bearer token cho client và CI, lưu trong kho SQLite.
                  {/if}
                </Card.Description>
              </div>
            </div>
            <Button variant="outline" size="sm" disabled={keysLoading} onclick={loadKeys}>
              <Repeat class={keysLoading ? "animate-spin" : ""} /> {keysLoading ? "Đang tải" : "Làm mới"}
            </Button>
          </Card.Header>
          <Card.Content class="grid gap-4 p-4 sm:p-6">
            {#if keysError}
              <div class="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert">
                <span>{keysError}</span>
                <Button variant="outline" size="sm" onclick={loadKeys}><Repeat /> Thử lại</Button>
              </div>
            {:else if keysLoading}
              <div class="grid gap-3" role="status" aria-live="polite" aria-busy="true">
                {#each [0, 1, 2] as _, i (i)}
                  <div class="rounded-lg border bg-card p-4">
                    <Skeleton class="h-4 w-40" />
                    <Skeleton class="mt-2 h-3 w-56" />
                  </div>
                {/each}
              </div>
            {:else if !keyData}
              <div class="flex min-h-36 flex-col items-center justify-center rounded-lg border bg-muted/10 p-6 text-center">
                <ShieldCheck class="mb-2 text-muted-foreground" size={28} />
                <p class="font-medium">Chưa nạp được API keys</p>
                <p class="mt-1 text-sm text-muted-foreground">Bấm “Làm mới” để thử lại.</p>
              </div>
            {:else if !keyData.persisted}
              <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="status">
                <WarningCircle class="mt-0.5 shrink-0" />
                <span>
                  Kho SQLite chưa mở nên chưa tạo được key. Dùng
                  <span class="font-data">CHAT2API_KEYS</span> trong .env, hoặc xem log khởi động.
                </span>
              </div>
            {:else}
              {#if keyData.bootstrap_keys}
                <p class="text-xs leading-5 text-muted-foreground">
                  Thêm {keyData.bootstrap_keys} key từ <span class="font-data">CHAT2API_KEYS</span>:
                  key bootstrap không có hàng trong kho nên không liệt kê và không thu hồi được từ đây.
                </p>
              {/if}

              {#if freshKey}
                <div
                  class="flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning/5 p-4"
                  role="status"
                  aria-live="assertive"
                >
                  <div class="flex items-start gap-2 text-sm text-warning">
                    <Warning className="mt-0.5 shrink-0" />
                    <span>
                      Key của <strong>{freshKey.label}</strong> — server chỉ lưu bản băm nên đây là
                      lần duy nhất đọc được. Chép đi trước khi đóng.
                    </span>
                  </div>
                  <div class="flex gap-1.5">
                    <code class="min-w-0 flex-1 break-all rounded-lg border bg-card px-2.5 py-1.5 font-data text-xs">
                      {freshReveal ? freshKey.key : "••••••••••••••••"}
                    </code>
                    <Button
                      variant="outline"
                      size="icon-sm"
                      aria-label={freshReveal ? "Ẩn key mới" : "Hiện key mới"}
                      aria-pressed={freshReveal}
                      onclick={() => (freshReveal = !freshReveal)}
                    >
                      {#if freshReveal}<EyeSlash />{:else}<Eye />{/if}
                    </Button>
                    <Button variant="outline" size="icon-sm" aria-label="Chép key mới" onclick={copyFreshKey}>
                      <Copy />
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onclick={() => {
                        freshKey = null;
                        freshReveal = false;
                      }}
                    >
                      <X /> Đã chép, đóng
                    </Button>
                  </div>
                </div>
              {/if}

              <form
                class="grid gap-3 rounded-lg border bg-muted/20 p-4 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end"
                onsubmit={(e) => {
                  e.preventDefault();
                  addKey();
                }}
              >
                <div class="grid gap-1.5">
                  <label for="key-label" class="text-sm font-medium">Nhãn</label>
                  <Input id="key-label" type="text" placeholder="desktop, ci, n8n…" bind:value={newLabel} />
                </div>
                <div class="grid gap-1.5">
                  <label for="key-scopes" class="text-sm font-medium">Quyền</label>
                  <select
                    id="key-scopes"
                    class="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                    bind:value={newScopes}
                  >
                    <option value="chat,admin">chat + admin</option>
                    <option value="chat">chỉ chat (/v1/*)</option>
                    <option value="admin">chỉ admin (/admin/*)</option>
                  </select>
                </div>
                <Button type="submit" disabled={keyBusy}>
                  {#if keyBusy}<CircleNotch class="animate-spin" />{/if}
                  <Key /> Tạo key
                </Button>
              </form>

              {#if keyData.keys.length}
                <ul class="grid gap-3">
                  {#each keyData.keys as row (row.id)}
                    <li class="flex flex-col gap-3 rounded-lg border bg-card p-4 sm:flex-row sm:items-center">
                      <div class="flex min-w-0 flex-1 items-start gap-3">
                        <span
                          class:bg-success={!row.revoked_at}
                          class:bg-destructive={!!row.revoked_at}
                          class="mt-1.5 size-2.5 shrink-0 rounded-full"
                          aria-hidden="true"
                        ></span>
                        <div class="min-w-0">
                          <div class="flex flex-wrap items-center gap-2">
                            <span class="font-data text-sm font-semibold">{row.label}</span>
                            {#if row.revoked_at}<Badge variant="destructive">đã thu hồi</Badge>{/if}
                          </div>
                          <p class="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 font-data text-xs text-muted-foreground">
                            <code>{row.key_prefix}…</code>
                            <code>{row.scopes.join(" + ")}</code>
                            <code>{lastUsed(row.last_used_at)}</code>
                          </p>
                        </div>
                      </div>
                      <div class="flex shrink-0 items-center gap-2">
                        <Button
                          variant="destructive"
                          size="sm"
                          disabled={keyBusy}
                          onclick={() => (dropTarget = row)}
                        >
                          {#if keyBusy}<CircleNotch class="animate-spin" />{/if}
                          <Trash />
                          {row.revoked_at ? "Xóa hẳn" : "Thu hồi"}
                        </Button>
                      </div>
                    </li>
                  {/each}
                </ul>
              {:else}
                <div class="flex min-h-32 flex-col items-center justify-center rounded-lg border bg-muted/10 p-6 text-center">
                  <Key class="mb-2 text-muted-foreground" size={28} />
                  <p class="font-medium">Chưa có key nào trong kho</p>
                  <p class="mt-1 text-sm text-muted-foreground">Tạo key đầu tiên để bật xác thực cho server.</p>
                </div>
              {/if}
            {/if}
          </Card.Content>
        </Card.Root>
      </Tabs.Content>

      <!-- Restart-required changes -->
      {#if hasRestartFields}
        <Tabs.Content value="restart" class="mt-3">
          <div class="flex flex-col gap-4">
            <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning" role="note">
              <WarningCircle class="mt-0.5 shrink-0" />
              <span>
                Các mục này chỉ có hiệu lực sau khi khởi động lại chat2api. Lưu vẫn ghi vào kho,
                giá trị được áp dụng ở lần chạy kế tiếp.
              </span>
            </div>

            {#if loading}
              <div class="grid gap-4" aria-label="Đang nạp settings" aria-busy="true">
                <Card.Root>
                  <Card.Content class="grid gap-4 p-4 sm:p-6">
                    <div class="grid gap-2">
                      <Skeleton class="h-4 w-32" />
                      <Skeleton class="h-8 w-full" />
                      <Skeleton class="h-3 w-2/3" />
                    </div>
                    <div class="grid gap-2">
                      <Skeleton class="h-4 w-32" />
                      <Skeleton class="h-8 w-full" />
                      <Skeleton class="h-3 w-1/2" />
                    </div>
                  </Card.Content>
                </Card.Root>
              </div>
            {:else if loadError}
              <div class="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive" role="alert">
                <span>{loadError}</span>
                <Button variant="outline" size="sm" onclick={load}><Repeat /> Thử lại</Button>
              </div>
            {:else if !restartGroups.length}
              <div class="flex min-h-36 flex-col items-center justify-center rounded-lg border bg-card p-6 text-center">
                <Warning class="mb-2 text-muted-foreground" size={28} />
                <p class="font-medium">Không có mục nào cần khởi động lại</p>
              </div>
            {:else}
              {#each restartGroups as group (group)}
                <Card.Root>
                  <Card.Header class="border-b">
                    <Card.Title class="flex items-center gap-2 text-base">
                      {group}
                      <Badge variant="secondary">restart</Badge>
                    </Card.Title>
                  </Card.Header>
                  <Card.Content class="grid gap-5 p-4 sm:grid-cols-2 sm:p-6">
                    {#each fieldsOf(group, "restart") as field (field.key)}
                      {@render fieldRow(field)}
                    {/each}
                  </Card.Content>
                </Card.Root>
              {/each}
              {@render saveBar()}
            {/if}
          </div>
        </Tabs.Content>
      {/if}
    </Tabs.Root>
  </div>
</section>

<AlertDialog.Root open={dropTarget !== null} onOpenChange={(open) => { if (!open) dropTarget = null; }}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {dropTarget?.revoked_at ? "Xóa hẳn key" : "Thu hồi key"} {dropTarget?.label}?
      </AlertDialog.Title>
      <AlertDialog.Description>
        {#if dropTarget?.revoked_at}
          request_log sẽ không truy ngược được nữa.
        {:else}
          Client đang dùng nó sẽ nhận 401 ngay.
        {/if}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>Hủy</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={confirmDropKey} disabled={keyBusy}>
        {dropTarget?.revoked_at ? "Xóa hẳn" : "Thu hồi"}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
