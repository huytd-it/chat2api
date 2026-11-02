<script lang="ts">
  import type { ProfileAccount, ProfileInfo } from "$lib/api";
  import { cooldowns, isAccountLocked } from "$lib/sync";
  import { Button } from "$lib/components/ui/button";
  import { LockKey, Plus, WarningCircle, X } from "phosphor-svelte";

  interface Props {
    profile: ProfileInfo;
    sites: string[];
    /** Host dò được trong profile nhưng chưa khai báo. */
    suggested: string[];
    busy: boolean;
    onadd: (host: string) => void;
    onremove: (account: ProfileAccount) => void;
  }
  let { profile, sites, suggested, busy, onadd, onremove }: Props = $props();

  const accounts = $derived(
    [...profile.accounts].sort((a, b) => a.host.localeCompare(b.host) || a.label.localeCompare(b.label)),
  );
  const unattached = $derived(
    sites.filter((host) => !suggested.includes(host) && !profile.accounts.some((a) => a.host === host)),
  );
</script>

<section class="grid gap-4 border-t pt-5" aria-label={`Site của ${profile.name}`}>
  {#if suggested.length}
    <div class="grid gap-2">
      <h4 class="flex items-center gap-1.5 text-sm font-medium text-warning"><WarningCircle size={15} /> Có đăng nhập chưa khai báo ({suggested.length})</h4>
      <div class="flex flex-wrap gap-1.5">
        {#each suggested as host (host)}
          <Button variant="outline" size="sm" class="border-warning/50 font-data text-warning hover:text-warning" disabled={busy} onclick={() => onadd(host)}><Plus /> {host}</Button>
        {/each}
      </div>
    </div>
  {/if}

  <div class="grid gap-2">
    <h4 class="text-sm font-medium">Site đã gắn <span class="font-normal text-muted-foreground">({accounts.length})</span></h4>
    {#if accounts.length}
      <ul class="divide-y rounded-lg border">
        {#each accounts as account (account.id)}
          {@const locked = isAccountLocked($cooldowns, account.id)}
          <li class="flex min-h-10 items-center gap-2 py-1 pr-1.5 pl-3 text-sm">
            <span class="min-w-0 flex-1 break-all font-data text-xs" title={`${account.host} / ${account.label}`}>{account.host} <span class="text-muted-foreground">/ {account.label}</span></span>
            {#if locked}<span class="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-warning" title="Đang bị khóa limit, mở khóa ở tab Account bị khóa"><LockKey size={13} /> Bị khóa</span>{/if}
            <Button variant="ghost" size="icon-sm" aria-label={`Gỡ ${account.host} / ${account.label} khỏi ${profile.name}`} title="Gỡ khỏi profile" disabled={busy} onclick={() => onremove(account)}><X /></Button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-xs text-muted-foreground">Chưa gắn site nào. Mở profile rồi dò domain, hoặc thêm account bằng tay.</p>
    {/if}
  </div>

  {#if unattached.length}
    <div class="grid gap-2">
      <h4 class="text-sm font-medium">Chưa gắn <span class="font-normal text-muted-foreground">({unattached.length})</span></h4>
      <div class="flex flex-wrap gap-1.5">
        {#each unattached as host (host)}
          <Button variant="ghost" size="sm" class="font-data font-normal text-muted-foreground" title={`Thêm ${host} vào ${profile.name}`} disabled={busy} onclick={() => onadd(host)}><Plus /> {host}</Button>
        {/each}
      </div>
    </div>
  {/if}
</section>
