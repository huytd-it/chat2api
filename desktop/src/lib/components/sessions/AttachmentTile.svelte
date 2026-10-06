<script lang="ts">
  import { FileText, X } from "phosphor-svelte";
  import { fetchAttachmentUrl, formatBytes, type SessionAttachment } from "../../api";
  import { apiKey, showToast } from "../../stores";
  import * as Dialog from "$lib/components/ui/dialog";

  let {
    attachment,
    sessionId = "",
    onremove,
  }: {
    attachment: SessionAttachment;
    /** Session giữ file đã lưu; bỏ trống với file còn nằm trong composer. */
    sessionId?: string;
    /** Có thì tile hiện nút gỡ (dùng trong composer). */
    onremove?: () => void;
  } = $props();

  const isImage = $derived(attachment.kind !== "file" && attachment.mime.startsWith("image/"));
  let remoteUrl = $state("");
  let failed = $state(false);
  let zoomed = $state(false);
  const url = $derived(attachment.preview_url || remoteUrl);

  // File đã lưu nằm sau Authorization nên phải tải thành object URL; chỉ ảnh
  // mới tải sẵn để vẽ thumbnail, file thường đợi tới lúc người dùng bấm.
  $effect(() => {
    if (!isImage || attachment.preview_url || !sessionId || attachment.id < 0) return;
    let revoked = false;
    let created = "";
    fetchAttachmentUrl($apiKey, sessionId, attachment.id)
      .then((value) => {
        if (revoked) return URL.revokeObjectURL(value);
        created = value;
        remoteUrl = value;
      })
      .catch(() => (failed = true));
    return () => {
      revoked = true;
      if (created) URL.revokeObjectURL(created);
    };
  });

  async function download() {
    try {
      const href = url || (await fetchAttachmentUrl($apiKey, sessionId, attachment.id));
      const link = document.createElement("a");
      link.href = href;
      link.download = attachment.name;
      link.click();
      if (!url) setTimeout(() => URL.revokeObjectURL(href), 10_000);
    } catch (error) {
      showToast("Không tải được file: " + (error as Error).message);
    }
  }
</script>

<div class="group/tile relative">
  {#if isImage && url && !failed}
    <button
      type="button"
      class="block size-16 overflow-hidden rounded-lg border border-border bg-muted transition-colors hover:border-primary/50"
      title={`${attachment.name} · ${formatBytes(attachment.bytes)}`}
      aria-label={`Xem ảnh ${attachment.name}`}
      onclick={() => (zoomed = true)}
    >
      <img src={url} alt={attachment.name} class="size-full object-cover" />
    </button>
  {:else}
    <button
      type="button"
      class="flex h-16 max-w-52 min-w-0 items-center gap-2 rounded-lg border border-border bg-card px-2.5 text-left transition-colors hover:border-primary/40 disabled:pointer-events-none"
      title={onremove ? attachment.name : `Tải ${attachment.name}`}
      disabled={!!onremove || (attachment.id < 0 && !url)}
      onclick={download}
    >
      <span class="grid size-8 flex-none place-items-center rounded-md bg-muted text-primary">
        <FileText size={16} aria-hidden="true" />
      </span>
      <span class="grid min-w-0">
        <strong class="truncate text-[11px] font-semibold">{attachment.name}</strong>
        <small class="truncate font-data text-[9px] text-muted-foreground">
          {formatBytes(attachment.bytes)}{failed ? " · không tải được preview" : ""}
        </small>
      </span>
    </button>
  {/if}

  {#if onremove}
    <button
      type="button"
      class="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full border border-border bg-background text-muted-foreground shadow-sm transition-colors hover:border-destructive/50 hover:text-destructive"
      aria-label={`Gỡ ${attachment.name}`}
      onclick={onremove}
    >
      <X size={10} aria-hidden="true" />
    </button>
  {/if}
</div>

{#if isImage && url}
  <Dialog.Root bind:open={zoomed}>
    <Dialog.Content class="max-w-[min(64rem,94vw)] p-3 sm:max-w-[min(64rem,94vw)]">
      <Dialog.Header>
        <Dialog.Title class="truncate pr-8 font-data text-xs">{attachment.name}</Dialog.Title>
        <Dialog.Description class="font-data text-[10px]">
          {attachment.mime} · {formatBytes(attachment.bytes)}
        </Dialog.Description>
      </Dialog.Header>
      <img src={url} alt={attachment.name} class="mx-auto max-h-[76vh] max-w-full rounded-md object-contain" />
    </Dialog.Content>
  </Dialog.Root>
{/if}
