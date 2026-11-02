// Browser profiles UI regression checks using a fully intercepted API.
// Never opens a real profile, never reaches a website.
//   UI_BASE_URL=http://127.0.0.1:5199 CHAT2API_BROWSER_EXECUTABLE=<chromium> node desktop/scripts/test-profiles-ui.mjs
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { chromium } from "playwright-core";

const base = process.env.UI_BASE_URL ?? "http://127.0.0.1:5199";
const shots = process.env.UI_SHOT_DIR;
if (shots) mkdirSync(shots, { recursive: true });
const origin = "http://profiles-test.invalid";

const account = (id, host, label) => ({ id, host, label, status: "ok", disabled: 0 });
const makeProfile = (id, name, extra = {}) => ({
  id, name, user_data_dir: `C:/fixture/profiles/${name}`, headless: 1, max_tabs: 4, scrapling_mode: "dynamic",
  is_default: 0, domains: 0, locked: false, open: false, tabs: 0, notes: "", last_used_at: null, accounts: [], ...extra,
});
const initialProfiles = () => [
  makeProfile(1, "main", { is_default: 1, open: true, tabs: 2, domains: 2, notes: "Tài khoản chính", last_used_at: Date.now() - 300000, accounts: [account(11, "chatgpt.com", "acc1"), account(12, "chat.qwen.ai", "acc2")] }),
  makeProfile(2, "work", { domains: 1, accounts: [account(21, "chat.z.ai", "work")] }),
  makeProfile(3, "http-only", { scrapling_mode: "fetcher" }),
  makeProfile(4, "held", { locked: true }),
];

const browser = await chromium.launch({ headless: true, executablePath: process.env.CHAT2API_BROWSER_EXECUTABLE });

/** Mỗi kịch bản một context sạch và một kho fixture riêng. */
async function scenario(name, options, run) {
  const state = {
    profiles: options.profiles ?? initialProfiles(),
    google: options.google ?? {},
    failProfiles: options.failProfiles ?? false,
    calls: [],
    domains: options.domains ?? [
      { host: "chatgpt.com", accounts: 0, recipes: ["chatgpt-web"] },
      { host: "chat.qwen.ai", accounts: 0, recipes: ["qwen-web"] },
      { host: "chat.z.ai", accounts: 2, recipes: [] },
      { host: "minimax.io", accounts: 0, recipes: [] },
    ],
  };
  const context = await browser.newContext({ viewport: options.viewport ?? { width: 1440, height: 1000 }, colorScheme: options.dark ? "dark" : "light" });
  await context.addInitScript((o) => { localStorage.setItem("c2a_api_base", o); localStorage.setItem("c2a_key", "fixture-key"); }, origin);
  await context.route(origin + "/**", (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
    const json = (body, status = 200) => route.fulfill({ status, headers: { ...cors, "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (method === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
    const path = url.pathname;
    if (method !== "GET") state.calls.push({ method, path, body: request.postDataJSON?.() ?? null, search: url.search });
    if (path === "/health") return json({ contexts: 0, engine: "fixture", models: 0 });
    if (path === "/admin/profiles" && method === "GET") {
      if (state.failProfiles) return json({ error: { message: "FIXTURE_DOWN" } }, 500);
      return json({ profiles: state.profiles, mode: "profile", profiles_dir: "C:/fixture/profiles", max_profiles: 6, persisted: true });
    }
    if (path === "/admin/profiles" && method === "POST") {
      const body = request.postDataJSON();
      const created = makeProfile(100 + state.profiles.length, body.name, body);
      state.profiles.push(created);
      return json(created);
    }
    if (path === "/admin/account-cooldowns") return json({ cooldowns: options.cooldowns ?? [] });
    if (path === "/admin/domains") return json({ domains: state.domains });
    const domainOne = path.match(/^\/admin\/domains\/([^/]+)$/);
    if (domainOne && method === "DELETE") {
      const host = decodeURIComponent(domainOne[1]);
      if (host === "race.example") return json({ error: { message: "FIXTURE_IN_USE" } }, 409);
      state.domains = state.domains.filter((d) => d.host !== host);
      for (const p of state.profiles) p.accounts = p.accounts.filter((a) => a.host !== host);
      return json({ ok: true });
    }
    if (path.endsWith("/import")) return json(state.importResult);
    if (path === "/admin/automations") return json([]);
    const addAccount = path.match(/^\/admin\/profiles\/(\d+)\/accounts$/);
    if (addAccount && method === "POST") {
      const body = request.postDataJSON();
      const p = state.profiles.find((x) => x.id === Number(addAccount[1]));
      const added = account(1000 + state.calls.length, body.domain, body.label);
      p.accounts.push(added);
      return new Promise((resolve) => setTimeout(resolve, state.delay ?? 0)).then(() => json({ ok: true, account: added }));
    }
    const domainProfile = path.match(/^\/admin\/domains\/([^/]+)\/profiles\/(\d+)$/);
    if (domainProfile && method === "DELETE") {
      const host = decodeURIComponent(domainProfile[1]);
      if (host === "chat.z.ai") return json({ error: { message: "FIXTURE_BLOCKED" } }, 409);
      const p = state.profiles.find((x) => x.id === Number(domainProfile[2]));
      p.accounts = p.accounts.filter((a) => a.host !== host);
      return json({ ok: true });
    }
    const googleSites = path.match(/^\/admin\/profiles\/(\d+)\/google\/sites$/);
    if (googleSites) return json({ results: request.postDataJSON().targets.map((host) => ({ ok: true, host, url: `https://${host}`, status: "done", detail: "" })) });
    const google = path.match(/^\/admin\/profiles\/(\d+)\/google$/);
    if (google && method === "GET") {
      const entry = state.google[google[1]] ?? { identity: null, waiting: false };
      return json(typeof entry === "function" ? entry() : entry);
    }
    if (google && method === "DELETE") return json({ ok: true });
    const open = path.match(/^\/admin\/profiles\/(\d+)\/open$/);
    if (open) { const p = state.profiles.find((x) => x.id === Number(open[1])); p.open = true; p.tabs = 1; return json({ profile: p.name, headless: false }); }
    const detect = path.match(/^\/admin\/profiles\/(\d+)\/detect$/);
    if (detect) return json({ profile: "x", known: [], suggested: ["minimax.io"] });
    const close = path.match(/^\/admin\/profiles\/([^/]+)\/close$/);
    if (close) { const p = state.profiles.find((x) => x.name === close[1]); p.open = false; p.tabs = 0; return json({ ok: true }); }
    const clone = path.match(/^\/admin\/profiles\/(\d+)\/clone$/);
    if (clone) { const created = makeProfile(200 + state.profiles.length, request.postDataJSON().name); state.profiles.push(created); return json(created); }
    const accountPath = path.match(/^\/admin\/profiles\/(\d+)\/accounts\/(\d+)$/);
    if (accountPath && method === "DELETE") {
      const p = state.profiles.find((x) => x.id === Number(accountPath[1]));
      p.accounts = p.accounts.filter((a) => a.id !== Number(accountPath[2]));
      return json({ ok: true });
    }
    const one = path.match(/^\/admin\/profiles\/(\d+)$/);
    if (one && method === "DELETE") { state.profiles = state.profiles.filter((x) => x.id !== Number(one[1])); return json({ ok: true }); }
    if (one) { const p = state.profiles.find((x) => x.id === Number(one[1])); const body = request.postDataJSON(); Object.assign(p, body, "headless" in body ? { headless: body.headless ? 1 : 0 } : {}, body.is_default ? { is_default: 1 } : {}); return json(p); }
    return json({ data: [], websites: [], sessions: [], targets: [], persisted: true });
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (e) => { pageErrors.push(e.message); console.error(`[${name}] page error: ${e.stack ?? e.message}`); });
  await page.goto(`${base}/profiles`);
  try {
    await run(page, state);
    assert.deepEqual(pageErrors, [], `${name}: page errors`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    assert.equal(overflow, false, `${name}: horizontal overflow`);
    if (shots) await page.screenshot({ path: `${shots}/${name}.png` });
    console.log(`ok - ${name}`);
  } finally {
    await context.close();
  }
}

const profileTable = (page) => page.getByRole("table", { name: "Danh sách profile" });
const row = (page, name) => profileTable(page).getByRole("button", { name, exact: true });
const rowEl = (page, name) => profileTable(page).getByRole("row").filter({ has: page.getByRole("button", { name, exact: true }) });
const tick = (page, label) => page.getByRole("checkbox", { name: label, exact: true }).click();
const openTab = (page, name) => page.getByRole("tab", { name }).click();
const lastCall = (state, method, pattern) => state.calls.filter((c) => c.method === method && pattern.test(c.path)).at(-1);
const moreMenu = (page, name) => page.getByRole("button", { name: `Thao tác khác cho ${name}` }).click();

await scenario("list-and-selection", {}, async (page) => {
  await row(page, "main").waitFor();
  assert.equal(await row(page, "main").getAttribute("aria-current"), "true");
  await page.getByRole("heading", { name: "main", level: 3 }).waitFor();
  await page.getByText("Tài khoản chính").waitFor();
  await page.getByText(/dùng 5 phút trước/).waitFor();
  // Account đã gắn không được tự nhận là "đã đăng nhập".
  assert.equal(await page.getByText("đã đăng nhập", { exact: false }).count(), 0);
  await row(page, "work").click();
  await page.getByRole("heading", { name: "work", level: 3 }).waitFor();
  await page.locator("section[aria-label='Google của main']").waitFor({ state: "hidden", timeout: 3000 });
  await page.locator("section[aria-label='Google của work']").waitFor({ state: "visible", timeout: 3000 });
});

await scenario("fetcher-and-closed-hints", {}, async (page) => {
  await row(page, "http-only").click();
  assert.equal(await page.getByRole("button", { name: "Mở", exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole("button", { name: "Dò domain" }).isDisabled(), true);
  await page.getByText(/Fetcher chỉ gửi HTTP/).waitFor();
  await row(page, "work").click();
  assert.equal(await page.getByRole("button", { name: "Mở", exact: true }).isDisabled(), false);
  await page.getByText("Mở profile để đăng nhập và dò domain.").waitFor();
});

await scenario("open-detect-declare-close", {}, async (page, state) => {
  await row(page, "work").click();
  await page.getByRole("button", { name: "Mở", exact: true }).click();
  await page.getByRole("button", { name: "Đóng", exact: true }).waitFor();
  await page.getByRole("button", { name: "Dò domain" }).click();
  await page.getByText(/Có đăng nhập chưa khai báo/).waitFor();
  assert.ok(lastCall(state, "POST", /\/2\/detect$/));
  await page.getByRole("button", { name: "Đóng", exact: true }).click();
  await page.getByRole("button", { name: "Mở", exact: true }).waitFor();
  assert.ok(lastCall(state, "POST", /\/work\/close$/));
});

await scenario("create-validation-and-payload", {}, async (page, state) => {
  await page.getByRole("button", { name: "Profile mới" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Tên profile").fill("Bad Name");
  await dialog.getByRole("button", { name: "Tạo", exact: true }).click();
  await dialog.getByText(/chỉ gồm chữ thường/).waitFor();
  assert.equal(lastCall(state, "POST", /\/admin\/profiles$/), undefined);
  await dialog.getByLabel("Tên profile").fill("fresh");
  await dialog.getByRole("button", { name: "Tạo", exact: true }).click();
  await dialog.waitFor({ state: "hidden" });
  assert.deepEqual(lastCall(state, "POST", /\/admin\/profiles$/).body, { name: "fresh", scrapling_mode: "dynamic", max_tabs: 4, headless: true });
  await page.getByRole("heading", { name: "fresh", level: 3 }).waitFor();
});

await scenario("settings-payload", {}, async (page, state) => {
  await row(page, "work").click();
  await page.getByRole("button", { name: "Cài đặt" }).click();
  const sheet = page.getByRole("dialog");
  await sheet.getByLabel("Ghi chú").fill("ghi chú mới");
  await sheet.getByText("C:/fixture/profiles/work").waitFor();
  assert.equal(await sheet.getByLabel(/Gmail/).count(), 0);
  await sheet.getByRole("button", { name: "Đặt làm mặc định" }).click();
  await sheet.getByText("Đây là profile mặc định.").waitFor();
  await sheet.getByRole("button", { name: "Lưu" }).click();
  await sheet.waitFor({ state: "hidden" });
  const saved = state.calls.filter((c) => c.method !== "GET" && /\/admin\/profiles\/2$/.test(c.path));
  assert.deepEqual(saved[0].body, { is_default: true });
  assert.deepEqual(saved[1].body, { scrapling_mode: "dynamic", max_tabs: 4, headless: true, notes: "ghi chú mới" });
  await page.getByText("ghi chú mới").waitFor();
});

await scenario("clone-requires-closed-profile", {}, async (page, state) => {
  await moreMenu(page, "main");
  await page.getByRole("menuitem", { name: "Nhân bản" }).click();
  const dialog = page.getByRole("dialog");
  const submit = dialog.getByRole("button", { name: "Nhân bản", exact: true });
  assert.equal(await submit.isDisabled(), true);
  await dialog.getByRole("button", { name: "Đóng profile" }).click();
  await dialog.getByText(/Profile đang chạy/).waitFor({ state: "hidden" });
  await dialog.getByLabel("Tên bản sao").fill("main-b");
  await submit.click();
  await dialog.waitFor({ state: "hidden" });
  await page.getByRole("heading", { name: "main-b", level: 3 }).waitFor();
  assert.equal(lastCall(state, "POST", /\/1\/clone$/).body.name, "main-b");
  // Dialog do menu mở phải trả lại tương tác cho trang.
  assert.equal(await page.evaluate(() => document.body.style.pointerEvents), "");
});

await scenario("remove-account-needs-confirmation", {}, async (page, state) => {
  await page.getByRole("button", { name: /Gỡ chatgpt.com \/ acc1/ }).click();
  const confirm = page.getByRole("alertdialog");
  await confirm.getByRole("button", { name: "Hủy" }).click();
  await confirm.waitFor({ state: "hidden" });
  assert.equal(lastCall(state, "DELETE", /accounts/), undefined);
  await page.getByRole("button", { name: /Gỡ chatgpt.com \/ acc1/ }).click();
  await confirm.getByRole("button", { name: "Gỡ site" }).click();
  await page.getByRole("button", { name: /Gỡ chatgpt.com \/ acc1/ }).waitFor({ state: "hidden" });
  assert.ok(lastCall(state, "DELETE", /\/1\/accounts\/11$/));
});

for (const purge of [false, true]) {
  await scenario(`delete-purge-${purge}`, {}, async (page, state) => {
    await row(page, "work").click();
    await moreMenu(page, "work");
    await page.getByRole("menuitem", { name: "Xóa profile" }).click();
    const confirm = page.getByRole("alertdialog");
    if (purge) await confirm.getByRole("checkbox").click();
    await confirm.getByRole("button", { name: "Xóa profile" }).click();
    await row(page, "work").waitFor({ state: "hidden" });
    assert.equal(lastCall(state, "DELETE", /\/admin\/profiles\/2$/).search, `?purge=${purge}`);
    await page.getByRole("heading", { name: "main", level: 3 }).waitFor();
  });
}

await scenario("google-delete-needs-confirmation", {
  google: { 1: { identity: { profile_id: 1, email: "a@gmail.com", has_password: true, has_totp: false, recovery_email: "", auto_login: true, status: "signed_in", checked_at: Date.now() }, waiting: false } },
}, async (page, state) => {
  const google = page.locator("section[aria-label='Google của main']");
  await google.getByText("Đã đăng nhập").waitFor();
  await google.getByRole("button", { name: "Tài khoản" }).click();
  await google.getByRole("button", { name: "Xoá tài khoản Google" }).click();
  assert.equal(lastCall(state, "DELETE", /google$/), undefined);
  await page.getByRole("alertdialog").getByRole("button", { name: "Xoá tài khoản" }).click();
  await page.getByRole("alertdialog").waitFor({ state: "hidden" });
  assert.ok(lastCall(state, "DELETE", /\/1\/google$/));
});

await scenario("google-poll-survives-switching", {
  google: {
    2: (() => {
      let reads = 0;
      const identity = { profile_id: 2, email: "w@gmail.com", has_password: true, has_totp: false, recovery_email: "", auto_login: true, status: "verify_required", checked_at: Date.now() };
      return () => (++reads < 2 ? { identity, waiting: true } : { identity: { ...identity, status: "signed_in" }, waiting: false });
    })(),
  },
}, async (page) => {
  await rowEl(page, "work").getByText("Đang chờ xác minh").waitFor();
  await row(page, "main").click();
  // Cả việc đổi profile lẫn đổi tab đều không được làm mất vòng poll.
  await openTab(page, "Domain");
  await page.getByText("work: đã xác minh Google xong").waitFor({ timeout: 8000 });
  await openTab(page, "Profiles");
  assert.equal(await rowEl(page, "work").getByText("Đang chờ xác minh").count(), 0);
});

await scenario("bulk-attach-one-domain-to-many-profiles", {}, async (page, state) => {
  await row(page, "main").waitFor();
  await tick(page, "Chọn profile main");
  await tick(page, "Chọn profile work");
  await page.getByRole("button", { name: "Gắn domain" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox", { name: "chat.z.ai" }).click();
  await dialog.getByLabel(/Domain khác/).fill("https://new.example.com/path");
  // work đã gắn chat.z.ai nên chỉ còn 3 trên 4 cặp.
  await dialog.getByText(/Sẽ xử lý 3 cặp.*bỏ qua 1 \(đã gắn\)/).waitFor();
  await dialog.getByRole("button", { name: "Gắn 3" }).click();
  await dialog.getByText("Thành công 3/3").waitFor();
  const adds = state.calls.filter((c) => c.method === "POST" && /\/accounts$/.test(c.path)).map((c) => `${c.path.split("/")[3]}:${c.body.domain}:${c.body.label}`);
  assert.deepEqual(adds, ["1:chat.z.ai:main", "1:new.example.com:main", "2:new.example.com:main"]);
  await dialog.getByRole("button", { name: "Xong" }).click();
  await dialog.waitFor({ state: "hidden" });
  // Selection giữ lại để làm tiếp thao tác khác trên cùng nhóm.
  await page.getByText("2 profile đã chọn", { exact: false }).waitFor();
});

await scenario("bulk-detach-domains-partial-failure", {}, async (page, state) => {
  await openTab(page, "Domain");
  await tick(page, "Chọn domain chatgpt.com");
  await tick(page, "Chọn domain chat.z.ai");
  await page.getByRole("button", { name: "Gỡ profile" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox", { name: "main" }).click();
  await dialog.getByRole("checkbox", { name: "work" }).click();
  await dialog.getByText(/Sẽ xử lý 2 cặp.*bỏ qua 2 \(chưa gắn\)/).waitFor();
  assert.equal(state.calls.some((c) => c.method === "DELETE"), false);
  await dialog.getByRole("button", { name: "Gỡ 2" }).click();
  await dialog.getByText("Thành công 1/2").waitFor();
  await dialog.getByText("FIXTURE_BLOCKED").waitFor();
  await dialog.getByRole("button", { name: "Xong" }).click();
  const rows = page.getByRole("table", { name: "Danh sách domain" }).getByRole("row");
  await rows.filter({ hasText: "chatgpt.com" }).getByText("Chưa gắn").waitFor();
  await rows.filter({ hasText: "chat.z.ai" }).getByText("work").waitFor();
});

await scenario("bulk-google-skips-fetcher", {}, async (page, state) => {
  await openTab(page, "Domain");
  await tick(page, "Chọn domain minimax.io");
  await page.getByRole("button", { name: "Đăng nhập Google" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox", { name: "main" }).click();
  await dialog.getByRole("checkbox", { name: "http-only" }).click();
  await dialog.getByText(/Sẽ xử lý 1 cặp.*Fetcher/).waitFor();
  await dialog.getByText(/Chưa ghi nhận đăng nhập Google/).waitFor();
  await dialog.getByRole("button", { name: "Đăng nhập 1" }).click();
  await dialog.getByText("Thành công 1/1").waitFor();
  const calls = state.calls.filter((c) => /google\/sites$/.test(c.path));
  assert.equal(calls.length, 1);
  assert.match(calls[0].path, /\/1\/google\/sites$/);
  assert.deepEqual(calls[0].body.targets, ["minimax.io"]);
});

await scenario("bulk-stop-and-select-all", {}, async (page, state) => {
  state.delay = 400;
  await row(page, "main").waitFor();
  await page.getByRole("checkbox", { name: "Chọn tất cả profile" }).click();
  await page.getByText("4 profile đã chọn", { exact: false }).waitFor();
  await page.getByRole("button", { name: "Gắn domain" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("checkbox", { name: "minimax.io" }).click();
  await dialog.getByRole("button", { name: "Gắn 4" }).click();
  await dialog.getByRole("button", { name: "Dừng" }).click();
  await dialog.getByText(/cặp chưa chạy vì đã dừng/).waitFor();
  const adds = state.calls.filter((c) => c.method === "POST" && /\/accounts$/.test(c.path));
  assert.ok(adds.length < 4, `expected stop before finishing, got ${adds.length}`);
  await dialog.getByRole("button", { name: "Xong" }).click();
  await page.getByRole("button", { name: "Bỏ chọn" }).click();
  await page.getByText("Tick profile để thao tác hàng loạt").waitFor();
  assert.equal(await page.getByRole("button", { name: "Gắn domain" }).isDisabled(), true);
});

await scenario("delete-domain-only-without-recipe", {}, async (page, state) => {
  await openTab(page, "Domain");
  await page.getByRole("table", { name: "Danh sách domain" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Xóa domain chatgpt.com" }).count(), 0);
  await page.getByRole("button", { name: "Xóa domain chat.z.ai" }).click();
  const confirm = page.getByRole("alertdialog");
  await confirm.getByText(/gỡ 1 account.*xóa vĩnh viễn 2 file/).waitFor();
  await confirm.getByRole("button", { name: "Hủy" }).click();
  assert.equal(state.calls.some((c) => c.method === "DELETE"), false);
  // Tick lẫn domain có recipe: thanh công cụ chỉ tính domain xóa được.
  await tick(page, "Chọn domain chatgpt.com");
  const bulkDelete = page.getByRole("toolbar", { name: /domain/ }).getByRole("button", { name: /Xóa domain/ });
  assert.equal(await bulkDelete.isDisabled(), true);
  await tick(page, "Chọn domain minimax.io");
  await tick(page, "Chọn domain chat.z.ai");
  await page.getByRole("button", { name: "Xóa domain (2)" }).click();
  await confirm.getByRole("button", { name: "Xóa domain" }).click();
  await confirm.waitFor({ state: "hidden" });
  await page.getByRole("button", { name: "Xóa domain minimax.io" }).waitFor({ state: "hidden" });
  const deleted = state.calls.filter((c) => c.method === "DELETE").map((c) => decodeURIComponent(c.path));
  assert.deepEqual(deleted, ["/admin/domains/chat.z.ai", "/admin/domains/minimax.io"]);
  assert.equal(state.domains.some((d) => d.host === "chatgpt.com"), true);
});

await scenario("delete-domain-server-refusal", {
  domains: [{ host: "race.example", accounts: 0, recipes: [] }],
}, async (page) => {
  await openTab(page, "Domain");
  await page.getByRole("button", { name: "Xóa domain race.example" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Xóa domain" }).click();
  await page.getByRole("alert").filter({ hasText: "FIXTURE_IN_USE" }).waitFor();
  await page.getByRole("button", { name: "Xóa domain race.example" }).waitFor();
});

await scenario("domain-filter", {}, async (page) => {
  await openTab(page, "Domain");
  await tick(page, "Chọn domain minimax.io");
  await page.getByLabel("Lọc domain").fill("qwen");
  await page.getByText("1 domain đã chọn đang bị bộ lọc ẩn", { exact: false }).waitFor();
  await page.getByRole("checkbox", { name: "Chọn tất cả domain đang hiện" }).click();
  await page.getByText("2 domain đã chọn", { exact: false }).first().waitFor();
});

await scenario("locks-tab", {
  cooldowns: [{ recipe_slug: "chatgpt-web", account_key: "db:11", retry_after: 600, until_ms: Date.now() + 600000, reason: "limit" }],
}, async (page, state) => {
  const unlock = page.getByRole("button", { name: /Mở khóa main \/ acc1/ });
  await rowEl(page, "main").waitFor();
  assert.equal(await unlock.isVisible(), false);
  await page.getByRole("tab", { name: /Account bị khóa.*1/ }).waitFor();
  await rowEl(page, "main").getByRole("link", { name: "1 account" }).click();
  await unlock.waitFor();
  assert.match(page.url(), /\?tab=locks/);
  await unlock.click();
  await page.waitForTimeout(200);
  assert.ok(lastCall(state, "DELETE", /account-cooldowns/));
  // Mở thẳng link tab cũng phải vào đúng tab.
  await page.goto(`${base}/profiles?tab=domains`);
  await page.getByRole("table", { name: "Danh sách domain" }).waitFor();
});

await scenario("locked-account-signals", {
  cooldowns: [{ recipe_slug: "chatgpt-web", account_key: "db:11", retry_after: 600, until_ms: Date.now() + 600000, reason: "limit" }],
}, async (page) => {
  await rowEl(page, "main").getByRole("link", { name: "1 account" }).waitFor();
  await page.getByText("Bị khóa", { exact: true }).waitFor();
});

await scenario("empty-state", { profiles: [] }, async (page) => {
  await page.getByText("Chưa có profile").waitFor();
  await page.getByRole("button", { name: "Tạo profile đầu tiên" }).click();
  await page.getByRole("dialog").getByLabel("Tên profile").waitFor();
  await page.keyboard.press("Escape");
  await page.getByRole("dialog").waitFor({ state: "hidden" });
});

await scenario("load-error-retry", { failProfiles: true }, async (page, state) => {
  const alert = page.getByRole("alert").filter({ hasText: "FIXTURE_DOWN" });
  await alert.waitFor();
  state.failProfiles = false;
  await alert.getByRole("button", { name: "Thử lại" }).click();
  await row(page, "main").waitFor();
});

await scenario("import-from-file", {}, async (page, state) => {
  await page.getByRole("button", { name: "Nhập từ máy khác" }).click();
  const dialog = page.getByRole("dialog");
  assert.equal(await dialog.getByRole("button", { name: "Nhập", exact: true }).isDisabled(), true);
  await dialog.getByLabel("File profile").setInputFiles({ name: "bad.json", mimeType: "application/json", buffer: Buffer.from("{}") });
  await dialog.getByRole("alert").filter({ hasText: "không phải file profile" }).waitFor();
  const bundle = { format: "chat2api-profile", profile: { name: "moved" }, accounts: [{ host: "chatgpt.com" }], storage_state: { cookies: [{}] } };
  await dialog.getByLabel("File profile").setInputFiles({ name: "moved.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(bundle)) });
  await dialog.getByText(/1 account \(chatgpt.com\)/).waitFor();
  assert.equal(await dialog.getByLabel("Tên profile ở máy này").inputValue(), "moved");
  state.importResult = { name: "moved", imported: { accounts: 1, cookies: 1 } };
  state.profiles.push(makeProfile(50, "moved"));
  await dialog.getByRole("button", { name: "Nhập", exact: true }).click();
  await dialog.waitFor({ state: "hidden" });
  await page.getByRole("heading", { name: "moved", level: 3 }).waitFor();
  assert.deepEqual(lastCall(state, "POST", /import/).body.bundle.profile, { name: "moved" });
});

await scenario("keyboard-and-focus", {}, async (page) => {
  const work = row(page, "work");
  await work.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { name: "work", level: 3 }).waitFor();
  await page.getByRole("button", { name: "Cài đặt" }).focus();
  await page.keyboard.press("Enter");
  const sheet = page.getByRole("dialog");
  await sheet.waitFor();
  for (let i = 0; i < 15; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await sheet.evaluate((el) => el.contains(document.activeElement)), true, "focus left the sheet");
  }
  await page.keyboard.press("Escape");
  await sheet.waitFor({ state: "hidden" });
  await page.getByRole("button", { name: "Thao tác khác cho work" }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("menuitem", { name: "Nhân bản" }).waitFor();
  await page.keyboard.press("Escape");
  await page.getByRole("menuitem", { name: "Nhân bản" }).waitFor({ state: "hidden" });
});

for (const [width, height, dark] of[[375, 812, false], [1024, 768, true], [1440, 1000, true]]) {
  await scenario(`layout-${width}${dark ? "-dark" : ""}`, { viewport: { width, height }, dark }, async (page) => {
    await row(page, "main").waitFor();
    await page.getByRole("heading", { name: "main", level: 3 }).waitFor();
  });
}

await browser.close();
console.log("All profiles UI checks passed");
