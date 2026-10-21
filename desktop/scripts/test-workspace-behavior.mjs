// Behavioral regression checks using a fully intercepted API, never an upstream.
import assert from "node:assert/strict";
import { chromium } from "playwright-core";

const browser = await chromium.launch({ headless: true, executablePath: process.env.CHAT2API_BROWSER_EXECUTABLE });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const origin = "http://workspace-test.invalid";
const models = ["qwen-web/qwen3.7-plus", "qwen-web/qwen3.8-max"];
const modelData = models.map((id) => ({ id, capability: "chat", ready: true }));
const now = Date.now();
const message = (role, content, id) => ({ id, seq: id, role, content, content_markdown: null, content_html: null, reasoning: null, error: null, artifacts: [], attachments: [], request: null, created_at: now, char_count: content.length });
const row = (id, title, model, automation = null) => ({ id, title, model_public_id: model, recipe_slug: "qwen-web", kind: "chat", account_id: null, account_label: null, account_host: null, profile_name: null, profile_id: null, site_conversation_url: null, pinned: 0, archived: 0, message_count: 1, error_count: 0, total_chars: 1, first_prompt: title, created_at: now, updated_at: now, tags: [], messages: [message("user", title, 0)], automation });
const sessions = new Map([["legacy-fixture", row("legacy-fixture", "Legacy fixture", models[0])]]);
const calls = [];
let rejectNext = false;
let healthSeen = false;
let targetBeforeHealth = false;
const pageErrors = [];
await context.addInitScript((origin) => { localStorage.setItem("c2a_api_base", origin); localStorage.setItem("c2a_key", "fixture-key"); }, origin);
await context.route(origin + "/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*", "Access-Control-Expose-Headers": "X-Chat2api-Session-Id" };
  const json = (body, status = 200) => route.fulfill({ status, headers: { ...cors, "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
  if (url.pathname === "/health") { healthSeen = true; return json({ contexts: 0, engine: "fixture", models: 2 }); }
  if (url.pathname === "/admin/websites") return json({ websites: [{ id: "qwen", slug: "qwen-web", title: "Qwen", url: "https://chat.qwen.ai/", hosts: ["chat.qwen.ai"], operations: ["chat", "projects", "thinking"], history_slugs: ["qwen-web"], models: modelData, runtime: "legacy", unhealthy: false }] });
  if (url.pathname === "/v1/models") return json({ data: modelData });
  if (url.pathname === "/admin/automations") return json([
    {slug:"qwen-web",type:"BrowserRecipe",url:"https://chat.qwen.ai",domain:"chat.qwen.ai",models:["qwen3.7-plus"],unhealthy:false,loaded:true},
    {slug:"chatgpt-web",type:"BrowserRecipe",url:"https://chatgpt.com",domain:"chatgpt.com",models:["default"],unhealthy:false,loaded:true},
  ]);
  if (url.pathname === "/admin/profiles") return json({profiles:[],mode:"profile",profiles_dir:"fixture",max_profiles:6,persisted:true});
  if (url.pathname === "/admin/openai") return json([]);
  if (url.pathname === "/admin/account-cooldowns") return json({cooldowns:[]});
  if (url.pathname === "/admin/automations/qwen-web/source") return json({slug:"qwen-web",yaml:"slug: qwen-web\nurl: https://chat.qwen.ai/",data:{slug:"qwen-web",url:"https://chat.qwen.ai/",models:[{id:"qwen3.7-plus"}]},parse_error:null});
  if (url.pathname === "/admin/accounts") return json({ domains: [] });
  if (url.pathname === "/admin/overview") return json({ request_routes: [], session_distribution: [], models: 2 });
  if (url.pathname === "/admin/automation-targets") { if (!healthSeen) targetBeforeHealth = true; return json({ targets: [], profile_mode: "profile", max_profiles: 6, max_tabs: 8, open_profiles: [], persisted: true }); }
  if (url.pathname === "/admin/sessions") return json({ sessions: [...sessions.values()], persisted: true });
  if (url.pathname.startsWith("/admin/sessions/")) {
    const detail = sessions.get(url.pathname.split("/").at(-1));
    return detail ? json(detail) : json({ error: { message: "No fixture" } }, 404);
  }
  if (url.pathname === "/v1/chat/completions") {
    const payload = request.postDataJSON();
    calls.push(payload);
    if (rejectNext) { rejectNext = false; return json({ error: { code: "operation_unresolved", message: "FIXTURE_UNRESOLVED" } }, 409); }
    const prior = sessions.get(payload.session_id);
    const successes = (prior?.automation?.successes || 0) + 1;
    const detail = row(payload.session_id, payload.messages[0].content, payload.model, { account_id: null, project_id: null, generation: 0, successes, busy_operation: null });
    detail.messages.push(message("assistant", `MOCK RESULT ${calls.length}`, 1));
    sessions.set(payload.session_id, detail);
    return route.fulfill({ status: 200, headers: { ...cors, "Content-Type": "text/event-stream", "X-Chat2api-Session-Id": payload.session_id }, body: `data: ${JSON.stringify({ choices: [{ delta: { content: `MOCK RESULT ${calls.length}` } }] })}\n\ndata: [DONE]\n\n` });
  }
  return json({ error: { message: `Unimplemented fixture: ${url.pathname}` } }, 404);
});

const page = await context.newPage();
page.on("pageerror", (error) => pageErrors.push(error.message));
async function send(text, result) {
  await page.getByRole("textbox", { name: "Tin nhắn mới" }).fill(text);
  await page.getByRole("button", { name: "Gửi", exact: true }).click();
  await page.getByText(result, { exact: true }).first().waitFor();
}
try {
  const initialCatalog = page.waitForResponse((response) => response.url().endsWith("/admin/websites"));
  await page.goto(process.env.UI_BASE_URL || "http://127.0.0.1:5199");
  await initialCatalog;
  await page.getByRole("heading", {name:"Web chats",exact:true,level:2}).waitFor();
  assert.equal(targetBeforeHealth, false, "Directory must wait for sidecar health before loading accounts");
  await page.goto((process.env.UI_BASE_URL || "http://127.0.0.1:5199") + "/websites/qwen/settings");
  await page.getByRole("heading", {name:"Cấu hình Qwen",exact:true}).waitFor();
  await page.locator("#recipe-row-qwen-web > button").click();
  assert.equal(await page.locator("#recipe-row-chatgpt-web").count(),0,"Another website's automation must not appear in settings");
  for (const name of ["Phân tích lại","Ghi thao tác","Chỉnh sửa","Đổi tên","Đóng browser","Xóa"]) {
    assert.equal(await page.getByRole("button",{name,exact:true}).count(),1,`Missing migrated control: ${name}`);
  }
  await page.getByRole("button",{name:"Chỉnh sửa",exact:true}).click();
  await page.getByRole("tab",{name:"YAML",exact:true}).waitFor();
  await page.keyboard.press("Escape");
  await page.goto((process.env.UI_BASE_URL || "http://127.0.0.1:5199") + "/api-providers");
  await page.getByRole("button",{name:"Thêm provider đầu tiên",exact:true}).waitFor();
  assert.equal(await page.locator("#recipe-row-qwen-web").count(),0,"Direct API page must not duplicate website management");
  await page.goto((process.env.UI_BASE_URL || "http://127.0.0.1:5199") + "/websites/qwen");
  await page.getByText("Legacy fixture", { exact: true }).first().click();
  await page.getByRole("button", { name: "Mở đúng hội thoại website" }).count();
  await send("chunk-one", "MOCK RESULT 1");
  assert.notEqual(calls[0].session_id, "legacy-fixture", "Legacy recordings must not become durable conversations implicitly");
  assert.deepEqual(calls[0].messages, [{ role: "user", content: "chunk-one" }]);
  await send("chunk-two", "MOCK RESULT 2");
  assert.equal(calls[1].session_id, calls[0].session_id);
  assert.notEqual(calls[1].request_id, calls[0].request_id);
  assert.deepEqual(calls[1].messages, [{ role: "user", content: "chunk-two" }]);
  await page.locator(".workspace-heading select").nth(1).selectOption(models[1]);
  await send("new-model", "MOCK RESULT 3");
  assert.notEqual(calls[2].session_id, calls[1].session_id);
  assert.equal(calls[2].model, models[1]);
  rejectNext = true;
  await send("uncertain-turn", "FIXTURE_UNRESOLVED");
  assert.equal(calls.length, 4, "Unresolved operations must not trigger automatic resend");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await page.getByRole("button", { name: "Ẩn hoặc hiện ngữ cảnh" }).click();
  const dialog = page.getByRole("dialog", { name: "Ngữ cảnh & chẩn đoán", exact: true });
  await dialog.waitFor();
  await page.keyboard.press("Tab");
  assert.ok(await dialog.evaluate((element) => element.contains(document.activeElement)), "Drawer must contain keyboard focus");
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  assert.deepEqual(pageErrors, []);
  console.log("PASS: legacy isolation, durable continuation, one new message, stable context, model change creates session, unresolved does not auto-resend, narrow drawer focus trap and Escape. All provider responses were intercepted fixtures.");
} finally { await browser.close(); }
