<script lang="ts">
  // Project thật trên website: danh sách theo account, tạo mới kèm chỉ dẫn và
  // file chung, chọn để chat trong project, hoặc xóa cả trên website lẫn local.
  import {
    ArrowClockwise,
    FileText,
    FolderSimple,
    Plus,
    Trash,
    WarningCircle,
  } from "phosphor-svelte";
  import {
    createProject,
    deleteProject,
    fetchProjects,
    formatBytes,
    type ProjectFileInput,
    type ProjectSummary,
  } from "../../api";
  import { apiKey, headedBrowser, showToast } from "../../stores";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button";
  import { Input } from "$lib/components/ui/input";
  import { Label } from "$lib/components/ui/label";
  import { Textarea } from "$lib/components/ui/textarea";

  let {
    open = $bindable(),
    model,
    accountId,
    selectedId = $bindable(""),
    selectedTitle = $bindable(""),
    accountLabel = "",
    onChanged,
  }: {
    open: boolean;
    model: string;
    accountId: number | null;
    selectedId: string;
    selectedTitle: string;
    accountLabel?: string;
    onChanged?: () => void;
  } = $props();

  let projects = $state<ProjectSummary[]>([]);
  let loading = $state(false);
  let creating = $state(false);
  let showCreate = $state(false);
  let title = $state("");
  let instructions = $state("");
  let files = $state<ProjectFileInput[]>([]);
  let fileEl = $state<HTMLInputElement | null>(null);

  const canUse = $derived(Boolean(accountId && model));

  $effect(() => {
    if (open && canUse) void load();
  });

  async function load() {
    if (!accountId || !model) return;
    loading = true;
    try {
      projects = await fetchProjects($apiKey, model, accountId, $headedBrowser);
      if (selectedId && !projects.some((item) => item.id === selectedId)) {
        selectedId = "";
        selectedTitle = "";
      } else if (selectedId) {
        selectedTitle = projects.find((item) => item.id === selectedId)?.title ?? selectedTitle;
      }
      onChanged?.();
    } catch (error) {
      showToast("Không nạp được project: " + (error as Error).message);
    } finally {
      loading = false;
    }
  }

  function pick(id: string, title = "") {
    selectedId = id;
    selectedTitle = title;
  }

  async function remove(item: ProjectSummary) {
    if (!confirm(`Xóa project "${item.title}" trên website và dữ liệu local?`)) return;
    try {
      await deleteProject($apiKey, item.id, model, $headedBrowser);
      projects = projects.filter((entry) => entry.id !== item.id);
      if (selectedId === item.id) {
        selectedId = "";
        selectedTitle = "";
      }
      onChanged?.();
      showToast(`Đã xóa project "${item.title}".`);
    } catch (error) {
      showToast("Không xóa được project: " + (error as Error).message);
    }
  }

  function toBase64(bytes: Uint8Array): string {
    let binary = "";
    const chunk = 0x8000;
    for (let index = 0; index < bytes.length; index += chunk) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
    }
    return btoa(binary);
  }

  async function addFiles(incoming: Iterable<File>) {
    const accepted: ProjectFileInput[] = [];
    let total = files.reduce((sum, item) => sum + item.data.length * 0.75, 0);
    for (const file of incoming) {
      if (total + file.size > 20 * 1024 * 1024) {
        showToast("Tổng file project tối đa 20 MiB — bỏ qua phần vượt.");
        break;
      }
      const bytes = new Uint8Array(await file.arrayBuffer());
      accepted.push({
        name: file.name,
        mime: file.type || "application/octet-stream",
        data: toBase64(bytes),
      });
      total += file.size;
    }
    files = [...files, ...accepted];
  }

  function onPick(event: Event) {
    const input = event.currentTarget as HTMLInputElement;
    void addFiles(input.files ?? []);
    input.value = "";
  }

  async function submit() {
    if (!accountId || !model || !title.trim() || creating) return;
    creating = true;
    try {
      const item = await createProject(
        $apiKey,
        {
          id: `proj-${crypto.randomUUID().replaceAll("-", "").slice(0, 16)}`,
          model,
          account_id: accountId,
          title: title.trim(),
          instructions: instructions.trim(),
          files,
        },
        $headedBrowser,
      );
      projects = [item, ...projects.filter((entry) => entry.id !== item.id)];
      selectedId = item.id;
      selectedTitle = item.title;
      showCreate = false;
      title = "";
      instructions = "";
      files = [];
      onChanged?.();
      showToast(`Đã tạo project "${item.title}".`);
    } catch (error) {
      showToast("Không tạo được project: " + (error as Error).message);
    } finally {
      creating = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title class="flex items-center gap-2">
        <FolderSimple class="text-primary" />
        Project trên website
      </Dialog.Title>
      <Dialog.Description>
        {#if canUse}
          {accountLabel || `Account #${accountId}`} · {model}. Chỉ dẫn và file chung được lưu cùng
          project; chat trong project không nhập lịch sử chat cũ.
        {:else}
          Chọn một account trước khi dùng project.
        {/if}
      </Dialog.Description>
    </Dialog.Header>

    {#if canUse}
      <div class="grid gap-3">
        <div class="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={loading} onclick={load}>
            <ArrowClockwise />
            {loading ? "Đang quét…" : "Nạp lại"}
          </Button>
          <Button size="sm" variant={showCreate ? "secondary" : "outline"} onclick={() => (showCreate = !showCreate)}>
            <Plus />
            Tạo project
          </Button>
          <span class="ml-auto font-data text-[10px] text-muted-foreground">
            {projects.length} project
          </span>
        </div>

        <p class="flex items-start gap-1.5 rounded-lg bg-warning/10 p-2 text-[10px] leading-relaxed text-warning">
          <WarningCircle size={13} class="mt-px flex-none" aria-hidden="true" />
          Mở danh sách/tạo/xóa project sẽ mở Chromium của account và có thể mất vài giây. Không chạy
          đồng thời với một lượt chat trên cùng account.
        </p>

        {#if showCreate}
          <div class="grid gap-2 rounded-lg bg-muted/60 p-3">
            <Label for="project-title" class="text-[11px]">Tên project</Label>
            <Input id="project-title" bind:value={title} placeholder="Ví dụ: Dịch truyện A" />
            <Label for="project-instructions" class="mt-1 text-[11px]">Chỉ dẫn chung</Label>
            <Textarea
              id="project-instructions"
              class="min-h-20 resize-y text-xs"
              bind:value={instructions}
              placeholder="Thuật ngữ, văn phong, quy tắc dịch…"
            />
            <div class="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" onclick={() => fileEl?.click()}>
                <Plus />
                Thêm file chung
              </Button>
              <span class="text-[10px] text-muted-foreground">Tối đa 20 MiB tổng cộng</span>
            </div>
            <input
              class="hidden"
              type="file"
              multiple
              tabindex="-1"
              aria-hidden="true"
              bind:this={fileEl}
              onchange={onPick}
            />
            {#if files.length}
              <ul class="grid gap-1">
                {#each files as file, index (index)}
                  <li class="flex items-center gap-2 rounded border border-border bg-background/60 px-2 py-1 text-[10px]">
                    <FileText class="flex-none" />
                    <span class="min-w-0 flex-1 truncate">{file.name}</span>
                    <span class="flex-none font-data text-muted-foreground">
                      {formatBytes(Math.round(file.data.length * 0.75))}
                    </span>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Bỏ ${file.name}`}
                      onclick={() => (files = files.filter((_, position) => position !== index))}
                    >
                      <Trash />
                    </Button>
                  </li>
                {/each}
              </ul>
            {/if}
            <div class="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onclick={() => (showCreate = false)}>Hủy</Button>
              <Button size="sm" disabled={!title.trim() || creating} onclick={submit}>
                {creating ? "Đang tạo…" : "Tạo trên website"}
              </Button>
            </div>
          </div>
        {/if}

        <div class="grid max-h-72 gap-1.5 overflow-y-auto">
          <button
            type="button"
            class="rounded-lg border px-3 py-2 text-left text-xs transition-colors
              {selectedId === ''
                ? 'border-primary bg-primary/8'
                : 'border-border hover:bg-muted'}"
            aria-pressed={selectedId === ""}
            onclick={() => pick("")}
          >
            <span class="font-medium">Không dùng project</span>
            <span class="mt-0.5 block text-[10px] text-muted-foreground">
              Chat độc lập; mỗi session vẫn giữ liên kết hội thoại riêng.
            </span>
          </button>

          {#if loading && !projects.length}
            <p class="px-3 py-6 text-center text-xs text-muted-foreground">Đang mở account để quét project…</p>
          {:else if !projects.length}
            <p class="px-3 py-6 text-center text-xs text-muted-foreground">
              Account này chưa có project. Tạo project mới hoặc chọn chat độc lập.
            </p>
          {:else}
            {#each projects as item (item.id)}
              <div
                class="flex items-center gap-1 rounded-lg border transition-colors
                  {selectedId === item.id ? 'border-primary bg-primary/8' : 'border-border'}"
              >
                <button
                  type="button"
                  class="min-w-0 flex-1 px-3 py-2 text-left"
                  aria-pressed={selectedId === item.id}
                  onclick={() => pick(item.id, item.title)}
                >
                  <span class="block truncate text-xs font-medium">{item.title}</span>
                  <span class="mt-0.5 block truncate font-data text-[10px] text-muted-foreground">
                    {item.id} · {item.files.length} file
                    {item.instructions ? " · có chỉ dẫn" : ""}
                  </span>
                </button>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  class="mr-1 flex-none text-destructive"
                  title="Xóa project trên website"
                  onclick={() => remove(item)}
                >
                  <Trash />
                </Button>
              </div>
            {/each}
          {/if}
        </div>
      </div>
    {:else}
      <p class="rounded-lg bg-muted/60 p-3 text-xs text-muted-foreground">
        Project cần một account cụ thể. Chọn account ở ô phía trên (hoặc chọn đúng một target ở Bàn
        test) rồi mở lại.
      </p>
    {/if}

    <Dialog.Footer>
      <Button size="sm" onclick={() => (open = false)}>Đóng</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
