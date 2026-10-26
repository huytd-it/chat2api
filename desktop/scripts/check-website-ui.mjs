// Read-only checks: websites configure automation, /sessions owns all conversations.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { chromium } from "playwright-core";

const base = process.env.UI_BASE_URL || "http://127.0.0.1:5199";
const api = process.env.UI_API_URL || "http://127.0.0.1:8879";
const key = process.env.CHAT2API_TEST_KEY;
if (!key) throw new Error("Set CHAT2API_TEST_KEY");
const out = process.env.LOCALAPPDATA + "/Temp/opencode/shared-sessions-ui";
await mkdir(out,{recursive:true});
const browser = await chromium.launch({headless:true,executablePath:process.env.CHAT2API_BROWSER_EXECUTABLE});
const context = await browser.newContext({viewport:{width:1440,height:1000}});
await context.addInitScript(({api,key})=>{localStorage.setItem("c2a_api_base",api);localStorage.setItem("c2a_key",key);},{api,key});
const page = await context.newPage();
const errors = [], scopedRequests = [], mutations = [];
page.on("pageerror",error=>errors.push(error.message));
page.on("request",request=>{
  if (!request.url().startsWith(api)) return;
  if (!["GET","OPTIONS"].includes(request.method())) mutations.push(request.url());
  const url = new URL(request.url());
  if (url.pathname==="/admin/sessions") scopedRequests.push(url.searchParams.get("site"));
});
async function capture(name) {
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),"Horizontal overflow");
  await page.screenshot({path:out+"/"+name+".png",animations:"disabled"});
}
try {
  await page.goto(base+"/websites/qwen");
  await page.getByRole("heading",{name:"Cấu hình Qwen",exact:true}).waitFor();
  await page.locator("#recipe-row-qwen-web > button").waitFor();
  assert.equal(await page.getByRole("textbox",{name:"Tin nhắn mới"}).count(),0);
  assert.equal(scopedRequests.length,0,"Config page must not fetch conversation history");
  await capture("website-config-desktop");
  await page.getByRole("link",{name:"Chat với Qwen",exact:true}).click();
  await page.getByRole("textbox",{name:"Tin nhắn mới"}).waitFor();
  await page.waitForFunction(()=>document.querySelectorAll('.workspace-heading select')[1]?.value.startsWith('qwen-web/'));
  assert.ok(page.url().includes("/sessions?model="));
  assert.equal(await page.locator('.workspace-heading select').nth(1).locator('option[value="chatgpt-web/default"]').count(),1,"All websites share one model picker");
  await capture("sessions-desktop");
  await page.getByRole("button",{name:"Tạo ảnh",exact:true}).click();
  await page.getByRole("combobox",{name:"Model tạo ảnh",exact:true}).waitFor();
  assert.ok(await page.getByRole("button",{name:"Tạo ảnh",exact:true}).last().isDisabled());
  await capture("images-shared");
  await page.getByRole("button",{name:"Hội thoại",exact:true}).click();
  await page.getByRole("button",{name:"Đổi giao diện sáng/tối"}).click();
  await page.getByRole("menuitem",{name:"Tối",exact:true}).click();
  await capture("sessions-dark");
  await page.setViewportSize({width:390,height:844});
  await page.reload();
  await page.getByRole("textbox",{name:"Tin nhắn mới"}).waitFor();
  await capture("sessions-mobile");
  const box = await page.getByRole("textbox",{name:"Tin nhắn mới"}).boundingBox();
  assert.ok(box && box.y>=0 && box.y+box.height<=844,"Shared composer must remain visible");
  await page.goto(base+"/websites/minimax");
  await page.getByRole("heading",{name:"Cấu hình MiniMax Agent",exact:true}).waitFor();
  assert.equal(await page.getByRole("textbox",{name:"Tin nhắn mới"}).count(),0);
  await capture("website-config-mobile");
  assert.ok(scopedRequests.length && scopedRequests.every(scope=>scope===null));
  assert.deepEqual(errors,[]);
  assert.deepEqual(mutations,[]);
  console.log(JSON.stringify({ok:true,checks:["config-only website pages","shared history and model picker","image tool preserved in sessions","desktop/dark/mobile","visible narrow composer","no mutations"],screenshots:out}));
} finally { await context.close(); await browser.close(); }
