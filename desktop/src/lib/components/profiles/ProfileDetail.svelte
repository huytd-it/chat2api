<script lang="ts">
  import type { ProfileInfo } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Badge } from "$lib/components/ui/badge";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
  import { Browser, CircleNotch, Copy, DotsThree, DownloadSimple, GearSix, MagnifyingGlass, Plus, Star, Stop, Trash } from "phosphor-svelte";
  import { modeLabel, statusOf } from "./profile-utils";

  interface Props {
    profile: ProfileInfo;
    /** Hành động đang chạy trên profile này; rỗng = rảnh. */
    busyAction: string;
    onopen: () => void;
    onclose: () => void;
    ondetect: () => void;
    onaddaccount: () => void;
    onsettings: () => void;
    onexport: () => void;
    onclone: () => void;
    ondelete: () => void;
  }
  let { profile, busyAction, onopen, onclose, ondetect, onaddaccount, onsettings, onexport, onclone, ondelete }: Props = $props();

  const busy = $derived(busyAction !== "");
  const status = $derived(statusOf(profile));
  const isFetcher = $derived(profile.scrapling_mode === "fetcher");

  // Nút bị disable không có tooltip hover được, nên lý do phải là chữ hiện sẵn.
  const hint = $derived(
    isFetcher
      ? "Chế độ Fetcher chỉ gửi HTTP nên không mở được cửa sổ hay dò domain. Đổi chế độ trong Cài đặt nếu cần."
      : !profile.open
        ? "Mở profile để đăng nhập và dò domain."
        : "",
  );

  function lastUsed(ts: number | null): string {
    if (!ts) return "chưa dùng";
    // Server lưu mili-giây.
    const mins = Math.round((Date.now() - ts) / 60000);
    if (mins < 1) return "dùng vừa xong";
    if (mins < 60) return `dùng ${mins} phút trước`;
    if (mins < 1440) return `dùng ${Math.round(mins / 60)} giờ trước`;
    return `dùng ${new Date(ts).toLocaleDateString()}`;
  }
</script>

<header class="grid gap-3">
  <div class="min-w-0">
    <div class="flex flex-wrap items-center gap-2">
      <h3 class="min-w-0 break-all font-data text-lg font-semibold">{profile.name}</h3>
      <Badge variant="outline" class="font-data text-[11px]">{modeLabel(profile.scrapling_mode)}</Badge>
      {#if profile.is_default}<Badge variant="secondary"><Star weight="fill" /> Mặc định</Badge>{/if}
    </div>
    <p class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
      <span class={`size-2 shrink-0 rounded-full ${status.cls}`}></span>
      {status.label} · tối đa {profile.max_tabs} tab · {lastUsed(profile.last_used_at)}
    </p>
    {#if profile.notes}<p class="mt-2 text-sm whitespace-pre-wrap text-muted-foreground">{profile.notes}</p>{/if}
  </div>

  <div class="flex flex-wrap items-center gap-1.5">
    {#if profile.open}
      <Button variant="outline" disabled={busy} onclick={onclose}>
        {#if busyAction === "close"}<CircleNotch class="animate-spin" />{:else}<Stop />{/if} Đóng
      </Button>
    {:else}
      <Button disabled={busy || isFetcher} onclick={onopen}>
        {#if busyAction === "open"}<CircleNotch class="animate-spin" />{:else}<Browser />{/if} Mở
      </Button>
    {/if}
    <Button variant="outline" disabled={busy || !profile.open || isFetcher} onclick={ondetect}>
      {#if busyAction === "detect"}<CircleNotch class="animate-spin" />{:else}<MagnifyingGlass />{/if} Dò domain
    </Button>
    <Button variant="outline" disabled={busy} onclick={onaddaccount}><Plus /> Account</Button>
    <Button variant="ghost" disabled={busy} onclick={onsettings}><GearSix /> Cài đặt</Button>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        {#snippet child({ props })}
          <Button variant="ghost" size="icon" disabled={busy} aria-label={`Thao tác khác cho ${profile.name}`} {...props}>
            {#if busyAction === "export" || busyAction === "delete"}<CircleNotch class="animate-spin" />{:else}<DotsThree weight="bold" />{/if}
          </Button>
        {/snippet}
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" class="min-w-44">
        <DropdownMenu.Item onclick={onexport}><DownloadSimple /> Xuất sang máy khác</DropdownMenu.Item>
        <DropdownMenu.Item onclick={onclone}><Copy /> Nhân bản</DropdownMenu.Item>
        <DropdownMenu.Separator />
        <DropdownMenu.Item variant="destructive" onclick={ondelete}><Trash /> Xóa profile</DropdownMenu.Item>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  </div>
  {#if hint}<p class="text-xs text-muted-foreground">{hint}</p>{/if}
</header>
