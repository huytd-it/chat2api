<script lang="ts">
  import { Button } from "$lib/components/ui/button";
  import { GoogleLogo, LinkBreak, LinkSimple, Trash, X } from "phosphor-svelte";
  import type { BulkAction } from "./profile-utils";

  interface Props {
    count: number;
    /** Thứ đang được tick: "profile" hoặc "domain". */
    noun: string;
    /** Thứ sẽ chọn trong dialog: ngược lại với noun. */
    target: string;
    onaction: (action: BulkAction) => void;
    onclear: () => void;
    /** Số dòng đã chọn xoá được; chỉ tab Domain truyền. */
    deletable?: number;
    ondelete?: () => void;
  }
  let { count, noun, target, onaction, onclear, deletable = 0, ondelete }: Props = $props();
</script>

<!-- Luôn hiện để người dùng biết có thao tác hàng loạt và bảng không bị đẩy khi tick. -->
<div class="flex flex-wrap items-center gap-1.5 px-4 py-2 sm:px-6" role="toolbar" aria-label={`Thao tác trên các ${noun} đã chọn`}>
  <span class="mr-2 text-sm text-muted-foreground" aria-live="polite">
    {#if count}<strong class="font-medium text-foreground">{count}</strong> {noun} đã chọn{:else}Tick {noun} để thao tác hàng loạt{/if}
  </span>
  <Button variant="outline" size="sm" disabled={!count} onclick={() => onaction("attach")}><LinkSimple /> Gắn {target}</Button>
  <Button variant="outline" size="sm" disabled={!count} onclick={() => onaction("google")}><GoogleLogo /> Đăng nhập Google</Button>
  <Button variant="outline" size="sm" disabled={!count} onclick={() => onaction("detach")}><LinkBreak /> Gỡ {target}</Button>
  {#if ondelete}<Button variant="destructive" size="sm" disabled={!deletable} title="Chỉ xoá được domain không có recipe" onclick={ondelete}><Trash /> {deletable ? `Xóa domain (${deletable})` : "Xóa domain"}</Button>{/if}
  {#if count}<Button variant="ghost" size="sm" onclick={onclear}><X /> Bỏ chọn</Button>{/if}
</div>
