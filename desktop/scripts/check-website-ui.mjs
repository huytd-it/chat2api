// Read-only smoke/visual checks against the actual app and backend.
// Never sends prompts, opens account browsers, creates images or deletes data.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";

const base = process.env.UI_BASE_URL || "http://127.0.0.1:5199";
const api = process.env.UI_API_URL || "http://127.0.0.1:8877";
const key = process.env.CHAT2API_TEST_KEY;
if (!key) throw new Error("Set CHAT2API_TEST_KEY for the local test backend");
const output = process.env.UI_SCREENSHOT_DIR || path.join(process.env.LOCALAPPDATA, "Temp", "opencode", "website-ui");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHAT2API_BROWSER_EXECUTABLE });
const errors = [];
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(({ api, key }) => {
  localStorage.setItem("c2a_key", key);
  localStorage.setItem("c2a_api_base", api);
}, { api, key });
const page = await context.newPage();
page.on("pageerror", (error) => errors.push(error.message));
const scopes = [];
page.on("request", (request) => {
  const url = new URL(request.url());
  if (url.pathname === "/admin/sessions") scopes.push(url.searchParams.get("site"));
  assert.ok(request.method() === "GET" || request.method() === "OPTIONS", "Smoke test must be read-only");
});

async function noOverflow() {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Page overflows horizontally");
}
async function capture(name) {
  await noOverflow();
  await page.screenshot({ path: path.join(output, name + ".png"), fullPage: false, animations: "disabled" });
}
try {
  await page.goto(base);
  await page.getByRole("heading", { name: "Web chats", exact: true, level: 2 }).waitFor();
  await page.locator('main a[href="/websites/qwen"]').waitFor();
  await capture("directory-desktop");

  await Promise.all([
    page.waitForResponse((r) => r.url().includes("/admin/sessions?") && r.url().includes("site=qwen")),
    page.locator('main a[href="/websites/qwen"]').click(),
  ]);
  await page.getByRole("heading", { name: "Qwen", exact: true }).waitFor();
  await page.getByRole("textbox", { name: "Tin nhắn mới" }).waitFor();
  const modelValues = await page.locator(".workspace-heading select").nth(1).locator("option").evaluateAll((items) => items.map((item) => item.value));
  assert.ok(modelValues.length && modelValues.every((id) => id.startsWith("qwen-web/") || id.startsWith("chat/")));
  assert.ok(!modelValues.some((id) => id.endsWith("/image")));
  await capture("qwen-desktop");

  await page.getByRole("button", { name: "Tạo ảnh", exact: true }).click();
  await page.getByRole("heading", { name: "Tạo ảnh với Qwen" }).waitFor();
  assert.ok(await page.getByRole("button", { name: "Tạo ảnh", exact: true }).last().isDisabled());
  await page.getByRole("button", { name: "Hội thoại", exact: true }).click();

  await page.goto(base + "/websites/kimi");
  await page.getByRole("heading", { name: "Kimi", exact: true }).waitFor();
  assert.equal(await page.locator(".workspace-heading").getByRole("button", { name: "Chọn project", exact: true }).count(), 0);
  assert.equal(await page.locator(".workspace-heading").getByRole("button", { name: "Tạo ảnh", exact: true }).count(), 0);

  await page.goto(base + "/websites/minimax");
  await page.getByRole("heading", { name: "MiniMax Agent chưa kết nối automation" }).waitFor();
  assert.equal(await page.getByRole("textbox", { name: "Tin nhắn mới" }).count(), 0);
  await capture("minimax-desktop");

  await page.goto(base + "/websites/qwen");
  await page.getByRole("textbox", { name: "Tin nhắn mới" }).waitFor();
  await page.getByRole("button", { name: "Đổi giao diện sáng/tối" }).click();
  await page.getByRole("menuitem", { name: "Tối", exact: true }).click();
  await capture("qwen-dark-desktop");

  await page.setViewportSize({ width: 390, height: 844 });
  // Reload to initialize the narrow workspace with drawers closed.
  await page.reload();
  await page.getByRole("textbox", { name: "Tin nhắn mới" }).waitFor();
  await capture("qwen-mobile");
  const composer = await page.getByRole("textbox", { name: "Tin nhắn mới" }).boundingBox();
  assert.ok(composer && composer.y >= 0 && composer.y + composer.height <= 844, "Composer is not visible");

  assert.ok(scopes.includes("qwen") && scopes.includes("kimi") && scopes.includes("minimax"));
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ ok: true, screenshots: output, checked: ["directory", "scoped history", "scoped models", "image studio", "capability controls", "unconfigured module", "dark theme", "mobile composer"], errors }, null, 2));
} finally { await browser.close(); }
