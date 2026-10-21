// Run ONLY against an isolated temporary-data backend: this registers a test domain.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright-core";

if (process.env.UI_ALLOW_TEST_DOMAIN !== "1") throw new Error("Use an isolated backend and set UI_ALLOW_TEST_DOMAIN=1");
const api = process.env.UI_API_URL || "http://127.0.0.1:8879";
const base = process.env.UI_BASE_URL || "http://127.0.0.1:5199";
const key = process.env.CHAT2API_TEST_KEY;
if (!key) throw new Error("Set CHAT2API_TEST_KEY");
const output = process.env.LOCALAPPDATA + "/Temp/opencode/launcher-ui";
await mkdir(output, {recursive:true});
const browser = await chromium.launch({headless:true,executablePath:process.env.CHAT2API_BROWSER_EXECUTABLE});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
await context.addInitScript(({api,key}) => {localStorage.setItem("c2a_api_base",api);localStorage.setItem("c2a_key",key);}, {api,key});
const page = await context.newPage();
const errors = [];
const unexpectedMutations = [];
page.on("pageerror", e => errors.push(e.message));
page.on("request", request => {
  if (!request.url().startsWith(api) || ["GET","OPTIONS"].includes(request.method())) return;
  if (!request.url().endsWith("/admin/websites") && !request.url().endsWith("/agent-brief")) unexpectedMutations.push(request.url());
});
async function capture(name) {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal overflow");
  await page.screenshot({path:output+"/"+name+".png",animations:"disabled"});
}
try {
  await page.goto(base);
  await page.getByRole("heading",{name:"Web chats",exact:true,level:2}).waitFor();
  await page.locator('main a[href="/websites/qwen"]').waitFor();
  assert.equal(await page.locator('a[href="/websites/qwen"]').count(),1,"Website must be in icon launcher only, not repeated in sidebar");
  await capture("launcher-desktop");
  await page.getByRole("button",{name:"Đổi giao diện sáng/tối"}).click();
  await page.getByRole("menuitem",{name:"Tối",exact:true}).click();
  await capture("launcher-dark");
  await page.setViewportSize({width:390,height:844});
  await capture("launcher-mobile");
  await page.getByRole("button",{name:"Thêm web chat",exact:true}).click();
  await page.getByRole("textbox",{name:"Domain website",exact:true}).fill("ui-launcher-test.example");
  await page.getByRole("button",{name:"Thêm domain",exact:true}).click();
  await page.getByRole("heading",{name:"Tạo automation bằng agent CLI",exact:true}).waitFor();
  await page.getByRole("textbox",{name:"Bạn muốn automation làm gì?"}).fill("Chọn model và upload file");
  await page.getByRole("button",{name:"Copy yêu cầu cho agent",exact:true}).click();
  await page.getByText("Xem nội dung gửi agent",{exact:true}).waitFor();
  await page.getByText("Xem nội dung gửi agent",{exact:true}).click();
  assert.ok((await page.locator("main").last().innerText()).includes("Chọn model và upload file"));
  await capture("agent-handoff-mobile");
  await page.goto(base);
  await page.getByText("ui-launcher-test.example",{exact:true}).first().waitFor();
  await page.getByRole("textbox",{name:"Tìm website"}).fill("ui-launcher-test");
  const link = page.locator('main a[href^="/websites/"]').first();
  await link.click();
  await page.getByRole("link",{name:"Tạo automation bằng agent CLI",exact:true}).waitFor();
  assert.equal(await page.getByRole("textbox",{name:"Tin nhắn mới"}).count(),0,"Registering a domain must not advertise a runnable model");
  assert.deepEqual(errors,[]);
  assert.deepEqual(unexpectedMutations,[]);
  console.log(JSON.stringify({ok:true,checked:["icon launcher","no per-domain sidebar","desktop/dark/mobile","domain registration","CLI agent brief","domain survives reload","no fake composer","no provider submissions"],screenshots:output}));
} finally { await browser.close(); }
