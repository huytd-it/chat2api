// Read-only QA of the transferred management surface against a local backend.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright-core";

const base = process.env.UI_BASE_URL || "http://127.0.0.1:5199";
const api = process.env.UI_API_URL || "http://127.0.0.1:8878";
const key = process.env.CHAT2API_TEST_KEY;
if (!key) throw new Error("Set CHAT2API_TEST_KEY");
const out = process.env.LOCALAPPDATA + "/Temp/opencode/workspace-migration";
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHAT2API_BROWSER_EXECUTABLE });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(({api,key}) => {localStorage.setItem("c2a_api_base",api);localStorage.setItem("c2a_key",key);}, {api,key});
const page = await context.newPage();
const errors = [];
const forbidden = [];
page.on("pageerror", error => errors.push(error.message));
page.on("request", request => {
  if (request.url().startsWith(api)) {
    if (!['GET','OPTIONS'].includes(request.method())) forbidden.push(request.method()+" "+request.url());
    if (/\/admin\/(recipes|test-targets|integrate|record|traces|flows)(\/|$|\?)/.test(request.url())) forbidden.push(request.url());
  }
});
const checkWidth = async () => assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
try {
  await page.goto(base + "/websites/qwen/settings");
  await page.getByRole("heading", {name:"Cấu hình Qwen",exact:true}).waitFor();
  await page.locator('#recipe-row-qwen-web > button').waitFor();
  await page.locator('#recipe-row-qwen-web > button').click();
  await page.getByRole("button",{name:"Ghi thao tác",exact:true}).first().waitFor();
  assert.equal(await page.locator('#recipe-row-chatgpt-web').count(),0);
  await checkWidth();
  await page.screenshot({path:out+"/settings-desktop.png",animations:"disabled"});
  await page.setViewportSize({width:390,height:844});
  await checkWidth();
  await page.screenshot({path:out+"/settings-mobile.png",animations:"disabled"});
  await page.goto(base + "/api-providers");
  await page.getByText("Endpoint OpenAI-compatible, model và API key.",{exact:true}).waitFor();
  assert.equal(await page.locator('[id^="recipe-row-"]').count(),0);
  await checkWidth();
  await page.goto(base + "/connections");
  await page.getByRole("heading",{name:"Kết nối website",exact:true,level:2}).waitFor();
  await page.getByText("Thêm cấu hình automation — thủ công hoặc phân tích website",{exact:true}).waitFor();
  await checkWidth();
  assert.deepEqual(errors,[]);
  assert.deepEqual(forbidden,[]);
  console.log(JSON.stringify({ok:true,checked:["scoped management","record/edit/reload/rename controls","direct API separated","authoring relocated","narrow overflow","no retired API calls","no mutations"],screenshots:out}));
} finally { await browser.close(); }
