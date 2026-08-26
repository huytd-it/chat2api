<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { accounts, recipes, recipesLoading, refreshIntegrations, refreshModels } from "../sync";
  import { cancelAccountLogin, closeRecipeBrowser, completeDomainLogin, deleteDomainAccount, deleteRecipe, reloadRecipe, reopenDomainAccount, type AccountInfo } from "../api";
  import AccountDialog from "./AccountDialog.svelte";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { Browser, CaretDown, CaretRight, CircleNotch, Plus, Repeat, Trash, Users, WarningCircle, X } from "phosphor-svelte";

  let expanded = $state<Record<string, boolean>>({});
  let busySlug = $state<string | null>(null);
  let busyAccount = $state<string | null>(null);
  let dialogDomain = $state<string | null>(null);
  let reopenSession = $state<string | null>(null);
  let reopenDomain = $state("");
  let reopenName = $state("");
  let reopenBusy = $state(false);
  let deleteRecipeTarget = $state<string | null>(null);
  let deleteAccountTarget = $state<{ domain: string; name: string } | null>(null);
  let panelError = $state("");
  let refreshing = $state(false);

  function accountsOf(domain: string | undefined): AccountInfo[] { return domain ? $accounts.find((d) => d.domain === domain)?.accounts ?? [] : []; }
  function toggle(slug: string) { expanded = { ...expanded, [slug]: !expanded[slug] }; }
  function fail(e: unknown) { panelError = (e as Error).message; showToast(panelError); }
  async function refresh() { refreshing = true; panelError = ""; try { await refreshIntegrations(); } catch (e) { fail(e); } finally { refreshing = false; } }
  async function onReload(slug: string) { busySlug = slug; panelError = ""; try { await reloadRecipe($apiKey, slug); await Promise.all([refreshIntegrations(), refreshModels()]); } catch (e) { fail(e); } finally { busySlug = null; } }
  async function onCloseBrowser(slug: string) { busySlug = slug; panelError = ""; try { const closed = await closeRecipeBrowser($apiKey, slug); showToast(closed ? `Đã tắt browser của ${slug}` : `Browser của ${slug} chưa mở`); } catch (e) { fail(e); } finally { busySlug = null; } }
  async function confirmDeleteRecipe() {
    const slug = deleteRecipeTarget; if (!slug) return; deleteRecipeTarget = null; busySlug = slug; panelError = "";
    try { await deleteRecipe($apiKey, slug); showToast(`Đã xóa recipe ${slug}`); await Promise.all([refreshIntegrations(), refreshModels()]); } catch (e) { fail(e); } finally { busySlug = null; }
  }
  async function onReopen(domain: string, name: string) { busyAccount = `${domain}/${name}`; panelError = ""; try { const res = await reopenDomainAccount($apiKey, domain, name); reopenSession = res.session_id; reopenDomain = domain; reopenName = name; } catch (e) { fail(e); } finally { busyAccount = null; } }
  async function saveReopen() { if (!reopenSession) return; reopenBusy = true; panelError = ""; try { await completeDomainLogin($apiKey, reopenSession, reopenDomain, reopenName); showToast(`Đã cập nhật ${reopenDomain}/${reopenName}`); reopenSession = null; await refreshIntegrations(); } catch (e) { fail(e); } finally { reopenBusy = false; } }
  async function cancelReopen() { const session = reopenSession; reopenSession = null; if (session) await cancelAccountLogin($apiKey, reopenDomain, session).catch(() => {}); }
  async function confirmDeleteAccount() {
    const target = deleteAccountTarget; if (!target) return; deleteAccountTarget = null; const key = `${target.domain}/${target.name}`; busyAccount = key; panelError = "";
    try { await deleteDomainAccount($apiKey, target.domain, target.name); showToast(`Đã xóa ${key}`); await refreshIntegrations(); } catch (e) { fail(e); } finally { busyAccount = null; }
  }
  function formatWhen(seconds: number): string { return new Date(seconds * 1000).toLocaleString(); }
  const orphanDomains = $derived($accounts.filter((d) => d.recipes.length === 0 && d.accounts.length > 0));
</script>

<Card.Root class="overflow-hidden" aria-labelledby="sites-title">
  <Card.Header class="flex-row items-center justify-between gap-4 border-b"><div class="flex items-start gap-3"><div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Browser size={19} /></div><div><Card.Title id="sites-title">Sites & accounts</Card.Title><Card.Description>Kiểm tra recipe, model và phiên đăng nhập theo domain.</Card.Description></div></div><Button variant="outline" size="sm" disabled={refreshing} onclick={refresh}><Repeat class={refreshing ? "animate-spin" : ""} /> {refreshing ? "Đang tải" : "Làm mới"}</Button></Card.Header>
  <Card.Content class="p-0">
    {#if panelError}<div class="m-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{panelError}</div>{/if}
    {#if $recipesLoading && !$recipes.length}<div class="flex min-h-36 flex-col items-center justify-center gap-2 p-6 text-muted-foreground" role="status" aria-live="polite"><CircleNotch class="animate-spin" size={24} /><p class="text-sm">Đang tải recipes…</p></div>
    {:else if !$recipes.length}<div class="flex min-h-36 flex-col items-center justify-center p-6 text-center"><Browser class="mb-2 text-muted-foreground" size={28} /><p class="font-medium">Chưa có integration</p><p class="mt-1 text-sm text-muted-foreground">Bắt đầu ở bước “Thêm integration” phía trên.</p></div>{/if}

    <div class="divide-y">
      {#each $recipes as rec (rec.slug)}
        {@const isBrowser = rec.type === "BrowserRecipe"}{@const list = accountsOf(rec.domain)}
        <article>
          <button class="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[auto_minmax(10rem,1fr)_minmax(8rem,1fr)_auto_auto]" onclick={() => toggle(rec.slug)} aria-expanded={expanded[rec.slug] ?? false}>
            {#if expanded[rec.slug]}<CaretDown />{:else}<CaretRight />{/if}<span class="min-w-0"><strong class="block truncate font-data text-sm">{rec.slug}</strong><span class="block truncate font-data text-xs text-muted-foreground sm:hidden">{rec.domain ?? "—"}</span></span><span class="hidden truncate font-data text-xs text-muted-foreground sm:block">{rec.domain ?? "—"}</span><Badge variant={rec.unhealthy ? "destructive" : "outline"}>{rec.unhealthy ? "Cần kiểm tra" : "Sẵn sàng"}</Badge><span class="hidden text-xs text-muted-foreground sm:inline">{isBrowser ? `${rec.trial ? `${rec.trial.used}/${rec.trial.limit} trial` : `${list.length} account`}` : `${rec.models.length} model`}</span>
          </button>
          {#if expanded[rec.slug]}
            <div class="grid gap-4 border-t bg-muted/15 p-4 sm:p-5">
              <dl class="grid gap-2 text-sm sm:grid-cols-[6rem_minmax(0,1fr)]"><dt class="text-muted-foreground">Models</dt><dd class="break-words font-data text-xs">{rec.models.join(", ") || "—"}</dd>{#if rec.url}<dt class="text-muted-foreground">URL</dt><dd class="break-all font-data text-xs">{rec.url}</dd>{/if}</dl>
              <div class="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onReload(rec.slug)}><Repeat class={busySlug === rec.slug ? "animate-spin" : ""} /> Reload</Button>{#if isBrowser}<Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onCloseBrowser(rec.slug)}><X /> Đóng browser</Button>{/if}<Button variant="destructive" size="sm" disabled={busySlug === rec.slug} onclick={() => (deleteRecipeTarget = rec.slug)}><Trash /> Xóa recipe</Button></div>
              {#if isBrowser}<div class="border-t pt-4"><div class="mb-3 flex items-center justify-between gap-3"><div><h4 class="text-sm font-medium">Accounts</h4><p class="font-data text-xs text-muted-foreground">{rec.domain}</p></div><Button variant="outline" size="sm" onclick={() => (dialogDomain = rec.domain ?? "")}><Plus /> Thêm account</Button></div>
                {#if list.length}<div class="overflow-x-auto rounded-lg border"><table class="w-full text-sm"><thead class="bg-muted/50 text-left text-xs text-muted-foreground"><tr><th class="px-3 py-2 font-medium">Account</th><th class="px-3 py-2 font-medium">Cập nhật</th><th class="px-3 py-2 text-right font-medium">Thao tác</th></tr></thead><tbody class="divide-y">{#each list as account (account.name)}{@const key = `${rec.domain}/${account.name}`}<tr><td class="px-3 py-2 font-data text-xs">{account.name}</td><td class="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">{formatWhen(account.updated_at)}</td><td class="px-3 py-2"><div class="flex justify-end gap-1"><Button variant="ghost" size="sm" disabled={busyAccount === key} onclick={() => onReopen(rec.domain ?? "", account.name)}>Đăng nhập lại</Button><Button variant="destructive" size="icon-sm" aria-label={`Xóa account ${account.name}`} disabled={busyAccount === key} onclick={() => (deleteAccountTarget = { domain: rec.domain ?? "", name: account.name })}><Trash /></Button></div></td></tr>{/each}</tbody></table></div>
                {:else}<div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Chưa có account — recipe đang chạy ẩn danh và sẽ hết lượt dùng thử.</div>{/if}
              </div>{/if}
            </div>
          {/if}
        </article>
      {/each}
      {#each orphanDomains as d (d.domain)}<article class="grid gap-3 bg-muted/10 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div><strong class="font-data text-sm">{d.domain}</strong><p class="text-xs text-muted-foreground">{d.accounts.length} account · chưa recipe nào dùng</p></div><div class="flex flex-wrap gap-1">{#each d.accounts as account (account.name)}<Button variant="destructive" size="sm" disabled={busyAccount === `${d.domain}/${account.name}`} onclick={() => (deleteAccountTarget = { domain: d.domain, name: account.name })}><Trash /> Xóa {account.name}</Button>{/each}</div></article>{/each}
    </div>
    {#if reopenSession}<div class="m-4 flex flex-col gap-3 rounded-lg border border-warning/20 bg-warning/5 p-4 sm:flex-row sm:items-center"><div class="min-w-0 flex-1"><p class="text-sm font-medium text-warning">Đăng nhập lại {reopenDomain}/{reopenName}</p><p class="text-xs text-muted-foreground">Hoàn tất trong browser rồi lưu để ghi đè state cũ.</p></div><div class="flex gap-2"><Button disabled={reopenBusy} onclick={saveReopen}>{#if reopenBusy}<CircleNotch class="animate-spin" />{/if} Lưu</Button><Button variant="outline" disabled={reopenBusy} onclick={cancelReopen}>Hủy</Button></div></div>{/if}
  </Card.Content>
</Card.Root>

{#if dialogDomain !== null}<AccountDialog domain={dialogDomain} lockDomain={Boolean(dialogDomain)} onclose={() => (dialogDomain = null)} />{/if}
<AlertDialog.Root open={deleteRecipeTarget !== null} onOpenChange={(open) => { if (!open) deleteRecipeTarget = null; }}><AlertDialog.Content><AlertDialog.Header><AlertDialog.Title>Xóa recipe {deleteRecipeTarget}?</AlertDialog.Title><AlertDialog.Description>Recipe sẽ bị gỡ khỏi router. Các model của recipe này sẽ không còn khả dụng.</AlertDialog.Description></AlertDialog.Header><AlertDialog.Footer><AlertDialog.Cancel>Hủy</AlertDialog.Cancel><AlertDialog.Action variant="destructive" onclick={confirmDeleteRecipe}>Xóa recipe</AlertDialog.Action></AlertDialog.Footer></AlertDialog.Content></AlertDialog.Root>
<AlertDialog.Root open={deleteAccountTarget !== null} onOpenChange={(open) => { if (!open) deleteAccountTarget = null; }}><AlertDialog.Content><AlertDialog.Header><AlertDialog.Title>Xóa account {deleteAccountTarget?.domain}/{deleteAccountTarget?.name}?</AlertDialog.Title><AlertDialog.Description>Recipe dùng domain này sẽ mất phiên đăng nhập và có thể quay lại chế độ trial hoặc anonymous.</AlertDialog.Description></AlertDialog.Header><AlertDialog.Footer><AlertDialog.Cancel>Hủy</AlertDialog.Cancel><AlertDialog.Action variant="destructive" onclick={confirmDeleteAccount}>Xóa account</AlertDialog.Action></AlertDialog.Footer></AlertDialog.Content></AlertDialog.Root>
