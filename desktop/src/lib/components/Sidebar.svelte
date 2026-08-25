<script lang="ts">
  import { apiKey, currentView, serverStatus } from "../stores";
  import { models, modelsLoading, selectedModel, refreshModels, refreshRecipes } from "../sync";

  let keyVisible = $state(false);
  let keyInput = $state($apiKey);

  function commitKey() {
    apiKey.set(keyInput.trim());
    refreshModels();
    refreshRecipes();
  }
</script>

<aside class="sidebar" aria-label="Cấu hình playground">
  <section class="side-section">
    <h2>Request</h2>
    <div class="field">
      <label for="model">Model</label>
      <select
        id="model"
        aria-describedby="modelhelp"
        disabled={$modelsLoading}
        bind:value={$selectedModel}
      >
        {#if $modelsLoading}
          <option value="">Đang tải model...</option>
        {:else if $models.length === 0}
          <option value="">Không có model sẵn sàng</option>
        {:else}
          {#each $models as m (m.id)}
            <option value={m.id}>{m.id}</option>
          {/each}
        {/if}
      </select>
      <p class="field-help" id="modelhelp">Chỉ hiển thị model đang sẵn sàng.</p>
    </div>
    <div class="field">
      <label for="key">API key</label>
      <div class="key-row">
        <input
          id="key"
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
      <p class="field-help">Được lưu cục bộ trong trình duyệt này.</p>
    </div>
  </section>
  <section class="side-section">
    <h2>Server</h2>
    <div class="metrics">
      <div class="metric"><strong>{$modelsLoading ? "-" : $models.length}</strong><span>models</span></div>
      <div class="metric"><strong>{$serverStatus.contexts}</strong><span>contexts</span></div>
      <div class="metric"><strong>{$serverStatus.engine}</strong><span>engine</span></div>
      <div class="metric"><strong>OpenAI</strong><span>compatible</span></div>
    </div>
  </section>
  <button class="button secondary full" onclick={() => currentView.set("integrations")}>
    Quản lý integrations
  </button>
</aside>
