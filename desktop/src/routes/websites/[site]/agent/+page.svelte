<script lang="ts">
  import { page } from "$app/state";
  import { apiKey } from "$lib/stores";
  import { websites } from "$lib/websites";
  import { fetchWebsiteAgentBrief } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  import { Textarea } from "$lib/components/ui/textarea";
  import { Copy, Terminal } from "phosphor-svelte";
  const site = $derived($websites.find(item => item.id === page.params.site));
  let requirement = $state("");
  let busy = $state(false);
  let error = $state("");
  let brief = $state("");
  let copied = $state(false);
  async function prepare() {
    if (!site || busy) return;
    busy = true; error = ""; copied = false;
    try {
      brief = await fetchWebsiteAgentBrief($apiKey, site.id, requirement);
      try { await navigator.clipboard.writeText(brief); copied = true; }
      catch { error = "Không truy cập được clipboard. Bạn có thể sao chép nội dung bên dưới."; }
    } catch (cause) { error = (cause as Error).message; }
    finally { busy = false; }
  }
</script>

<div class="min-h-0 flex-1 overflow-y-auto px-5 py-8 md:px-10">
  <div class="mx-auto max-w-3xl">
    {#if site}
      <a class="text-sm text-primary hover:underline" href={`/websites/${site.id}`}>Về cấu hình {site.title}</a>
      <h2 class="mt-6 text-2xl font-semibold">Tạo automation bằng agent CLI</h2>
      <p class="mt-3 text-sm leading-relaxed text-muted-foreground">Domain <strong class="font-medium text-foreground">{new URL(site.url).hostname}</strong> đã được lưu. Mô tả các thao tác bạn cần rồi gửi yêu cầu cho coding agent đang chạy trong repository chat2api.</p>
      <label for="agent-requirement" class="mb-2 mt-7 block text-sm font-medium">Bạn muốn automation làm gì?</label>
      <Textarea id="agent-requirement" rows={5} maxlength={20000} bind:value={requirement} placeholder="Ví dụ: chọn model, bật Thinking, tải file và lấy câu trả lời; giữ phiên riêng cho từng tác phẩm…" />
      <Button class="mt-4" disabled={busy || !requirement.trim()} onclick={prepare}><Copy />{busy ? "Đang chuẩn bị…" : "Copy yêu cầu cho agent"}</Button>
      {#if copied}<p role="status" class="mt-3 text-sm text-success">Đã sao chép. Dán vào agent CLI của bạn để triển khai.</p>{/if}
      {#if error}<p role="alert" class="mt-3 text-sm text-destructive">{error}</p>{/if}
      <div class="mt-8 rounded-xl bg-muted/50 p-5"><h3 class="flex items-center gap-2 text-sm font-medium"><Terminal size={17} /> Hoặc chuẩn bị yêu cầu từ terminal</h3><pre class="mt-3 overflow-x-auto whitespace-pre-wrap break-all font-mono text-xs leading-relaxed">python -m chat2api website brief {site.url} --request "Mô tả automation cần tạo"</pre><p class="mt-3 text-xs leading-relaxed text-muted-foreground">Lệnh chỉ in brief, không tự gọi LLM hoặc điều khiển website. Agent CLI sẽ sửa code/cấu hình theo brief; kiểm thử và reload riêng sau khi triển khai.</p></div>
      {#if brief}<details class="mt-6"><summary class="cursor-pointer text-sm font-medium">Xem nội dung gửi agent</summary><pre class="mt-3 whitespace-pre-wrap break-words rounded-lg bg-muted/40 p-4 font-mono text-xs leading-relaxed">{brief}</pre></details>{/if}
      <a href={`/websites/${site.id}`} class="mt-7 inline-block text-sm text-primary hover:underline">Cấu hình và công cụ nâng cao</a>
    {:else}<p class="text-sm text-muted-foreground">Đang nạp website. Nếu không có dữ liệu, quay lại danh sách.</p><a href="/" class="mt-4 inline-block text-primary">Web chats</a>{/if}
  </div>
</div>
