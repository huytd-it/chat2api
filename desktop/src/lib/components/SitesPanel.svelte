<script lang="ts">
  import { apiKey, showToast } from "../stores";
  import { profiles, recipes, recipesLoading, refreshAfterRecipeChange, refreshAfterRecipeDelete, refreshProfiles, refreshRecipes } from "../sync";
  import { closeRecipeBrowser, deleteRecipe, reloadRecipe, type RecipeInfo } from "../api";
  import { Button } from "$lib/components/ui/button";
  import { Badge, type BadgeVariant } from "$lib/components/ui/badge";
  import * as Card from "$lib/components/ui/card";
  import * as AlertDialog from "$lib/components/ui/alert-dialog";
  import { Browser, CaretDown, CaretRight, CircleNotch, Repeat, Stack, Trash, WarningCircle, X } from "phosphor-svelte";

  interface Props {
    /** Slug cần cuộn tới và làm nổi bật (ví dụ ngay sau khi tích hợp thành công). */
    highlightSlug?: string | null;
    onHighlighted?: () => void;
    /** Chuyển sang tab Profiles — nơi duy nhất sửa được profile/account. */
    onManageProfiles?: () => void;
  }
  let { highlightSlug = null, onHighlighted, onManageProfiles }: Props = $props();

  let expanded = $state<Record<string, boolean>>({});
  let busySlug = $state<string | null>(null);
  let deleteRecipeTarget = $state<string | null>(null);
  let panelError = $state("");
  let refreshing = $state(false);

  /** Profile đang đăng nhập một domain, theo đúng bảng `profile`/`account` mà
   * router dùng để chọn account cho mỗi request. Panel này chỉ ĐỌC: mọi thao
   * tác thêm/sửa/xóa nằm ở tab Profiles, để một thứ chỉ có một chỗ quản lý. */
  function profilesServing(domain: string | undefined) {
    if (!domain) return [];
    const wanted = domain.toLowerCase().replace(/^www\./, "");
    return $profiles
      .map((profile) => ({
        profile,
        accounts: profile.accounts.filter(
          (account) => account.host.toLowerCase().replace(/^www\./, "") === wanted && !account.disabled),
      }))
      .filter((item) => item.accounts.length > 0);
  }

  function toggle(slug: string) { expanded = { ...expanded, [slug]: !expanded[slug] }; }
  function fail(e: unknown) { panelError = (e as Error).message; showToast(panelError); }
  async function refresh() { refreshing = true; panelError = ""; try { await Promise.all([refreshRecipes(), refreshProfiles()]); } catch (e) { fail(e); } finally { refreshing = false; } }
  async function onReload(slug: string) { busySlug = slug; panelError = ""; try { await reloadRecipe($apiKey, slug); await refreshAfterRecipeChange(); } catch (e) { fail(e); } finally { busySlug = null; } }
  async function onCloseBrowser(slug: string) { busySlug = slug; panelError = ""; try { const closed = await closeRecipeBrowser($apiKey, slug); showToast(closed ? `Đã tắt browser của ${slug}` : `Browser của ${slug} chưa mở`); } catch (e) { fail(e); } finally { busySlug = null; } }
  async function confirmDeleteRecipe() {
    const slug = deleteRecipeTarget; if (!slug) return; deleteRecipeTarget = null; busySlug = slug; panelError = "";
    try { await deleteRecipe($apiKey, slug); showToast(`Đã xóa recipe ${slug}`); await refreshAfterRecipeDelete(); } catch (e) { fail(e); } finally { busySlug = null; }
  }

  function healthOf(rec: RecipeInfo, profileCount: number): { label: string; variant: BadgeVariant } {
    if (rec.unhealthy) return { label: "Lỗi sức khỏe", variant: "destructive" };
    if (rec.type === "BrowserRecipe" && profileCount === 0 && rec.trial) {
      return { label: `Dùng thử: ${rec.trial.used}/${rec.trial.limit}`, variant: "warning" };
    }
    return { label: "Sẵn sàng", variant: "success" };
  }

  $effect(() => {
    if (!highlightSlug) return;
    expanded = { ...expanded, [highlightSlug]: true };
    const el = document.getElementById(`recipe-row-${highlightSlug}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    const timer = setTimeout(() => onHighlighted?.(), 2500);
    return () => clearTimeout(timer);
  });
</script>

<Card.Root class="overflow-hidden" aria-labelledby="sites-title">
  <Card.Header class="flex-row items-center justify-between gap-4 border-b"><div class="flex items-start gap-3"><div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary"><Browser size={19} /></div><div><Card.Title id="sites-title">Sites</Card.Title><Card.Description>Recipe, model và domain. Đăng nhập nằm ở tab Profiles.</Card.Description></div></div><Button variant="outline" size="sm" disabled={refreshing} onclick={refresh}><Repeat class={refreshing ? "animate-spin" : ""} /> {refreshing ? "Đang tải" : "Làm mới"}</Button></Card.Header>
  <Card.Content class="p-0">
    {#if panelError}<div class="m-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive" role="alert"><WarningCircle class="mt-0.5 shrink-0" />{panelError}</div>{/if}
    {#if $recipesLoading && !$recipes.length}<div class="flex min-h-36 flex-col items-center justify-center gap-2 p-6 text-muted-foreground" role="status" aria-live="polite"><CircleNotch class="animate-spin" size={24} /><p class="text-sm">Đang tải recipes…</p></div>
    {:else if !$recipes.length}<div class="flex min-h-36 flex-col items-center justify-center p-6 text-center"><Browser class="mb-2 text-muted-foreground" size={28} /><p class="font-medium">Chưa có integration</p><p class="mt-1 text-sm text-muted-foreground">Bắt đầu ở bước “Thêm integration” phía trên.</p></div>{/if}

    <div class="divide-y">
      {#each $recipes as rec (rec.slug)}
        {@const isBrowser = rec.type === "BrowserRecipe"}{@const serving = profilesServing(rec.domain)}{@const health = healthOf(rec, serving.length)}
        <article id={`recipe-row-${rec.slug}`} class={highlightSlug === rec.slug ? "ring-2 ring-inset ring-primary/60 transition-shadow" : ""}>
          <button class="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:grid-cols-[auto_minmax(10rem,1fr)_minmax(8rem,1fr)_auto_auto]" onclick={() => toggle(rec.slug)} aria-expanded={expanded[rec.slug] ?? false}>
            {#if expanded[rec.slug]}<CaretDown />{:else}<CaretRight />{/if}<span class="min-w-0"><strong class="block truncate font-data text-sm">{rec.slug}</strong><span class="block truncate font-data text-xs text-muted-foreground sm:hidden">{rec.domain ?? "—"}</span></span><span class="hidden truncate font-data text-xs text-muted-foreground sm:block">{rec.domain ?? "—"}</span><Badge variant={health.variant}>{health.label}</Badge><span class="hidden text-xs text-muted-foreground sm:inline">{isBrowser ? `${serving.length} profile` : `${rec.models.length} model`}</span>
          </button>
          {#if expanded[rec.slug]}
            <div class="grid gap-4 border-t bg-muted/15 p-4 sm:p-5">
              <dl class="grid gap-2 text-sm sm:grid-cols-[6rem_minmax(0,1fr)]"><dt class="text-muted-foreground">Models</dt><dd class="break-words font-data text-xs">{rec.models.join(", ") || "—"}</dd>{#if rec.url}<dt class="text-muted-foreground">URL</dt><dd class="break-all font-data text-xs">{rec.url}</dd>{/if}</dl>
              <div class="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onReload(rec.slug)}><Repeat class={busySlug === rec.slug ? "animate-spin" : ""} /> Reload</Button>{#if isBrowser}<Button variant="outline" size="sm" disabled={busySlug === rec.slug} onclick={() => onCloseBrowser(rec.slug)}><X /> Đóng browser</Button>{/if}<Button variant="destructive" size="sm" disabled={busySlug === rec.slug} onclick={() => (deleteRecipeTarget = rec.slug)}><Trash /> Xóa recipe</Button></div>
              {#if isBrowser}
                <div class="border-t pt-4">
                  <div class="mb-3 flex items-center justify-between gap-3">
                    <div>
                      <h4 class="text-sm font-medium">Chạy trên</h4>
                      <p class="font-data text-xs text-muted-foreground">{rec.domain}</p>
                    </div>
                    <Button variant="outline" size="sm" onclick={() => onManageProfiles?.()}><Stack /> Quản lý ở Profiles</Button>
                  </div>
                  {#if serving.length}
                    <ul class="grid gap-1.5">
                      {#each serving as item (item.profile.id)}
                        <li class="flex flex-wrap items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm">
                          <span class={`size-2 shrink-0 rounded-full ${item.profile.open ? "bg-success" : "bg-muted-foreground"}`}></span>
                          <strong class="font-data">{item.profile.name}</strong>
                          {#each item.accounts as account (account.id)}<Badge variant="outline" class="font-data">{account.label}</Badge>{/each}
                          <span class="ml-auto text-xs text-muted-foreground">{item.profile.open ? `đang chạy · ${item.profile.tabs} tab` : "rảnh"}</span>
                        </li>
                      {/each}
                    </ul>
                    <p class="mt-2 text-xs text-muted-foreground">Request được chia lần lượt cho {serving.length} profile trên — càng nhiều profile thì càng nhiều request chạy song song được.</p>
                  {:else}
                    <div class="flex items-start gap-2 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-warning"><WarningCircle class="mt-0.5 shrink-0" />Chưa profile nào đăng nhập {rec.domain} — recipe đang chạy ẩn danh và sẽ hết lượt dùng thử. Thêm ở tab Profiles.</div>
                  {/if}
                </div>
              {/if}
            </div>
          {/if}
        </article>
      {/each}
    </div>
  </Card.Content>
</Card.Root>

<AlertDialog.Root open={deleteRecipeTarget !== null} onOpenChange={(open) => { if (!open) deleteRecipeTarget = null; }}><AlertDialog.Content><AlertDialog.Header><AlertDialog.Title>Xóa recipe {deleteRecipeTarget}?</AlertDialog.Title><AlertDialog.Description>Recipe sẽ bị gỡ khỏi router. Các model của recipe này sẽ không còn khả dụng. Profile và đăng nhập không bị đụng tới.</AlertDialog.Description></AlertDialog.Header><AlertDialog.Footer><AlertDialog.Cancel>Hủy</AlertDialog.Cancel><AlertDialog.Action variant="destructive" onclick={confirmDeleteRecipe}>Xóa recipe</AlertDialog.Action></AlertDialog.Footer></AlertDialog.Content></AlertDialog.Root>
