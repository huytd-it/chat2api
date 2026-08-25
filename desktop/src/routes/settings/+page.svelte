<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, showToast } from "$lib/stores";
  import { fetchSettings, saveSettings, type SettingField } from "$lib/api";
  import { refreshRecipes } from "$lib/sync";

  let fields = $state<SettingField[]>([]);
  let values = $state<Record<string, string>>({});
  let envPath = $state("");
  let loading = $state(true);
  let saving = $state(false);
  let restartKeys = $state<string[]>([]);

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
