<script lang="ts">
  import type { ProfileInfo } from "$lib/api";
  import { cooldowns, domains, isAccountLocked } from "$lib/sync";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import * as Table from "$lib/components/ui/table";
  import { Trash } from "phosphor-svelte";
  import { isDomainDeletable } from "./profile-utils";

  interface Props {
    hosts: string[];
    profiles: ProfileInfo[];
    /** Domain đã tick để thao tác hàng loạt. */
    checked: Set<string>;
    /** Xoá domain; chỉ hiện với domain server đã biết và không có recipe. */
    ondelete: (host: string) => void;
  }
  let { hosts, profiles, checked = $bindable(), ondelete }: Props = $props();

  let filter = $state("");
  const visible = $derived(hosts.filter((h) => h.includes(filter.trim().toLowerCase())));
  // "Chọn tất cả" chỉ tính những dòng đang nhìn thấy sau khi lọc.
  const allChecked = $derived(visible.length > 0 && visible.every((h) => checked.has(h)));
  const someChecked = $derived(!allChecked && visible.some((h) => checked.has(h)));
  const hiddenChecked = $derived([...checked].filter((h) => !visible.includes(h)).length);

  function toggle(host: string, on: boolean) {
    const next = new Set(checked);
    if (on) next.add(host); else next.delete(host);
    checked = next;
  }
  function toggleAll(on: boolean) {
    const next = new Set(checked);
    for (const h of visible) { if (on) next.add(h); else next.delete(h); }
    checked = next;
  }
  function attached(host: string): ProfileInfo[] { return profiles.filter((p) => p.accounts.some((a) => a.host === host)); }
  function recipesOf(host: string): string[] { return $domains.find((d) => d.host === host)?.recipes ?? []; }
  function lockedCount(host: string): number {
    return profiles.flatMap((p) => p.accounts).filter((a) => a.host === host && isAccountLocked($cooldowns, a.id)).length;
  }
</script>

<div class="flex flex-wrap items-center gap-3 px-4 pb-2 sm:px-6">
  <Input class="max-w-xs font-data" placeholder="Lọc domain" aria-label="Lọc domain" bind:value={filter} />
  {#if hiddenChecked}<span class="text-xs text-muted-foreground">{hiddenChecked} domain đã chọn đang bị bộ lọc ẩn, vẫn được tính khi thao tác.</span>{/if}
</div>

{#if !hosts.length}
  <p class="border-t px-4 py-8 text-center text-sm text-muted-foreground sm:px-6">Chưa biết domain nào. Thêm account cho profile hoặc tạo recipe để domain xuất hiện ở đây.</p>
{:else if !visible.length}
  <p class="border-t px-4 py-8 text-center text-sm text-muted-foreground sm:px-6">Không có domain khớp bộ lọc.</p>
{:else}
  <Table.Root aria-label="Danh sách domain">
    <Table.Header>
      <Table.Row>
        <Table.Head class="w-10 pl-4 sm:pl-6"><Checkbox checked={allChecked} indeterminate={someChecked} onCheckedChange={(v) => toggleAll(!!v)} aria-label="Chọn tất cả domain đang hiện" /></Table.Head>
        <Table.Head>Domain</Table.Head>
        <Table.Head>Profile đã gắn</Table.Head>
        <Table.Head class="hidden md:table-cell">Recipe</Table.Head>
        <Table.Head class="hidden lg:table-cell">Account bị khóa</Table.Head>
        <Table.Head class="w-10 pr-4 sm:pr-6"><span class="sr-only">Xóa</span></Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each visible as host (host)}
        {@const linked = attached(host)}
        {@const recipes = recipesOf(host)}
        {@const locked = lockedCount(host)}
        <Table.Row>
          <Table.Cell class="pl-4 sm:pl-6"><Checkbox checked={checked.has(host)} onCheckedChange={(v) => toggle(host, !!v)} aria-label={`Chọn domain ${host}`} /></Table.Cell>
          <Table.Cell class="break-all font-data text-xs whitespace-normal">{host}</Table.Cell>
          <Table.Cell class="font-data text-xs whitespace-normal">
            {#if linked.length}{linked.map((p) => p.name).join(", ")}{:else}<span class="font-sans text-muted-foreground">Chưa gắn</span>{/if}
          </Table.Cell>
          <Table.Cell class="hidden font-data text-xs whitespace-normal text-muted-foreground md:table-cell">{recipes.join(", ") || "—"}</Table.Cell>
          <Table.Cell class="hidden text-xs lg:table-cell">
            {#if locked}<a class="font-medium text-warning underline-offset-2 hover:underline" href="?tab=locks">{locked} account</a>{:else}<span class="text-muted-foreground">—</span>{/if}
          </Table.Cell>
          <Table.Cell class="pr-4 text-right sm:pr-6">
            {#if isDomainDeletable($domains, host)}
              <Button variant="ghost" size="icon-sm" class="text-destructive" aria-label={`Xóa domain ${host}`} title="Xóa domain" onclick={() => ondelete(host)}><Trash /></Button>
            {/if}
          </Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
{/if}
