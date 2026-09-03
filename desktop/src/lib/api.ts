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

/** Loại thao tác trong một đoạn ghi. Khớp `chat2api/flows.py`.
 *
 * Là `string` chứ không phải union bốn giá trị: recipe đặt được flow tên riêng
 * (`deep_research`, `canvas`…) và UI phải mang được những tên đó. Bốn tên dưới
 * đây chỉ là các flow CÓ SẴN, dùng để gợi ý và để xếp thứ tự hiển thị. */
export type FlowKind = string;

/** Flow có sẵn, đúng thứ tự hiển thị của `flows.FLOW_KINDS`. */
export const FLOW_KINDS: FlowKind[] = ["select_model", "text", "image", "video"];

/** Hình dạng kết quả mà một flow tự đặt tên phải khai qua `type`. */
export const FLOW_TYPES = ["text", "image", "video"] as const;

const BUILTIN_FLOW_LABELS: Record<string, string> = {
  select_model: "Chọn model",
  text: "Generate text",
  image: "Generate image",
  video: "Generate video",
};

/** Nhãn hiển thị; flow tự đặt tên hiện chính tên của nó. Khớp `flow_label`. */
export function flowLabel(kind: FlowKind): string {
  return BUILTIN_FLOW_LABELS[kind] ?? kind;
}

/** Giữ tên cũ cho code đang đọc trực tiếp — tra tên lạ sẽ ra `undefined`, nên
 * chỗ nào hiển thị cho người dùng thì gọi `flowLabel` chứ đừng tra bảng này. */
export const FLOW_LABELS = BUILTIN_FLOW_LABELS;

/** Tên flow hợp lệ không — khớp `FLOW_NAME_RE` phía server. */
export function flowNameOk(name: string): boolean {
  return FLOW_KINDS.includes(name) || /^[a-z][a-z0-9_]{0,39}$/.test(name);
}

/** Flow có sẵn trước, tên tự đặt giữ thứ tự khai báo. Khớp `ordered_flows`. */
export function orderedFlows(names: Iterable<FlowKind>): FlowKind[] {
  const seen = [...new Set(names)];
  return [
    ...FLOW_KINDS.filter((k) => seen.includes(k)),
    ...seen.filter((k) => !FLOW_KINDS.includes(k)),
  ];
}

/** Một đoạn đã ghi trong phiên: ghi cho việc gì và bắt được bao nhiêu thao tác. */
export interface RecordSegment {
  flow: FlowKind;
  events: number;
  open: boolean;
}

export interface JobStatus {
  status: string;
  kind?: string;
  log: string[];
  can_complete_login?: boolean;
  can_finish_record?: boolean;
  slug?: string;
  /** Đoạn đang ghi, null khi không ghi đoạn nào. */
  segment?: FlowKind | null;
  segments?: RecordSegment[];
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

export interface RequestRoute {
  id: number;
  session_id: string | null;
  model_public_id: string;
  recipe_slug: string | null;
  account_label: string | null;
  profile_name: string | null;
  domain: string | null;
  status: "running" | "ok" | "error" | "timeout" | "trial_limit" | "cancelled";
  started_at: number;
  ttfb_ms: number | null;
  duration_ms: number | null;
  stream: number;
  fallback_used: number;
  error_code: string | null;
}

export interface SessionDistribution {
  recipe_slug: string;
  profile_name: string;
  account_label: string;
  domain: string;
  sessions: number;
  active: number;
  errors: number;
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
  request_routes: RequestRoute[];
  requests_last_minute: number;
  session_distribution: SessionDistribution[];
  routes_persisted: boolean;
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

function headers(key: string, headed?: boolean, sessionId = "", accountId?: number): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (key) h["Authorization"] = "Bearer " + key;
  // Gửi cả "false" chứ không chỉ "true": bỏ header đi nghĩa là "tuỳ server"
  // (API_HEADED rồi tới ô Chạy ẩn của profile), mà ô chọn ở Settings là ý muốn
  // dứt khoát của người dùng cho request gửi từ desktop.
  if (headed !== undefined) h["X-Chat2api-Headed"] = headed ? "true" : "false";
  if (sessionId) h["X-Chat2api-Session-Id"] = sessionId;
  if (accountId != null) h["X-Chat2api-Account-Id"] = String(accountId);
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
  /** Account/profile mà ĐÚNG request này đã chạy trên. Null khi provider không
   * phải browser recipe (Gemini, passthrough) hoặc khi agent fallback đã chạy
   * thay recipe. */
  account_id: number | null;
  account_label: string | null;
  account_host: string | null;
  profile_id: number | null;
  profile_name: string | null;
  /** Link hội thoại thật trên site nguồn — mở ra là thấy đúng lượt chat này. */
  conversation_url: string | null;
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
  account_host: string | null;
  account_id: number | null;
  profile_id: number | null;
  site_conversation_url: string | null;
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

/** Account/profile mà server đã chọn cho một request — đọc từ header response,
 * có ngay từ byte đầu nên UI nói được "đang gửi tới đâu" trong lúc còn stream. */
export interface ChatTarget {
  sessionId: string;
  accountId: number | null;
  accountLabel: string;
  profileId: number | null;
  profileName: string;
  /** 'profile/host/account' — một dòng hiển thị sẵn. */
  label: string;
}

function readTarget(r: Response): ChatTarget {
  const num = (name: string) => {
    const raw = r.headers.get(name);
    const value = raw ? Number(raw) : NaN;
    return Number.isFinite(value) ? value : null;
  };
  return {
    sessionId: r.headers.get("X-Chat2api-Session-Id") ?? "",
    accountId: num("X-Chat2api-Account-Id"),
    accountLabel: r.headers.get("X-Chat2api-Account-Label") ?? "",
    profileId: num("X-Chat2api-Profile-Id"),
    profileName: r.headers.get("X-Chat2api-Profile-Name") ?? "",
    label: r.headers.get("X-Chat2api-Target") ?? "",
  };
}

/** Streams an SSE chat completion, invoking onDelta for each content chunk.
 * `messages` is the full conversation (real-chat semantics) sent as-is to
 * /v1/chat/completions.
 * `headed` asks the server to run the underlying browser recipe with a
 * visible Chromium window instead of headless (recipe providers only — the
 * server ignores it for non-browser providers like Gemini/OpenAI passthrough).
 * Throws when the server reports an error before or MID-stream (SSE error
 * payload) so callers can render the real message instead of a dead pipe. */
export async function streamChat(
  key: string,
  model: string,
  messages: ChatMessage[],
  onDelta: (text: string) => void,
  signal?: AbortSignal,
  headed?: boolean,
  sessionId = "",
  onSessionId?: (sessionId: string) => void,
  accountId?: number,
  onTarget?: (target: ChatTarget) => void,
): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/v1/chat/completions", {
    method: "POST",
    headers: headers(key, headed, sessionId, accountId),
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
  const target = readTarget(r);
  if (target.sessionId && onSessionId) onSessionId(target.sessionId);
  if (onTarget) onTarget(target);
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

/** Một ô trong ma trận profile × domain × account của bàn test.
 * `models` là các model public id chạy được account này (rỗng ⇒ chưa có recipe
 * nào phục vụ domain đó, chọn cũng không gửi được). */
export interface TestTarget {
  account_id: number;
  label: string;
  host: string;
  domain: string;
  status: string;
  profile_id: number;
  profile_name: string;
  profile_headless: boolean;
  profile_open: boolean;
  profile_tabs: number;
  profile_max_tabs: number;
  recipes: string[];
  models: string[];
  ready: boolean;
  /** Request đang chạy trên account này ngay lúc này. */
  busy: number;
}

export interface TestTargetList {
  targets: TestTarget[];
  /** Trần số profile Chromium mở cùng lúc (POOL_MAX_PROFILES). */
  max_profiles: number;
  /** Trần số tab trong MỘT profile (PROFILE_MAX_TABS). */
  max_tabs: number;
  profile_mode: "storage_state" | "profile";
  open_profiles: string[];
  persisted: boolean;
}

/** Ma trận target đã ghép sẵn account ↔ recipe ở server, nên desktop không
 * phải tự đoán domain nào khớp model nào. */
export async function fetchTestTargets(key: string): Promise<TestTargetList> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/test-targets", { headers: headers(key) });
  return asJson(r);
}

/** Mở đúng tab headed mà request chat có target sẽ dùng lại. Bỏ trống `model`
 * để server tự chọn recipe đầu tiên phục vụ domain của account. */
export async function openTestTarget(
  key: string,
  model: string,
  accountId: number,
): Promise<{
  ok: true; profile: string; account: string; domain: string;
  url: string; model: string; recipe: string;
}> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/test-targets/open", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ model, account_id: accountId }),
  });
  return asJson(r);
}

/** Mở lại hội thoại của một session trong ĐÚNG profile đã chạy nó. Dán link vào
 * browser thường chỉ thấy trang đăng nhập — chỉ profile đó mới có phiên. */
export async function openSessionConversation(
  key: string,
  sessionId: string,
): Promise<{ ok: true; profile: string; url: string }> {
  const base = await apiBase();
  const r = await fetch(
    base + "/admin/sessions/" + encodeURIComponent(sessionId) + "/open",
    { method: "POST", headers: headers(key) },
  );
  return asJson(r);
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

// ------------------------------------------------------------- Flows (n8n-style)
// Module mới thay UI Recipe. Backend Recipe cũ vẫn chạy ngầm nhưng UI đã ẩn.

export interface FlowNode {
  id: string;
  type: string;
  position?: { x: number; y: number };
  params?: Record<string, unknown>;
  label?: string;
}

export interface FlowEdge {
  id?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  label?: string | null;
}

export interface FlowDoc {
  slug: string;
  kind?: string;
  flow_type?: string;
  type?: string;
  capability?: string;
  enabled?: boolean;
  keep_context?: boolean;
  model?: Record<string, unknown>;
  account?: Record<string, unknown>;
  meta?: Record<string, unknown>;
  nodes: FlowNode[];
  edges: FlowEdge[];
  [key: string]: unknown;
}

export interface FlowSummary {
  slug: string;
  flow_type: string;
  capability: string;
  enabled: boolean;
  display_name?: string | null;
  description?: string | null;
  node_count: number;
  edge_count: number;
  source_recipe?: string | null;
  parse_error?: string;
  errors?: string[];
}

export const FLOW_NODE_TYPES = [
  "start", "goto-url", "wait-ready", "new-chat", "assign-account",
  "check-trial-limit", "action-sequence", "select-model", "fill-input",
  "submit-enter", "submit-click", "wait-done-signal", "wait-media",
  "extract-text", "extract-media", "copy-button", "condition", "delay",
  "eval-js", "set-variable", "output",
] as const;

const FLOW_NODE_LABELS: Record<string, string> = {
  start: "Bắt đầu",
  "goto-url": "Mở URL",
  "wait-ready": "Chờ sẵn sàng",
  "new-chat": "Chat mới",
  "assign-account": "Chọn account",
  "check-trial-limit": "Giới hạn dùng thử",
  "action-sequence": "Chuỗi thao tác",
  "select-model": "Chọn model",
  "fill-input": "Nhập prompt",
  "submit-enter": "Gửi (Enter)",
  "submit-click": "Gửi (bấm nút)",
  "wait-done-signal": "Chờ trả lời",
  "wait-media": "Chờ media",
  "extract-text": "Lấy text",
  "extract-media": "Lấy media",
  "copy-button": "Nút Copy",
  condition: "Rẽ nhánh",
  delay: "Chờ",
  "eval-js": "Chạy JS",
  "set-variable": "Đặt biến",
  output: "Kết quả",
};

export function flowNodeLabel(type: string): string {
  return FLOW_NODE_LABELS[type] ?? type;
}

export async function fetchFlows(key: string): Promise<FlowSummary[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/flows", { headers: headers(key) });
  return asJson(r);
}

export async function fetchFlow(key: string, slug: string): Promise<FlowDoc> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/flows/" + encodeURIComponent(slug), {
    headers: headers(key),
  });
  return asJson(r);
}

export async function saveFlow(
  key: string,
  slug: string,
  flow: FlowDoc,
): Promise<{ ok: true; slug: string; flow: FlowDoc }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/flows/" + encodeURIComponent(slug), {
    method: "PUT",
    headers: headers(key),
    body: JSON.stringify(flow),
  });
  return asJson(r);
}

export async function deleteFlow(key: string, slug: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/flows/" + encodeURIComponent(slug), {
    method: "DELETE",
    headers: headers(key),
  });
  await asJson(r);
}

export async function duplicateFlow(
  key: string,
  slug: string,
  newSlug: string,
): Promise<{ ok: true; slug: string; flow: FlowDoc }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/flows/" + encodeURIComponent(slug) + "/duplicate", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ slug: newSlug }),
  });
  return asJson(r);
}

export async function testFlow(
  key: string,
  slug: string,
  opts: { headed?: boolean; prompt?: string; n?: number } = {},
): Promise<TrialResult> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/flows/" + encodeURIComponent(slug) + "/test", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({
      headed: opts.headed ?? false,
      prompt: opts.prompt ?? null,
      n: opts.n ?? 1,
    }),
  });
  return asJson(r);
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

export async function renameRecipe(
  key: string,
  slug: string,
  newSlug: string,
): Promise<{ ok: true; slug: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug), {
    method: "PATCH",
    headers: headers(key),
    body: JSON.stringify({ slug: newSlug }),
  });
  return asJson(r);
}

/** Đúng khung recipe.yaml mà form thủ công (`ManualRecipePanel`) tự khai —
 * không qua analyzer AI, dùng khi site quá lạ hoặc AI đoán sai selector. */
export interface ManualRecipeSpec {
  slug: string;
  url: string;
  prompt: {
    input_selector: string;
    input_mode: "fill" | "type";
    submit: string; // "Enter" hoặc "click:<css selector>"
  };
  response: {
    last_message_selector: string;
    done_signal: {
      type: "stable_text" | "selector_appear" | "selector_disappear" | "copy_button";
      selector?: string;
      quiet_ms?: number;
      timeout_ms?: number;
      scope?: "after" | "inside" | "page";
      use_copy_result?: boolean;
      exclude?: string;
      fallback_quiet_ms?: number;
    };
  };
  models: { id: string; action?: string; value?: string }[];
  new_chat?: { url?: string; selector?: string } | null;
  timing?: { ready_delay_ms?: number; input_delay_ms?: number; ready_timeout_ms?: number } | null;
  login?: {
    strategy?: "round_robin" | "fill_first";
    quota?: number;
    storage_state?: string;
    accounts?: { name: string; storage_state: string }[];
  } | null;
  keep_context: boolean;
  anon_trial_limit?: number | null;
}

export async function createRecipe(
  key: string,
  spec: ManualRecipeSpec,
): Promise<{ ok: true; slug: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(spec),
  });
  return asJson(r);
}

export interface DiscoveredRecipeModel {
  id: string;
  label: string;
  action: string;
  value?: string;
}

/** Phân tích URL bằng AI và trả về recipe chưa lưu — dùng để auto-fill form. */
export async function analyzeRecipeDraft(
  key: string,
  url: string,
  opts: { headed?: boolean; profileId?: number | null } = {},
): Promise<{ status: string; recipe?: Record<string, unknown>; notes?: string; log?: string[]; hint?: string; slug?: string }> {
  const base = await apiBase();
  const body: Record<string, unknown> = { url, headed: !!opts.headed };
  if (opts.profileId != null) body.profile_id = opts.profileId;
  const r = await fetch(base + "/admin/recipes/analyze", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(body),
  });
  return asJson(r);
}

/** Mở URL và dò model control khi người dùng chủ động yêu cầu. */
export async function discoverRecipeModels(
  key: string,
  url: string,
  headed = false,
): Promise<{ models: DiscoveredRecipeModel[]; method?: "dom" | "agent" }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/discover-models", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ url, headed }),
  });
  return asJson(r);
}

/** recipe.yaml nguyên văn + bản đã parse. `data` là null khi file hỏng cú
 * pháp — lúc đó chỉ tab YAML sửa được, và `parse_error` nói hỏng ở đâu. */
export interface RecipeSource {
  slug: string;
  yaml: string;
  data: Record<string, unknown> | null;
  parse_error: string | null;
}

export async function fetchRecipeSource(key: string, slug: string): Promise<RecipeSource> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/source", {
    headers: headers(key),
  });
  return asJson(r);
}

/** Một bản sửa recipe đã có, theo đúng hai đường server nhận:
 * `yaml` = toàn văn file (giữ được mọi khóa), `patch` = mảnh do biểu mẫu dựng
 * (server deep-merge, `null` nghĩa là xóa khóa). Chỉ gửi MỘT trong hai. */
export type RecipeEdit = { yaml: string } | { patch: Record<string, unknown> };

export async function updateRecipe(
  key: string,
  slug: string,
  edit: RecipeEdit,
): Promise<{ ok: true; slug: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug), {
    method: "PUT",
    headers: headers(key),
    body: JSON.stringify(edit),
  });
  return asJson(r);
}

/** Bản sửa sau khi áp, chưa ghi đĩa. Là cầu nối duy nhất giữa tab biểu mẫu
 * và tab YAML của màn sửa — client không có bộ parse/serialize YAML. */
export async function previewRecipeEdit(
  key: string,
  slug: string,
  edit: RecipeEdit,
): Promise<{ slug: string; yaml: string; data: Record<string, unknown> }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/preview", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(edit),
  });
  return asJson(r);
}

/** Một bước trong báo cáo chạy thử. Khớp `chat2api/trial.py`. */
export interface TrialStep {
  label: string;
  selector: string;
  /** ok = khớp đúng 1 · warn = khớp nhiều, mơ hồ · fail = 0 khớp/sai cú pháp · skip = không khai báo */
  status: "ok" | "warn" | "fail" | "skip";
  matches: number | null;
  detail: string;
}

export interface TrialResult {
  ok: boolean;
  flow?: FlowKind;
  reply: string;
  steps?: TrialStep[];
  /** Thời gian của riêng lượt thử, không tính mở/đóng browser. */
  ms?: number;
  /** Số ảnh/video nhận được (flow image/video). */
  media?: number;
  error?: string;
}

/** Tuỳ chọn cho một lượt chạy thử. `flow` mặc định là `text` ở server. */
export interface TrialOptions {
  headed?: boolean;
  flow?: FlowKind;
  /** Prompt riêng; để trống thì server dùng mặc định theo flow. */
  testPrompt?: string;
}

function trialBody(opts: TrialOptions = {}) {
  return {
    headed: opts.headed ?? false,
    flow: opts.flow ?? "text",
    // Server đặt tên `test_prompt` chứ không phải `prompt` — `prompt` đã là
    // khối cấu hình ô nhập của chính recipe.
    test_prompt: opts.testPrompt || null,
  };
}

/** Chạy thử bản đang sửa mà chưa ghi đè recipe đang chạy. */
export async function testRecipeEdit(
  key: string,
  slug: string,
  edit: RecipeEdit,
  opts: TrialOptions = {},
): Promise<TrialResult> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/test", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ ...edit, ...trialBody(opts) }),
  });
  return asJson(r);
}

/** Gửi thử một prompt qua recipe CHƯA lưu — cho biết selector nào sai trước
 * khi bấm tạo (form thủ công không có bước AI tự sửa). */
export async function testRecipe(
  key: string,
  spec: ManualRecipeSpec,
  opts: TrialOptions = {},
): Promise<TrialResult> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/test", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ ...spec, ...trialBody(opts) }),
  });
  return asJson(r);
}

/** `profileId` bắt buộc: login trong lúc tích hợp (nếu site cần) gắn thẳng
 * vào profile này thay vì rơi vào một profile tự sinh sau khi restart. */
export async function startIntegration(
  key: string,
  url: string,
  profileId: number,
  headed = false,
): Promise<{ job_id: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/integrate", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ url, headed, profile_id: profileId }),
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

export async function startRecord(
  key: string,
  url: string,
  profileId: number,
  slug?: string,
): Promise<{ job_id: string }> {
  const base = await apiBase();
  const body: Record<string, unknown> = { url, profile_id: profileId };
  if (slug) body.slug = slug;
  const r = await fetch(base + "/admin/record", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(body),
  });
  return asJson(r);
}

/** Mở đoạn ghi cho `flow`, hoặc đóng đoạn đang mở khi `flow` là null. */
export async function setRecordSegment(
  key: string,
  jobId: string,
  flow: FlowKind | null,
): Promise<JobStatus> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/record/" + encodeURIComponent(jobId) + "/segment", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(flow ? { action: "start", flow } : { action: "stop" }),
  });
  return asJson(r);
}

export async function finishRecord(key: string, jobId: string): Promise<JobStatus> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/record/" + encodeURIComponent(jobId) + "/finish", {
    method: "POST",
    headers: headers(key),
  });
  return asJson(r);
}

export async function fetchTrace(
  key: string,
  jobId: string,
  format: "json" | "md" = "json",
): Promise<string | any> {
  const base = await apiBase();
  // Spec: GET /admin/record/{id}/trace(.md/.json) — dùng extension path, fallback ?format alias
  const suffix = format === "md" ? ".md" : ".json";
  const urls = [
    base + "/admin/record/" + encodeURIComponent(jobId) + "/trace" + suffix,
    base + "/admin/record/" + encodeURIComponent(jobId) + "/trace?format=" + format,
  ];
  let lastErr: string | null = null;
  for (const url of urls) {
    const r = await fetch(url, { headers: headers(key) });
    if (r.ok) return format === "json" ? r.json() : r.text();
    const body = await r.json().catch(() => ({}));
    lastErr = body?.error?.message || r.statusText;
    if (r.status !== 404) break;
  }
  throw new Error(lastErr || "Trace not found");
}

export async function fetchTraces(key: string): Promise<{ traces: { name: string; size?: number; mtime?: number }[]; count: number }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/traces", { headers: headers(key) });
  return asJson(r);
}

export function traceDownloadUrl(jobId: string, format: "json" | "md" = "json"): string {
  // Dùng cho <a href> / nút Tải trace (desktop mở qua apiBase + auth header)
  return "/admin/record/" + encodeURIComponent(jobId) + "/trace." + format;
}

/** Phân tích lại recipe đã có bằng AI — giữ nguyên slug, ghi đè YAML. */
export async function reanalyzeRecipe(
  key: string,
  slug: string,
  opts: { url?: string; headed?: boolean; profile_id?: number | null } = {},
): Promise<{ job_id: string; slug: string; url: string }> {
  const base = await apiBase();
  const body: Record<string, unknown> = { headed: !!opts.headed };
  if (opts.url) body.url = opts.url;
  if (opts.profile_id != null) body.profile_id = opts.profile_id;
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug) + "/reanalyze", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(body),
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
 * hiện ra — phải đóng profile rồi mở lại mới thấy. */
export async function openProfile(
  key: string,
  ident: string | number,
  url = "",
  tabKey = "",
): Promise<{ profile: string; headless: boolean }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/profiles/" + encodeURIComponent(String(ident)) + "/open", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ url, tab_key: tabKey }),
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

export interface ComboMember {
  model_id: string;
  weight: number;
  priority: number;
}

export interface ComboInfo {
  id: number;
  slug: string;
  model_id: string;
  display_name: string;
  strategy: string;
  description: string;
  enabled: boolean;
  created_at: number;
  updated_at: number;
  members: ComboMember[];
}

export async function fetchCombos(key: string): Promise<ComboInfo[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/combos", { headers: headers(key) });
  return asJson(r);
}

export async function fetchCombo(key: string, slug: string): Promise<ComboInfo> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/combos/" + encodeURIComponent(slug), { headers: headers(key) });
  return asJson(r);
}

export async function createCombo(
  key: string,
  data: { slug: string; display_name?: string; strategy: string; description?: string; enabled?: boolean; members: ComboMember[] },
): Promise<ComboInfo> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/combos", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(data),
  });
  return asJson(r);
}

export async function updateCombo(
  key: string,
  slug: string,
  data: Partial<{ display_name: string; strategy: string; description: string; enabled: boolean; members: ComboMember[] }>,
): Promise<ComboInfo> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/combos/" + encodeURIComponent(slug), {
    method: "PUT",
    headers: headers(key),
    body: JSON.stringify(data),
  });
  return asJson(r);
}

export async function deleteCombo(key: string, slug: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/combos/" + encodeURIComponent(slug), {
    method: "DELETE",
    headers: headers(key),
  });
  await asJson(r);
}

export interface OpenAIModel {
  id: string;
  capability: string;
}

export interface OpenAIProviderInfo {
  slug: string;
  base_url: string;
  has_key: boolean;
  api_key_env: string;
  models: OpenAIModel[];
  stream: boolean;
  ready: boolean;
  type: string;
}

export async function fetchOpenAIProviders(key: string): Promise<OpenAIProviderInfo[]> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/openai", { headers: headers(key) });
  return asJson(r);
}

export async function fetchOpenAIProvider(key: string, slug: string): Promise<any> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/openai/" + encodeURIComponent(slug), { headers: headers(key) });
  return asJson(r);
}

export async function createOpenAIProvider(
  key: string,
  data: { slug: string; base_url: string; api_key?: string; api_key_env?: string; models: OpenAIModel[]; stream?: boolean },
): Promise<{ ok: true; slug: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/openai", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify(data),
  });
  return asJson(r);
}

export async function updateOpenAIProvider(
  key: string,
  slug: string,
  data: Partial<{ base_url: string; api_key: string; api_key_env: string; models: OpenAIModel[]; stream: boolean }>,
): Promise<{ ok: true; slug: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/openai/" + encodeURIComponent(slug), {
    method: "PUT",
    headers: headers(key),
    body: JSON.stringify(data),
  });
  return asJson(r);
}

export async function deleteOpenAIProvider(key: string, slug: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/openai/" + encodeURIComponent(slug), {
    method: "DELETE",
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

export async function deleteSessions(
  key: string,
  values: { ids?: string[]; all?: boolean },
): Promise<number> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/sessions", {
    method: "DELETE",
    headers: headers(key),
    body: JSON.stringify(values),
  });
  const data = await asJson(r);
  return data.deleted as number;
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
