import type { DomainInfo, GoogleIdentity, ProfileInfo } from "$lib/api";
import type { BadgeVariant } from "$lib/components/ui/badge";

export const PROFILE_NAME_RE = /^[a-z0-9][a-z0-9-]*$/;
export const PROFILE_NAME_ERROR = "Tên profile chỉ gồm chữ thường, số và dấu -";
export const GMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const MAX_TABS_LIMIT = 32;

/** Ba chế độ fetcher của Scrapling; fetcher chỉ gửi HTTP nên không mở được cửa sổ. */
export const SCRAPLING_MODES = [
  { value: "dynamic", label: "Dynamic", detail: "Chromium thường" },
  { value: "stealthy", label: "Stealthy", detail: "chống bot" },
  { value: "fetcher", label: "Fetcher", detail: "chỉ HTTP, không mở browser" },
] as const;

export function modeLabel(mode: string): string {
  return SCRAPLING_MODES.find((m) => m.value === mode)?.label ?? "Dynamic";
}

export function statusOf(p: ProfileInfo): { label: string; cls: string } {
  if (p.locked && !p.open) return { label: "Bị khoá", cls: "bg-destructive" };
  if (p.open) return { label: `Đang chạy · ${p.tabs} tab`, cls: "bg-success" };
  return { label: "Rảnh", cls: "bg-muted-foreground" };
}

export function validTabs(value: unknown): boolean {
  const n = Number(value);
  return Number.isInteger(n) && n >= 1 && n <= MAX_TABS_LIMIT;
}

/** Trạng thái Google mà `GoogleAuthPanel` báo lên cho danh sách. */
export interface GoogleState {
  identity: GoogleIdentity | null;
  waiting: boolean;
}

export const GOOGLE_STATUS: Record<string, { label: string; variant: BadgeVariant }> = {
  signed_in: { label: "Đã đăng nhập", variant: "success" },
  signed_out: { label: "Chưa đăng nhập", variant: "outline" },
  verify_required: { label: "Cần xác minh", variant: "warning" },
  error: { label: "Lỗi", variant: "destructive" },
  unknown: { label: "Chưa kiểm tra", variant: "outline" },
};

export const GOOGLE_SITE_RESULT: Record<string, string> = {
  done: "Đã đăng nhập", already: "Có vẻ đã đăng nhập sẵn", unsure: "Chưa chắc",
  no_button: "Không thấy nút Google", verify_required: "Cần xác minh", error: "Lỗi",
};

export type BulkAction = "attach" | "detach" | "google";

/** Host chỉ đến từ kết quả dò cookie thì server chưa biết, không có gì để xoá. */
export function isDomainDeletable(domains: DomainInfo[], host: string): boolean {
  const found = domains.find((d) => d.host === host);
  return !!found && !found.recipes.length;
}

/** Nhận cả URL dán vào hoặc host gõ tay; trả về host viết thường. */
export function normalizeHost(value: string): string {
  const text = value.trim().toLowerCase();
  if (!text) return "";
  try {
    return new URL(text.includes("://") ? text : `https://${text}`).hostname;
  } catch {
    return text;
  }
}
