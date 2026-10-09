import { chromium } from 'playwright';

const URL = process.env.APP_URL || 'http://127.0.0.1:3050';
const OUT = process.env.TMPDIR || '/tmp';
const results = {};
const browser = await chromium.launch();

for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const rec = { apiCalls: [], consoleErrors: [] };
  results[vp.name] = rec;
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error') rec.consoleErrors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => rec.consoleErrors.push('pageerror: ' + String(e.message).slice(0, 200)));
  page.on('response', (r) => { const u = r.url(); if (/agent\/orchestrate|voice\/token|talk\/agent/.test(u)) rec.apiCalls.push(`${r.status()} ${u.replace(URL, '')}`); });
  try {
    await page.goto(`${URL}/#/agent`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2500);
    rec.bodyHead = (await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 200);
    rec.hash = await page.evaluate(() => location.hash);
    rec.overflowX = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    await page.screenshot({ path: `${OUT}/agnez-${vp.name}-agent.png` });

    const sec = page.locator('section[aria-label="Tell me what to do"]');
    rec.tellFound = await sec.count() > 0;
    if (rec.tellFound) {
      await sec.locator('input').first().fill('make a 20% off filter coffee offer for students, then lock my plan');
      rec.beforeClick = (await sec.innerText()).replace(/\s+/g, ' ').slice(0, 300);
      await sec.getByRole('button', { name: /Do it/ }).first().click();
      await page.waitForTimeout(7000);
      rec.hashAfter = await page.evaluate(() => location.hash);
      rec.afterBody = (await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 400);
      await page.screenshot({ path: `${OUT}/agnez-${vp.name}-tell.png` });
    }
  } catch (e) {
    rec.error = String(e.message).slice(0, 300);
    await page.screenshot({ path: `${OUT}/agnez-${vp.name}-err.png` }).catch(() => {});
  }
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(results, null, 2));
