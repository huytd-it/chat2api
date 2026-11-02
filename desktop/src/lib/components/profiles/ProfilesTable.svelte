<script lang="ts">
  import type { ProfileInfo } from "$lib/api";
  import { cooldowns, isAccountLocked } from "$lib/sync";
  import { Badge } from "$lib/components/ui/badge";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import * as Table from "$lib/components/ui/table";
  import { Star } from "phosphor-svelte";
  import { GOOGLE_STATUS, modeLabel, statusOf, type GoogleState } from "./profile-utils";

  interface Props {
    profiles: ProfileInfo[];
    /** Profile đang xem chi tiết. */
    activeId: number | null;
    /** Profile đã tick để thao tác hàng loạt. */
    checked: Set<number>;
    google: Record<number, GoogleState>;
    onselect: (p: ProfileInfo) => void;
  }
  let { profiles, activeId, checked = $bindable(), google, onselect }: Props = $props();

  const allChecked = $derived(profiles.length > 0 && profiles.every((p) => checked.has(p.id)));
  const someChecked = $derived(!allChecked && profiles.some((p) => checked.has(p.id)));

  function toggle(id: number, on: boolean) {
    const next = new Set(checked);
    if (on) next.add(id); else next.delete(id);
    checked = next;
  }
  function toggleAll(on: boolean) { checked = on ? new Set(profiles.map((p) => p.id)) : new Set(); }
  function siteCount(p: ProfileInfo): number { return new Set(p.accounts.map((a) => a.host)).size; }
  function lockedCount(p: ProfileInfo): number { return p.accounts.filter((a) => isAccountLocked($cooldowns, a.id)).length; }
</script>

<Table.Root aria-label="Danh sách profile">
  <Table.Header>
    <Table.Row>
      <Table.Head class="w-10 pl-4 sm:pl-6"><Checkbox checked={allChecked} indeterminate={someChecked} onCheckedChange={(v) => toggleAll(!!v)} aria-label="Chọn tất cả profile" /></Table.Head>
      <Table.Head>Profile</Table.Head>
      <Table.Head class="hidden md:table-cell">Chế độ</Table.Head>
      <Table.Head>Trạng thái</Table.Head>
      <Table.Head class="hidden sm:table-cell">Site</Table.Head>
      <Table.Head class="hidden md:table-cell">Google</Table.Head>
      <Table.Head class="hidden pr-4 sm:pr-6 lg:table-cell">Account bị khóa</Table.Head>
    </Table.Row>
  </Table.Header>
  <Table.Body>
    {#each profiles as p (p.id)}
      {@const status = statusOf(p)}
      {@const state = google[p.id]}
      {@const locked = lockedCount(p)}
      {@const googleStatus = GOOGLE_STATUS[state?.identity?.status ?? "unknown"] ?? GOOGLE_STATUS.unknown}
      <Table.Row class={p.id === activeId ? "bg-primary/10 hover:bg-primary/10" : ""}>
        <Table.Cell class="pl-4 sm:pl-6"><Checkbox checked={checked.has(p.id)} onCheckedChange={(v) => toggle(p.id, !!v)} aria-label={`Chọn profile ${p.name}`} /></Table.Cell>
        <Table.Cell class="max-w-56">
          <span class="flex min-w-0 items-center gap-1.5">
            <button type="button" class={`min-w-0 truncate rounded-sm text-left font-data font-semibold hover:underline focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none ${p.id === activeId ? "text-primary" : ""}`} aria-current={p.id === activeId ? "true" : undefined} onclick={() => onselect(p)}>{p.name}</button>
            {#if p.is_default}<Star size={13} weight="fill" class="shrink-0 text-muted-foreground" aria-label="Mặc định" />{/if}
          </span>
        </Table.Cell>
        <Table.Cell class="hidden text-muted-foreground md:table-cell">{modeLabel(p.scrapling_mode)}</Table.Cell>
        <Table.Cell><span class="inline-flex items-center gap-2 text-xs"><span class={`size-2 shrink-0 rounded-full ${status.cls}`}></span>{status.label}</span></Table.Cell>
        <Table.Cell class="hidden font-data text-xs sm:table-cell">{siteCount(p)}</Table.Cell>
        <Table.Cell class="hidden md:table-cell"><Badge variant={state?.waiting ? "warning" : googleStatus.variant}>{state?.waiting ? "Đang chờ xác minh" : googleStatus.label}</Badge></Table.Cell>
        <Table.Cell class="hidden pr-4 text-xs sm:pr-6 lg:table-cell">
          {#if locked}<a class="font-medium text-warning underline-offset-2 hover:underline" href="?tab=locks">{locked} account</a>{:else}<span class="text-muted-foreground">—</span>{/if}
        </Table.Cell>
      </Table.Row>
    {/each}
  </Table.Body>
</Table.Root>
