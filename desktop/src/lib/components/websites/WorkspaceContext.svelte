<script lang="ts">
  import { X, ArrowSquareOut, Target, FolderSimple, ArrowClockwise, WarningCircle } from "phosphor-svelte";
  import type { SessionDetail, ChatTarget, TestTarget, WebsiteInfo } from "$lib/api";
  import { Button } from "$lib/components/ui/button";
  let { site, session, target, account, project, sending, elapsed, error, onClose, onOpen,
    onTargets, onProject, onRefresh, projectAvailable,
  }: {
    site: WebsiteInfo; session: SessionDetail | null; target: ChatTarget | null;
    account: TestTarget | undefined; project: string; sending: boolean; elapsed: number; error: string;
    projectAvailable: boolean; onClose: () => void; onOpen: () => void;
    onTargets: () => void; onProject: () => void; onRefresh: () => void;
  } = $props();
  const context = $derived(session?.automation);
</script>

<aside class="flex h-full min-h-0 w-full flex-col bg-card" aria-label="Ngữ cảnh & chẩn đoán">
  <div class="flex items-center justify-between px-4 py-4"><h3 class="text-sm font-semibold">Ngữ cảnh & tác vụ</h3><Button size="icon-xs" variant="ghost" aria-label="Đóng ngữ cảnh" onclick={onClose}><X /></Button></div>
  <div class="min-h-0 flex-1 overflow-y-auto px-4 pb-5 text-xs">
    <div class="rounded-lg bg-muted/55 p-3" role="status" aria-live="polite"><p class="font-medium">{sending ? `Đang chờ phản hồi · ${elapsed}s` : context?.busy_operation ? "Tác vụ cần đối soát" : error ? "Lần gửi chưa hoàn tất" : session ? "Đã nạp bản ghi phiên" : "Sẵn sàng soạn yêu cầu"}</p><p class="mt-1.5 leading-relaxed text-muted-foreground">{sending ? "Trạng thái chi tiết browser chưa được telemetry; không đóng profile khi đang chạy." : "Chỉ hiển thị dữ liệu đã đọc được từ server."}</p></div>
    {#if error}<p role="alert" class="mt-3 break-words rounded-md bg-destructive/8 p-3 leading-relaxed text-destructive">{error}</p>{/if}
    <dl class="mt-5 grid gap-4">
      <div><dt class="text-muted-foreground">Account đang dùng</dt><dd class="mt-1 font-medium">{account ? `${account.profile_name} · ${account.label}` : target?.label || (session?.profile_name ? `${session.profile_name} · ${session.account_label || "main"}` : "Chờ server chọn")}</dd></div>
      <div><dt class="text-muted-foreground">Project</dt><dd class="mt-1">{project || context?.project_id || "Chat độc lập"}</dd></div>
      <div><dt class="text-muted-foreground">Context</dt><dd class="mt-1">{context ? `${context.successes} lượt thành công · generation ${context.generation}` : "Chưa có dữ liệu durable"}</dd></div>
      <div><dt class="text-muted-foreground">Session ID</dt><dd class="mt-1 break-all font-mono text-[11px]">{session?.id || "Được tạo khi gửi"}</dd></div>
      {#if context?.busy_operation}<div><dt class="text-muted-foreground">Operation chưa xác nhận</dt><dd class="mt-1 break-all font-mono text-[11px]">{context.busy_operation}</dd></div>{/if}
    </dl>
    {#if target?.contextReset}<p class="mt-4 rounded-md bg-warning/10 p-3 leading-relaxed text-warning">Context đã được mở lại. Lịch sử website cũ không được mang sang.</p>{/if}
    <div class="mt-5 grid gap-1 border-t border-border pt-3">
      <Button variant="ghost" size="sm" class="justify-start" disabled={!session?.site_conversation_url || sending} onclick={onOpen}><ArrowSquareOut /> Mở hội thoại website</Button>
      {#if projectAvailable}<Button variant="ghost" size="sm" class="justify-start" disabled={sending} onclick={onProject}><FolderSimple /> Quản lý project</Button>{/if}
      <Button variant="ghost" size="sm" class="justify-start" onclick={onTargets}><Target /> Account & chạy hàng loạt</Button>
      <Button variant="ghost" size="sm" class="justify-start" disabled={sending} onclick={onRefresh}><ArrowClockwise /> Cập nhật dữ liệu</Button>
    </div>
    <div class="mt-5 border-t border-border pt-4 leading-relaxed text-muted-foreground"><p class="flex items-center gap-1.5 font-medium text-foreground"><WarningCircle size={14} /> Runtime hiện tại</p><p class="mt-1.5">{site.runtime === "legacy" ? "Workspace mới đang dùng engine hiện có. Cutover module automation chưa hoàn tất." : site.runtime === "not_configured" ? "Chưa có driver/model đang chạy cho website này." : "Module automation."}</p><p class="mt-2">Có account không bảo đảm còn đăng nhập. Mở đúng profile để xử lý login hoặc xác minh website.</p><a class="mt-3 inline-block text-primary hover:underline" href={`/websites/${site.id}/settings`}>Cấu hình website</a></div>
  </div>
</aside>
