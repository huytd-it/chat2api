import { invoke } from "@tauri-apps/api/core";

export interface HealthInfo {
  models: number;
  contexts: number;
  engine: string;
}

export interface ModelInfo {
  id: string;
  ready?: boolean;
}

export interface TrialStatus {
  limit: number;
  used: number;
}

export interface RecipeInfo {
  slug: string;
  models: string[];
  unhealthy: boolean;
  type?: string;
  accounts?: number;
  account_names?: string[];
  trial?: TrialStatus | null;
  /** Chỉ có ở BrowserRecipe — trang Integrations dùng để gộp account vào hàng. */
  domain?: string;
  url?: string;
}

export interface LogEntry {
  id: number;
  ts: number;
  level: string;
  message: string;
}

export interface JobStatus {
  status: string;
  log: string[];
  can_complete_login?: boolean;
}

export interface AccountInfo {
  name: string;
  size: number;
  updated_at: number;
}

/** Account thuộc về domain, không thuộc recipe: mọi recipe trong `recipes` dùng chung. */
export interface DomainAccounts {
  domain: string;
  accounts: AccountInfo[];
  recipes: string[];
}

export interface SettingField {
  key: string;
  type: "int" | "bool" | "str" | "secret" | "choice";
  value: string;
  label: string;
  group: string;
  apply: "reload" | "restart";
  help?: string;
  choices?: string[];
  is_set?: boolean;
  /** Giá trị đang dùng đến từ đâu: biến môi trường/.env, bảng `setting`, hay default. */
  source?: "env" | "db" | "default";
  /** true ⇒ .env đang ghim khoá này, lưu từ UI sẽ không đổi được giá trị đang chạy. */
  env_locked?: boolean;
}

/** Một hàng trong bảng `api_key`. Key thô chỉ tồn tại trong response lúc tạo. */
export interface ApiKeyInfo {
  id: number;
  label: string;
  key_prefix: string;
  scopes: string[];
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
}

export interface ApiKeyList {
  keys: ApiKeyInfo[];
  /** false khi kho SQLite chưa mở — lúc đó không tạo được key nào. */
  persisted: boolean;
  /** Số key đến từ CHAT2API_KEYS: không liệt kê được, chỉ đếm. */
  bootstrap_keys: number;
  enforced: boolean;
}

export interface Overview {
  engine: string;
  contexts: number;
  models: number;
  recipes: number;
  browser_recipes: number;
  unhealthy: string[];
  domains: number;
  accounts: number;
  open_browsers: string[];
}

const FALLBACK_BASE_URL = "http://127.0.0.1:8100";

let cachedBase: string | null = null;

/** Resolves the chat2api server URL. Order: `?api=` URL param (per load),
 * `localStorage.c2a_api_base` (persisted dev override — useful when the
 * default 8100 is blocked by Windows reserved ranges), then the Tauri host's
 * sidecar port, then the default dev port when running outside Tauri. */
export async function apiBase(): Promise<string> {
  if (cachedBase) return cachedBase;
  const fromQuery = typeof location !== "undefined"
    ? new URLSearchParams(location.search).get("api")
    : null;
  const override = fromQuery
    ?? (typeof localStorage !== "undefined" ? localStorage.getItem("c2a_api_base") : null);
  if (override) {
    cachedBase = override.replace(/\/+$/, "");
    return cachedBase;
  }
  try {
    cachedBase = await invoke<string>("api_base_url");
  } catch {
    cachedBase = FALLBACK_BASE_URL;
  }
  return cachedBase;
}

function headers(key: string, headed = false, sessionId = ""): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (key) h["Authorization"] = "Bearer " + key;
  if (headed) h["X-Chat2api-Headed"] = "true";
  if (sessionId) h["X-Chat2api-Session-Id"] = sessionId;
  return h;
}

async function asJson(r: Response): Promise<any> {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data?.error?.message || r.statusText);
  return data;
}

export async function fetchHealth(): Promise<HealthInfo> {
  const base = await apiBase();
  const r = await fetch(base + "/health");
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

export async function fetchModels(key: string): Promise<ModelInfo[]> {
  const base = await apiBase();
  const r = await fetch(base + "/v1/models", { headers: headers(key) });
  const data = await asJson(r);
  return ((data.data ?? []) as ModelInfo[]).filter((m) => m.ready !== false);
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface RequestRecord {
  id: number;
  status: string;
  ttfb_ms: number | null;
  duration_ms: number | null;
  fallback_used: number;
  error_code: string | null;
  error_message: string | null;
  prompt_chars: number;
  completion_chars: number;
}

export interface SessionArtifact {
  id: number;
  idx: number;
  kind: string;
  language: string;
  title: string;
  body: string;
}

export interface SessionMessage {
  id: number;
  seq: number;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  content_markdown: string | null;
  content_html: string | null;
  reasoning: string | null;
  finish_reason: string | null;
  error: string | null;
  ttfb_ms: number | null;
  duration_ms: number | null;
  char_count: number;
  created_at: number;
  artifacts: SessionArtifact[];
  request: RequestRecord | null;
}

export interface SessionSummary {
  id: string;
  title: string;
  kind: "chat" | "api" | "probe";
  model_public_id: string;
  recipe_slug: string | null;
  profile_name: string | null;
  account_label: string | null;
  pinned: number;
  archived: number;
  message_count: number;
  total_chars: number;
  error_count: number;
  first_prompt: string | null;
  created_at: number;
  updated_at: number;
}

export interface SessionDetail extends SessionSummary {
  tags: string[];
  messages: SessionMessage[];
}

/** Streams an SSE chat completion, invoking onDelta for each content chunk.
 * `messages` is the full conversation (real-chat semantics) sent as-is to
 * /v1/chat/completions.
 * `headed` asks the server to run the underlying browser recipe with a
 * visible Chromium window instead of headless (recipe providers only — the
 * server ignores it for non-browser providers like Gemini/OpenAI passthrough).
 * When the server grants a live view, `onWatchId` fires with the id to poll
 * via `fetchScreenshot` — this works whether or not a native window actually
 * shows up on the user's machine.
 * Throws when the server reports an error before or MID-stream (SSE error
 * payload) so callers can render the real message instead of a dead pipe. */
export async function streamChat(
  key: string,
  model: string,
  messages: ChatMessage[],
  onDelta: (text: string) => void,
  signal?: AbortSignal,
  headed = false,
  onWatchId?: (watchId: string) => void,
  sessionId = "",
  onSessionId?: (sessionId: string) => void,
): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/v1/chat/completions", {
    method: "POST",
    headers: headers(key, headed, sessionId),
    signal,
    body: JSON.stringify({
      model,
      stream: true,
      messages,
    }),
  });
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data?.error?.message || r.statusText);
  }
  const watchId = r.headers.get("X-Chat2api-Watch-Id");
  if (watchId && onWatchId) onWatchId(watchId);
  const resolvedSessionId = r.headers.get("X-Chat2api-Session-Id");
  if (resolvedSessionId && onSessionId) onSessionId(resolvedSessionId);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, idx).trim();
      buf = buf.slice(idx + 1);
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6);
      if (payload === "[DONE]") continue;
      const parsed = JSON.parse(payload);
      // Lỗi nổ giữa stream được server bọc trong SSE event thay vì cắt
      // kết nối — surface đúng thông điệp (timeout, hết lượt thử...).
      if (parsed.error) throw new Error(parsed.error.message || String(parsed.error));
      const delta = parsed.choices?.[0]?.delta?.content ?? "";
      if (delta) onDelta(delta);
    }
  }
}

/** Fetches one live-view frame (JPEG) for a watch id from streamChat's
 * onWatchId or an Integrate job id (job ids double as their own watch id
 * when the "hiện browser" checkbox was on). Returns null if there's no
 * active browser page for that id right now (e.g. the request finished). */
export async function fetchScreenshot(key: string, watchId: string): Promise<Blob | null> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/watch/" + encodeURIComponent(watchId) + "/screenshot", {
    headers: headers(key),
  });
  if (!r.ok) return null;
  return r.blob();
}

export async function fetchRecipes(key: string): Promise<RecipeInfo[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes", { headers: headers(key) });
  return asJson(r);
}

export async function reloadRecipe(key: string, slug: string): Promise<void> {
  const base = await apiBase();
  await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/reload", {
    method: "POST",
    headers: headers(key),
  });
}

export async function closeRecipeBrowser(key: string, slug: string): Promise<number> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/browser/close", {
    method: "POST",
    headers: headers(key),
  });
  const data = await asJson(r);
  return data.closed ?? 0;
}

export async function deleteRecipe(key: string, slug: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug), {
    method: "DELETE",
    headers: headers(key),
  });
  await asJson(r);
}

export async function startIntegration(
  key: string,
  url: string,
  headed = false,
): Promise<{ job_id: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/integrate", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ url, headed }),
  });
  return asJson(r);
}

export async function fetchJob(key: string, jobId: string, signal?: AbortSignal): Promise<JobStatus> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/integrate/" + encodeURIComponent(jobId), {
    headers: headers(key),
    signal,
  });
  return asJson(r);
}

export async function jobAction(
  key: string,
  jobId: string,
  action: "login-complete" | "cancel",
): Promise<JobStatus> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/integrate/" + encodeURIComponent(jobId) + "/" + action, {
    method: "POST",
    headers: headers(key),
  });
  return asJson(r);
}

/** Opens a Chromium window (on the machine running the chat2api server) for
 * the given recipe's URL so the user can log in and register a new account. */
export async function startAccountLogin(key: string, slug: string): Promise<{ session_id: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/accounts", {
    method: "POST",
    headers: headers(key),
  });
  return asJson(r);
}

export async function completeAccountLogin(
  key: string,
  slug: string,
  sessionId: string,
  name: string,
): Promise<{ ok: true; slug: string; account: string }> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/recipes/" + encodeURIComponent(slug) + "/accounts/" + encodeURIComponent(sessionId) + "/complete",
    { method: "POST", headers: headers(key), body: JSON.stringify({ name }) },
  );
  return asJson(r);
}

export async function cancelAccountLogin(key: string, slug: string, sessionId: string): Promise<void> {
  const base = await apiBase();
  await fetch(
    base + "/admin/recipes/" + encodeURIComponent(slug) + "/accounts/" + encodeURIComponent(sessionId) + "/cancel",
    { method: "POST", headers: headers(key) },
  );
}

/** Re-opens a Chromium window preloaded with an already-saved account's
 * profile (its storage_state) instead of a blank one — for re-login when a
 * saved session has expired. Save the result via completeAccountLogin with
 * the same account name to overwrite its storage_state in place. */
export async function reopenAccountLogin(
  key: string,
  slug: string,
  name: string,
): Promise<{ session_id: string; name: string }> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/recipes/" + encodeURIComponent(slug) + "/accounts/" + encodeURIComponent(name) + "/reopen",
    { method: "POST", headers: headers(key) },
  );
  return asJson(r);
}

/** Every domain that has saved accounts, plus which recipes use each domain. */
export async function fetchAccounts(key: string): Promise<DomainAccounts[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/accounts", { headers: headers(key) });
  return asJson(r);
}

/** Opens a Chromium window for a domain (not tied to any recipe). Pass `name`
 * to preload an existing account's profile for re-login. */
export async function startDomainLogin(
  key: string,
  domain: string,
  url = "",
  name = "",
): Promise<{ session_id: string; domain: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/accounts/login", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ domain, url, name }),
  });
  return asJson(r);
}

/** Lưu phiên đăng nhập. `domain` rỗng là hợp lệ: server đọc cookie của
 * context rồi tự suy ra domain. `suggested` là những domain khác cùng phiên
 * còn đăng nhập mà chưa có account nào. */
export async function completeDomainLogin(
  key: string,
  sessionId: string,
  domain: string,
  name: string,
): Promise<{ ok: true; domain: string; name: string; suggested: string[] }> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/accounts/login/" + encodeURIComponent(sessionId) + "/complete",
    { method: "POST", headers: headers(key), body: JSON.stringify({ domain, name }) },
  );
  return asJson(r);
}

export async function reopenDomainAccount(
  key: string,
  domain: string,
  name: string,
): Promise<{ session_id: string; domain: string; name: string }> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/accounts/" + encodeURIComponent(domain) + "/" + encodeURIComponent(name) + "/reopen",
    { method: "POST", headers: headers(key) },
  );
  return asJson(r);
}

export async function deleteDomainAccount(key: string, domain: string, name: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/accounts/" + encodeURIComponent(domain) + "/" + encodeURIComponent(name),
    { method: "DELETE", headers: headers(key) },
  );
  await asJson(r);
}

export async function fetchSettings(
  key: string,
): Promise<{ fields: SettingField[]; env_path: string; persisted: boolean }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/settings", { headers: headers(key) });
  return asJson(r);
}

export async function saveSettings(
  key: string,
  values: Record<string, string>,
): Promise<{ saved: string[]; needs_restart: string[]; shadowed: string[] }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/settings", {
    method: "PUT",
    headers: headers(key),
    body: JSON.stringify({ values }),
  });
  return asJson(r);
}

export async function fetchApiKeys(key: string): Promise<ApiKeyList> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/api-keys", { headers: headers(key) });
  return asJson(r);
}

/** Tạo key mới. `key` trong kết quả là key thô — server không lưu nó, chỉ lưu
 * sha256, nên đây là lần duy nhất đọc được. */
export async function createApiKey(
  key: string,
  label: string,
  scopes?: string,
): Promise<ApiKeyInfo & { key: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/api-keys", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ label, scopes: scopes ?? null }),
  });
  return asJson(r);
}

/** `purge` xoá hẳn hàng; mặc định chỉ thu hồi để request_log còn truy ngược được. */
export async function deleteApiKey(
  key: string,
  id: number,
  purge = false,
): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/api-keys/" + id + "?purge=" + purge, {
    method: "DELETE",
    headers: headers(key),
  });
  await asJson(r);
}

export async function fetchOverview(key: string): Promise<Overview> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/overview", { headers: headers(key) });
  return asJson(r);
}

/** Polls the server-wide activity log (requests, integrate/login/account
 * events, errors) — distinct from a single Integrate job's `log`. Pass the
 * last received entry's `id` as `after` to fetch only new lines. */
export async function fetchLogs(key: string, after = 0): Promise<LogEntry[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/logs?after=" + after, { headers: headers(key) });
  const data = await asJson(r);
  return data.entries as LogEntry[];
}

export interface ProfileAccount {
  id: number;
  label: string;
  host: string;
  status: string;
  disabled: number;
}

export interface ProfileInfo {
  id: number;
  name: string;
  user_data_dir: string;
  headless: number;
  max_tabs: number;
  engine: string;
  is_default: number;
  domains: number;
  locked: boolean;
  open: boolean;
  tabs: number;
  notes: string;
  last_used_at: number | null;
  accounts: ProfileAccount[];
}

export interface ProfileList {
  profiles: ProfileInfo[];
  mode: "storage_state" | "profile";
  profiles_dir: string;
  max_profiles: number;
  /** false khi kho SQLite chưa mở — profile là hàng DB nên lúc đó không có gì. */
  persisted: boolean;
}

/** Các cột người dùng sửa được từ UI (tên profile là thư mục Chromium, không đổi). */
export interface ProfileValues {
  engine?: string;
  headless?: boolean;
  max_tabs?: number;
  proxy?: string;
  user_agent?: string;
  locale?: string;
  timezone?: string;
  viewport?: string;
  notes?: string;
  is_default?: boolean;
}

export interface DomainInfo {
  host: string;
  accounts: number;
  recipes: string[];
}

export async function fetchProfiles(key: string): Promise<ProfileList> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles", { headers: headers(key) });
  return asJson(r);
}

export async function createProfile(
  key: string,
  name: string,
  values: ProfileValues = {},
): Promise<ProfileInfo> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ name, ...values }),
  });
  return asJson(r);
}

export async function updateProfile(
  key: string,
  ident: string | number,
  values: ProfileValues,
): Promise<ProfileInfo> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles/" + encodeURIComponent(String(ident)), {
    method: "PATCH",
    headers: headers(key),
    body: JSON.stringify(values),
  });
  return asJson(r);
}

/** Xoá profile. Server từ chối (409) khi còn recipe dựa vào nó. `purge` xoá
 * luôn thư mục Chromium — mọi đăng nhập trong profile mất theo. */
export async function deleteProfile(
  key: string,
  ident: string | number,
  purge = false,
): Promise<void> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/profiles/" + encodeURIComponent(String(ident)) + "?purge=" + purge,
    { method: "DELETE", headers: headers(key) },
  );
  await asJson(r);
}

/** Mở cửa sổ profile trên máy chạy server để đăng nhập tay. `headless: true`
 * trong kết quả nghĩa là profile đã chạy nền từ trước nên không có cửa sổ nào
 * hiện ra — xem qua live view bằng `watch_id`. */
export async function openProfile(
  key: string,
  ident: string | number,
  url = "",
): Promise<{ profile: string; watch_id: string; headless: boolean }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles/" + encodeURIComponent(String(ident)) + "/open", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ url }),
  });
  return asJson(r);
}

/** Quét cookie của profile đang mở: domain nào còn đăng nhập mà chưa khai báo. */
export async function detectProfileDomains(
  key: string,
  ident: string | number,
): Promise<{ profile: string; known: string[]; suggested: string[] }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles/" + encodeURIComponent(String(ident)) + "/detect", {
    method: "POST",
    headers: headers(key),
  });
  return asJson(r);
}

/** Ghi nhận "profile này đã đăng nhập domain kia" (tạo domain nếu chưa có). */
export async function addProfileAccount(
  key: string,
  ident: string | number,
  domain: string,
  label: string,
): Promise<{ ok: true; account: ProfileAccount }> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/profiles/" + encodeURIComponent(String(ident)) + "/accounts",
    { method: "POST", headers: headers(key), body: JSON.stringify({ domain, label }) },
  );
  return asJson(r);
}

/** Mọi domain đã biết (DB + đĩa + recipe) — gợi ý cho ô Domain của dialog. */
export async function fetchDomains(key: string): Promise<DomainInfo[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/domains", { headers: headers(key) });
  const data = await asJson(r);
  return data.domains as DomainInfo[];
}

export async function closeProfile(key: string, name: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles/" + encodeURIComponent(name) + "/close", {
    method: "POST",
    headers: headers(key),
  });
  await asJson(r);
}

export async function fetchSessions(
  key: string,
  query = "",
  model = "",
  archived = false,
): Promise<SessionSummary[]> {
  const base = await apiBase();
  const params = new URLSearchParams();
  if (query) params.set("q", query);
  if (model) params.set("model", model);
  if (archived) params.set("archived", "true");
  const r = await fetch(base + "/admin/sessions?" + params, { headers: headers(key) });
  const data = await asJson(r);
  return data.sessions as SessionSummary[];
}

export async function fetchSession(key: string, sessionId: string): Promise<SessionDetail> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/sessions/" + encodeURIComponent(sessionId), {
    headers: headers(key),
  });
  return asJson(r);
}

export async function updateSession(
  key: string,
  sessionId: string,
  values: {
    title?: string;
    pinned?: boolean | number;
    archived?: boolean | number;
    tags?: string[];
  },
): Promise<SessionDetail> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/sessions/" + encodeURIComponent(sessionId), {
    method: "PATCH",
    headers: headers(key),
    body: JSON.stringify(values),
  });
  return asJson(r);
}

export async function deleteSession(key: string, sessionId: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/sessions/" + encodeURIComponent(sessionId), {
    method: "DELETE",
    headers: headers(key),
  });
  await asJson(r);
}

export async function forkSession(
  key: string,
  sessionId: string,
  upToSeq: number,
): Promise<SessionDetail> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/sessions/" + encodeURIComponent(sessionId) + "/fork", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ up_to_seq: upToSeq }),
  });
  return asJson(r);
}

export async function exportSession(
  key: string,
  sessionId: string,
  format: "md" | "html" | "json" | "jsonl",
): Promise<Blob> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/sessions/" + encodeURIComponent(sessionId) + "/export?format=" + format,
    { headers: headers(key) },
  );
  if (!r.ok) await asJson(r);
  return r.blob();
}
