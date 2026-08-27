const { chromium } = require('playwright-core');

(async () => {
  const exe = 'C:\\Users\\tdhuy\\AppData\\Local\\ms-playwright\\chromium-1223\\chrome-win64\\chrome.exe';
  const browser = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  const logs = [];
  page.on('console', (m) => logs.push(`[console.${m.type()}] ${m.text()}`));
  page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}\n${e.stack || ''}`));
  page.on('requestfailed', (r) => logs.push(`[reqfail] ${r.url()} ${r.failure()?.errorText}`));
  try {
    await page.goto('http://localhost:1420/', { waitUntil: 'networkidle', timeout: 20000 });
  } catch (e) {
    logs.push(`[goto-error] ${e.message}`);
  }
  await page.waitForTimeout(3000);
  // Try to find a checkbox and click it
  const cbs = await page.$$('input[type=checkbox]');
  logs.push(`[info] checkbox count: ${cbs.length}`);
  let clickInfo = 'none';
  if (cbs.length) {
    try {
      const before = await cbs[0].isChecked();
      await cbs[0].click({ timeout: 3000 });
      await page.waitForTimeout(500);
      const after = await cbs[0].isChecked();
      clickInfo = `before=${before} after=${after}`;
    } catch (e) { clickInfo = `click-error: ${e.message}`; }
  }
  logs.push(`[click] ${clickInfo}`);
  console.log(logs.join('\n'));
  await browser.close();
})();
