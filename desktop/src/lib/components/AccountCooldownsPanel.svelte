<script lang="ts">
  import { onMount } from "svelte";
  import { apiKey, showToast } from "../stores";
  import { cooldowns, cooldownsError, cooldownsLoading, profiles, refreshCooldowns } from "../sync";
  import { clearAccountCooldown, type AccountCooldown } from "../api";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import { CircleNotch, LockKey, LockKeyOpen, Repeat, WarningCircle } from "phosphor-svelte";

  interface Props {
    /** Lọc theo recipe; rỗng = mọi recipe. */
    recipeSlug?: string;
    /** true = gọn cho khối trong expanded row; false = thẻ đầy đủ. */
    compact?: boolean;
  }
  let { recipeSlug = "", compact = false }: Props = $props();

  let busyKey = $state<string | null>(null);
  let unlockingAll = $state(false);

  const visible = $derived(
    recipeSlug ? $cooldowns.filter((c) => c.recipe_slug === recipeSlug) : $cooldowns,
  );

  /** Bản compact trong expanded row: không có gì thì ẩn hẳn cho gọn. */
  const showEmptyHint = $derived(!compact || $cooldownsLoading || $cooldownsError || visible.length > 0);

  onMount(() => {
    // Panel dùng chung store toàn cục nhưng API hỗ trợ lọc theo recipe:
    // nạp không lọc để badge khóa ở chỗ khác vẫn đúng.
    void refreshCooldowns();
  });

  function rowKey(c: AccountCooldown): string {
    return `${c.recipe_slug}|${c.account_key}`;
  }

  /** `db:<id>` → `profile / label`; `file:<domain>/<name>` giữ nguyên. */
  function accountLabel(key: string): string {
    if (key.startsWith("db:")) {
      const id = Number(key.slice(3));
      for (const p of $profiles) {
        const found = p.accounts.find((a) => a.id === id);
        if (found) return `${p.name} / ${found.label}`;
      }
      return `account #${Number.isFinite(id) ? id : key}`;
    }
    if (key.startsWith("file:")) return key.slice(5);
    return key;
  }

  function remainingText(c: AccountCooldown): string {
    const s = Math.max(0, c.retry_after ?? 0);
    if (s < 60) return `${s}s nữa`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m} phút nữa`;
    const h = Math.floor(m / 60);
    if (h < 48) {
      const rest = m % 60;
      return rest ? `${h}h${rest}p nữa` : `${h} giờ nữa`;
    }
    return `${Math.floor(h / 24)} ngày nữa`;
  }

  function untilText(ms: number): string {
    try {
      return new Date(ms).toLocaleString();
    } catch {
      return "";
    }
  }

  async function unlock(c: AccountCooldown) {
    const key = rowKey(c);
    busyKey = key;
    try {
      await clearAccountCooldown($apiKey, c.recipe_slug, c.account_key);
      showToast(`Đã mở khóa ${accountLabel(c.account_key)} (${c.recipe_slug})`);
      await refreshCooldowns();
    } catch (e) {
      showToast("Mở khóa thất bại: " + (e as Error).message);
    } finally {
      if (busyKey === key) busyKey = null;
    }
  }

  async function unlockAll() {
    const list = [...visible];
    if (!list.length) return;
    unlockingAll = true;
    let ok = 0;
    let fail = 0;
    for (const c of list) {
      try {
        await clearAccountCooldown($apiKey, c.recipe_slug, c.account_key);
        ok++;
      } catch {
        fail++;
      }
    }
    await refreshCooldowns();
    unlockingAll = false;
    showToast(
      fail ? `Đã mở ${ok}/${list.length} account (${fail} lỗi)` : `Đã mở khóa ${ok} account`,
    );
  }
</script>

{#if showEmptyHint}
<div
  class={compact
    ? "rounded-lg border border-warning/25 bg-warning/5 p-3"
    : "overflow-hidden rounded-xl border"}
  aria-labelledby={recipeSlug ? `cooldowns-${recipeSlug}` : "cooldowns-all"}
>
  <div class={compact ? "mb-2 flex flex-wrap items-center gap-2" : "flex flex-wrap items-center gap-2 border-b px-4 py-3"}>
    <span class="flex size-7 items-center justify-center rounded-lg bg-warning/15 text-warning">
      <LockKey size={15} />
    </span>
    <div class="min-w-0 flex-1">
      <h4 id={recipeSlug ? `cooldowns-${recipeSlug}` : "cooldowns-all"} class="text-sm font-medium">
        Account bị khóa limit{#if recipeSlug} · <span class="font-mono">{recipeSlug}</span>{/if}
      </h4>
      <p class="text-xs text-muted-foreground">
        {#if $cooldownsLoading}Đang tải…{:else if visible.length}{visible.length} account đang chờ hết cooldown{:else}Không có account nào bị khóa{/if}
      </p>
    </div>
    <Button variant="ghost" size="sm" disabled={$cooldownsLoading} onclick={() => refreshCooldowns()}>
      <Repeat class={$cooldownsLoading ? "animate-spin" : ""} /> Làm mới
    </Button>
    {#if visible.length > 1}
      <Button variant="outline" size="sm" disabled={unlockingAll || busyKey !== null} onclick={unlockAll}>
        {#if unlockingAll}<CircleNotch class="animate-spin" />{:else}<LockKeyOpen />{/if}
        Mở tất cả
      </Button>
    {/if}
  </div>

  {#if $cooldownsError}
    <div class={compact ? "mt-1 text-xs text-destructive" : "px-4 py-3 text-sm text-destructive"} role="alert">
      Không tải được danh sách khóa: {$cooldownsError}
    </div>
  {:else if visible.length}
    <ul class={compact ? "grid gap-1.5" : "divide-y"}>
      {#each visible as c (rowKey(c))}
        {@const busy = busyKey === rowKey(c)}
        <li class={compact ? "flex flex-wrap items-center gap-2 rounded-lg border bg-card px-2.5 py-2 text-sm" : "flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm"}>
          <Badge variant="warning" class="font-mono text-[11px]">{c.recipe_slug}</Badge>
          <strong class="min-w-0 flex-1 truncate font-mono text-xs" title={c.account_key}>
            {accountLabel(c.account_key)}
          </strong>
          {#if c.reason}
            <span class="max-w-full truncate text-xs text-muted-foreground" title={c.reason}>
              {c.reason.length > 60 ? c.reason.slice(0, 60) + "…" : c.reason}
            </span>
          {/if}
          <span class="inline-flex items-center gap-1 text-xs text-warning" title={untilText(c.until_ms)}>
            <WarningCircle size={13} /> {remainingText(c)}
          </span>
          <Button variant="outline" size="sm" disabled={busy || unlockingAll} onclick={() => unlock(c)} aria-label={`Mở khóa ${accountLabel(c.account_key)} ở ${c.recipe_slug}`}>
            {#if busy}<CircleNotch class="animate-spin" />{:else}<LockKeyOpen />{/if}
            Mở khóa
          </Button>
        </li>
      {/each}
    </ul>
    {#if !compact}
      <p class="border-t bg-muted/20 px-4 py-2 text-xs text-muted-foreground">
        Mở khóa cho chạy lại ngay; không mở thì account tự dùng được khi hết giờ trên.
      </p>
    {/if}
  {:else if !$cooldownsLoading}
    {#if !compact}
      <p class="px-4 py-3 text-sm text-muted-foreground">
        Site trả limit thì account tự vào đây — mở khóa để dùng lại ngay.
      </p>
    {/if}
  {/if}
</div>
{/if}
