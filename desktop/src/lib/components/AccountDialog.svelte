<script lang="ts">
  // Một dialog duy nhất cho mọi cách thêm account (docs/design-v2.md §6.1):
  // mở từ hàng recipe (domain điền sẵn, khoá lại), hay mở độc lập từ panel
  // Profile (domain gõ tay, chọn từ dropdown, hoặc để trống cho server tự dò).
  import { apiKey, showToast } from "../stores";
  import { domains, profiles, refreshIntegrations } from "../sync";
  import {
    addProfileAccount,
    cancelAccountLogin,
    completeDomainLogin,
    detectProfileDomains,
    openProfile,
    startDomainLogin,
  } from "../api";

  interface Props {
    /** Domain điền sẵn khi mở từ một recipe. */
    domain?: string;
    /** Khoá ô domain lại: recipe đã quyết định domain rồi. */
    lockDomain?: boolean;
    /** Profile chọn sẵn khi mở từ panel Profile. */
    profile?: string;
    onclose?: () => void;
  }

  let { domain = "", lockDomain = false, profile = "", onclose }: Props = $props();

  // Dialog được dựng lại mỗi lần mở, nên chỉ cần giá trị prop lúc khởi tạo:
  // từ đó trở đi ô input là của người dùng, không được prop ghi đè.
  // svelte-ignore state_referenced_locally
  let host = $state(domain);
  let label = $state("");
  // svelte-ignore state_referenced_locally
  let profileName = $state(profile);
  let busy = $state(false);
  let statusText = $state("");
  let suggested = $state<string[]>([]);
  let done = $state(false);

  // Hai đường lưu khác nhau: qua profile thì chính profile giữ đăng nhập (chỉ
  // ghi nhận quan hệ), không qua profile thì lưu storage_state thành file.
  let sessionId = $state<string | null>(null);
  let profileId = $state<number | null>(null);

  const usingProfile = $derived(profileName !== "");
  const opened = $derived(sessionId !== null || profileId !== null);

  async function openBrowser() {
    const target = host.trim().toLowerCase();
    busy = true;
    done = false;
    suggested = [];
    try {
      if (usingProfile) {
        const found = $profiles.find((p) => p.name === profileName);
        if (!found) {
          showToast("Không tìm thấy profile " + profileName);
          return;
        }
        const res = await openProfile($apiKey, found.id, target ? `https://${target}` : "");
        profileId = found.id;
        statusText = res.headless
          ? "Profile đang chạy nền nên không có cửa sổ mới — đóng profile rồi mở lại."
          : `Cửa sổ profile ${res.profile} đã mở. Đăng nhập xong thì bấm Dò domain.`;
      } else {
        const res = await startDomainLogin($apiKey, target);
        sessionId = res.session_id;
        statusText = target
          ? `Browser đã mở cho ${target}. Đăng nhập xong thì đặt nhãn rồi Lưu.`
          : "Browser mở trang trắng: tự vào site và đăng nhập, rồi bấm Lưu — server đọc cookie để suy ra domain.";
      }
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busy = false;
    }
  }

  async function detect() {
    if (profileId === null) return;
    busy = true;
    try {
      const res = await detectProfileDomains($apiKey, profileId);
      suggested = res.suggested;
      if (!host.trim() && res.suggested.length) host = res.suggested[0];
      statusText = res.suggested.length
        ? `Profile còn đăng nhập: ${res.suggested.join(", ")}`
        : "Không thấy domain nào chưa khai báo trong profile này.";
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busy = false;
    }
  }

  async function save() {
    const name = label.trim() || "main";
    if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
      showToast("Nhãn account chỉ gồm chữ thường, số và dấu -");
      return;
    }
    busy = true;
    try {
      if (profileId !== null) {
        const target = host.trim().toLowerCase();
        if (!target) {
          showToast("Chọn hoặc dò domain trước khi lưu.");
          return;
        }
        await addProfileAccount($apiKey, profileId, target, name);
        statusText = `Đã gắn ${target}/${name} vào profile ${profileName}.`;
      } else {
        if (!sessionId) return;
        // domain rỗng là hợp lệ: server tự dò từ cookie rồi trả về domain thật.
        const res = await completeDomainLogin($apiKey, sessionId, host.trim().toLowerCase(), name);
        host = res.domain;
        suggested = res.suggested ?? [];
        sessionId = null;
        statusText = `Đã lưu ${res.domain}/${name}.`;
      }
      done = true;
      await refreshIntegrations();
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      busy = false;
    }
  }

  /** Domain khác mà phiên/profile này cũng đang đăng nhập — thêm luôn cho đỡ một vòng. */
  async function useSuggestion(candidate: string) {
    if (profileId !== null) {
      busy = true;
      try {
        await addProfileAccount($apiKey, profileId, candidate, label.trim() || "main");
        suggested = suggested.filter((h) => h !== candidate);
        statusText = `Đã gắn ${candidate} vào profile ${profileName}.`;
        await refreshIntegrations();
      } catch (e) {
        showToast((e as Error).message);
      } finally {
        busy = false;
      }
      return;
    }
    // Đường storage_state: browser đã đóng sau khi lưu, phải mở lại một vòng
    // đăng nhập mới cho domain đó (state của domain này không dùng cho domain kia).
    host = candidate;
    label = "";
    suggested = [];
    done = false;
    await openBrowser();
  }

  async function close() {
    if (sessionId) await cancelAccountLogin($apiKey, host || "unknown", sessionId).catch(() => {});
    onclose?.();
  }

  function onKey(event: KeyboardEvent) {
    if (event.key === "Escape") close();
  }
</script>

<svelte:window on:keydown={onKey} />

<div class="modal-backdrop" role="presentation" onclick={(e) => e.target === e.currentTarget && close()}>
  <div class="panel modal" role="dialog" aria-modal="true" aria-label="Thêm account">
    <div class="panel-head">
      <div>
        <h2>Thêm account</h2>
        <p>Đăng nhập một lần, mọi recipe cùng domain dùng lại được.</p>
      </div>
      <button class="button secondary small" onclick={close}>Đóng</button>
    </div>

    <div class="dash-body">
      <div class="field">
        <label for="acct-domain">Domain</label>
        <input
          id="acct-domain"
          type="text"
          list="known-domains"
          placeholder="chat.qwen.ai — để trống để server tự dò"
          bind:value={host}
          disabled={lockDomain || opened}
        />
        <datalist id="known-domains">
          {#each $domains as d (d.host)}
            <option value={d.host}></option>
          {/each}
        </datalist>
        <p class="field-help">
          {#if lockDomain}
            Domain của recipe, không đổi được ở đây.
          {:else}
            Dán URL hay gõ tay đều được. Để trống thì browser mở trang trắng và domain
            được suy ra từ cookie lúc lưu.
          {/if}
        </p>
      </div>

      <div class="field">
        <label for="acct-profile">Profile</label>
        <select id="acct-profile" bind:value={profileName} disabled={opened}>
          <option value="">Không dùng profile (lưu storage_state)</option>
          {#each $profiles as p (p.id)}
            <option value={p.name}>{p.name} · {p.domains} domain</option>
          {/each}
        </select>
        <p class="field-help">
          Chọn profile thì cửa sổ mở bằng đúng profile đó và chính nó giữ đăng nhập — một
          profile dùng chung cho nhiều domain.
        </p>
      </div>

      <div class="field">
        <label for="acct-label">Nhãn</label>
        <input id="acct-label" type="text" placeholder="work" bind:value={label} />
      </div>

      <div class="modal-actions">
        {#if !opened}
          <button class="button" disabled={busy} onclick={openBrowser}>Mở browser</button>
        {:else}
          {#if profileId !== null}
            <button class="button secondary" disabled={busy} onclick={detect}>Dò domain</button>
          {/if}
          <button class="button" disabled={busy} onclick={save}>Lưu</button>
        {/if}
        <button class="button secondary" onclick={close}>{done ? "Xong" : "Hủy"}</button>
      </div>

      {#if statusText}
        <p class="alert {done ? 'ok' : 'amber'}">{statusText}</p>
      {/if}

      {#if suggested.length}
        <div>
          <p class="hint">Profile/phiên này còn đăng nhập những domain chưa khai báo:</p>
          <div class="saved-accounts">
            {#each suggested as candidate (candidate)}
              <span class="saved-account">
                {candidate}
                <button class="button secondary small" disabled={busy} onclick={() => useSuggestion(candidate)}>
                  Thêm luôn
                </button>
              </span>
            {/each}
          </div>
        </div>
      {/if}

    </div>
  </div>
</div>
