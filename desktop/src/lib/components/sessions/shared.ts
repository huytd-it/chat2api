/** Types and pure helpers shared between the Sessions workbench panes.
 *
 * SessionWorkspace owns the state; SessionBank / TestBench / SessionComposer
 * render it. Anything both sides need to agree on lives here so the panes stay
 * presentational and the workspace stays the single source of truth. */
import type { TestTarget } from "../../api";

/** One prompt × one account, i.e. exactly one request the batch will fire. */
export type BatchJob = {
  promptIndex: number;
  prompt: string;
  accountId: number;
  model: string;
  label: string;
  sessionId: string;
  state: "queued" | "running" | "done" | "error";
  detail: string;
};

export type RotationMode = "broadcast" | "round_robin" | "fill_first";

export const SEND_MODES: ReadonlyArray<{
  id: RotationMode;
  label: string;
  help: string;
}> = [
  { id: "broadcast", label: "Mọi target", help: "Mỗi prompt chạy trên tất cả target đã chọn." },
  { id: "round_robin", label: "Vòng tròn", help: "Chia đều prompt cho các target, lần lượt." },
  { id: "fill_first", label: "Lấp đầy", help: "Dùng hết hạn mức của target đầu rồi mới sang cái sau." },
];

/** Model đang chọn cho một target: ưu tiên lựa chọn thủ công, sau đó model đầu
 *  tiên mà recipe của domain đó hỗ trợ. Rỗng nghĩa là target chưa chạy được. */
export function modelFor(target: TestTarget, picked: Record<number, string>): string {
  return picked[target.account_id] || target.models[0] || "";
}

export function formatDate(ts: number): string {
  const date = new Date(ts);
  const today = new Date();
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return date.toLocaleDateString([], { day: "2-digit", month: "2-digit" });
}

export function relativeTime(ts: number): string {
  const delta = Date.now() - ts;
  if (delta < 60_000) return "vừa xong";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} phút`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} giờ`;
  return formatDate(ts);
}
