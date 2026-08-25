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

export interface RecipeInfo {
  slug: string;
  models: string[];
  unhealthy: boolean;
}

export interface JobStatus {
  status: string;
  log: string[];
  can_complete_login?: boolean;
}

const FALLBACK_BASE_URL = "http://127.0.0.1:8100";

let cachedBase: string | null = null;

/** Resolves the chat2api server URL. Asks the Tauri host for the sidecar's
 * port; falls back to the default dev port when running outside Tauri
 * (e.g. `npm run dev` in a plain browser against a manually-started server). */
export async function apiBase(): Promise<string> {
  if (cachedBase) return cachedBase;
  try {
    cachedBase = await invoke<string>("api_base_url");
  } catch {
    cachedBase = FALLBACK_BASE_URL;
  }
  return cachedBase;
}

function headers(key: string): HeadersInit {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (key) h["Authorization"] = "Bearer " + key;
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

/** Streams an SSE chat completion, invoking onDelta for each content chunk. */
export async function streamChat(
  key: string,
  model: string,
  prompt: string,
  onDelta: (text: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/v1/chat/completions", {
    method: "POST",
    headers: headers(key),
    signal,
    body: JSON.stringify({
      model,
      stream: true,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!r.ok || !r.body) {
    const data = await r.json().catch(() => ({}));
    throw new Error(data?.error?.message || r.statusText);
  }
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
      const delta = JSON.parse(payload).choices?.[0]?.delta?.content ?? "";
      if (delta) onDelta(delta);
    }
  }
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

export async function deleteRecipe(key: string, slug: string): Promise<void> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/recipes/" + encodeURIComponent(slug), {
    method: "DELETE",
    headers: headers(key),
  });
  await asJson(r);
}

export async function startIntegration(key: string, url: string): Promise<{ job_id: string }> {
  const base = await apiBase();
  const r = await fetch(base + "/admin/integrate", {
    method: "POST",
    headers: headers(key),
    body: JSON.stringify({ url }),
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
