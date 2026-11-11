<script lang="ts">
  import { updateDomain, type ProfileInfo } from "$lib/api";
  import { apiKey, showToast } from "$lib/stores";
  import { cooldowns, domains, isAccountLocked, refreshDomains } from "$lib/sync";
  import { Button } from "$lib/components/ui/button";
  import { Checkbox } from "$lib/components/ui/checkbox";
  import { Input } from "$lib/components/ui/input";
  import * as Table from "$lib/components/ui/table";
  import { FloppyDisk, Trash } from "phosphor-svelte";
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
  let loginDrafts = $state<Record<string, string>>({});
  let savingHost = $state("");
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
  function loginUrlOf(host: string): string { return $domains.find((d) => d.host === host)?.login_url ?? ""; }
  function draftOf(host: string): string { return loginDrafts[host] ?? loginUrlOf(host); }
  function lockedCount(host: string): number {
    return profiles.flatMap((p) => p.accounts).filter((a) => a.host === host && isAccountLocked($cooldowns, a.id)).length;
  }
  async function saveLoginUrl(host: string) {
    const value = (draftOf(host) || "").trim();
    savingHost = host;
    try {
      await updateDomain($apiKey, host, value);
      await refreshDomains();
      const next = { ...loginDrafts };
      delete next[host];
      loginDrafts = next;
      showToast(value ? `Đã lưu URL đăng nhập cho ${host}` : `Đã xoá URL đăng nhập tùy chỉnh của ${host}`);
    } catch (e) {
      showToast((e as Error).message);
    } finally {
      savingHost = "";
    }
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
  <p class="border-t px-4 pt-3 text-xs text-muted-foreground sm:px-6">Có thể đặt URL trang đăng nhập riêng cho từng domain (trang có nút “Continue with Google”) để khi đăng nhập Google truy cập thẳng vào đúng trang đó.</p>
  <Table.Root aria-label="Danh sách domain">
    <Table.Header>
      <Table.Row>
        <Table.Head class="w-10 pl-4 sm:pl-6"><Checkbox checked={allChecked} indeterminate={someChecked} onCheckedChange={(v) => toggleAll(!!v)} aria-label="Chọn tất cả domain đang hiện" /></Table.Head>
        <Table.Head>Domain</Table.Head>
        <Table.Head class="min-w-[18rem]">URL trang đăng nhập (Google)</Table.Head>
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
        {@const saved = loginUrlOf(host)}
        <Table.Row>
          <Table.Cell class="pl-4 align-top sm:pl-6"><Checkbox checked={checked.has(host)} onCheckedChange={(v) => toggle(host, !!v)} aria-label={`Chọn domain ${host}`} /></Table.Cell>
          <Table.Cell class="break-all font-data text-xs whitespace-normal align-top pt-4">{host}</Table.Cell>
          <Table.Cell class="align-top">
            <div class="flex gap-2">
              <Input
                class="font-data text-xs"
                placeholder={`https://${host}/login`}
                aria-label={`URL trang đăng nhập của ${host}`}
                value={draftOf(host)}
                oninput={(e) => (loginDrafts = { ...loginDrafts, [host]: (e.currentTarget as HTMLInputElement).value })}
                onblur={() => { if (draftOf(host) !== saved) saveLoginUrl(host); }}
                onkeydown={(e) => { if (e.key === "Enter") { e.preventDefault(); saveLoginUrl(host); } }}
              />
              <Button variant="outline" size="icon-sm" title="Lưu URL đăng nhập" aria-label={`Lưu URL đăng nhập của ${host}`} disabled={savingHost === host || draftOf(host) === saved} onclick={() => saveLoginUrl(host)}>
                <FloppyDisk />
              </Button>
            </div>
            {#if saved}<p class="mt-1 text-[11px] text-muted-foreground">Đang dùng URL này khi đăng nhập Google cho domain.</p>{/if}
          </Table.Cell>
          <Table.Cell class="font-data text-xs whitespace-normal align-top pt-4">
            {#if linked.length}{linked.map((p) => p.name).join(", ")}{:else}<span class="font-sans text-muted-foreground">Chưa gắn</span>{/if}
          </Table.Cell>
          <Table.Cell class="hidden font-data text-xs whitespace-normal text-muted-foreground align-top pt-4 md:table-cell">{recipes.join(", ") || "—"}</Table.Cell>
          <Table.Cell class="hidden text-xs align-top pt-4 lg:table-cell">
            {#if locked}<a class="font-medium text-warning underline-offset-2 hover:underline" href="?tab=locks">{locked} account</a>{:else}<span class="text-muted-foreground">—</span>{/if}
          </Table.Cell>
          <Table.Cell class="pr-4 text-right align-top pt-3 sm:pr-6">
            {#if isDomainDeletable($domains, host)}
              <Button variant="ghost" size="icon-sm" class="text-destructive" aria-label={`Xóa domain ${host}`} title="Xóa domain" onclick={() => ondelete(host)}><Trash /></Button>
            {/if}
          </Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
{/if}
