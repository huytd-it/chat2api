import { writable } from "svelte/store";

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

/** The playground/admin bearer key, persisted locally like the browser build. */
export const apiKey = createApiKeyStore();

export type ViewName = "playground" | "integrations" | "logs";
export const currentView = writable<ViewName>("playground");

/** Khi bật, request chat test trong Playground yêu cầu server hiện cửa sổ
 * Chromium (không headless) thay vì chạy ẩn ở nền. */
export const headedPlayground = writable(false);

export const toastMessage = writable<string | null>(null);
let toastTimer: ReturnType<typeof setTimeout> | undefined;

export function showToast(message: string) {
  toastMessage.set(message);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastMessage.set(null), 3200);
}

/** Lines emitted by the Rust sidecar (stdout/stderr of the Python server). */
export const serverLog = writable<string[]>([]);

export interface ServerStatus {
  state: "loading" | "ok" | "error";
  contexts: string;
  engine: string;
}

export const serverStatus = writable<ServerStatus>({ state: "loading", contexts: "-", engine: "-" });
