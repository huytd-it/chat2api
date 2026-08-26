import { writable } from "svelte/store";
import { toast } from "svelte-sonner";

const STORAGE_KEY = "c2a_key";

function createApiKeyStore() {
  const initial = typeof localStorage !== "undefined" ? (localStorage.getItem(STORAGE_KEY) ?? "") : "";
  const { subscribe, set } = writable(initial);
  return {
    subscribe,
    set(value: string) {
      set(value);
      if (typeof localStorage !== "undefined") localStorage.setItem(STORAGE_KEY, value);
    },
  };
}

/** Bearer key dùng cho mọi request chat + admin, lưu cục bộ trên máy này. */
export const apiKey = createApiKeyStore();

/** Khi bật, request chat từ trang Sessions yêu cầu server hiện cửa sổ
 * Chromium (không headless) thay vì chạy ẩn ở nền. */
export const headedBrowser = writable(false);

export function showToast(message: string) {
  toast(message);
}

/** Lines emitted by the Rust sidecar (stdout/stderr of the Python server). */
export const serverLog = writable<string[]>([]);

export interface ServerStatus {
  state: "loading" | "ok" | "error";
  contexts: string;
  engine: string;
}

export const serverStatus = writable<ServerStatus>({ state: "loading", contexts: "-", engine: "-" });
