import { chromium } from 'playwright';

// Loads the screens that use voice input WITHOUT starting any call, and reports console errors and overflow.
// (Talk is left out on purpose: it opens an ElevenLabs call on arrival.)
const URL = process.env.APP_URL || 'http://127.0.0.1:3050';
const ROUTES = ['agent', 'launch', 'replies', 'settings', 'memory', 'connections', 'video', 'planner', 'home', 'studio', 'website', 'identity', 'brand', 'campaign', 'insights', 'log'];
const browser = await chromium.launch();
const out = {};
for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('growit-signed-in', JSON.stringify({ email: 'admin', name: 'admin', sub: 'admin', at: 0 })); } catch { /* storage blocked */ }
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 140)); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + String(e.message).slice(0, 140)));
  await page.goto(`${URL}/?nointro#/agent`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1800);
  const skip = page.getByText('Skip tour', { exact: false }).first();
  if (await skip.count()) { await skip.click().catch(() => {}); await page.waitForTimeout(500); }
  out[vp.name] = {};
  for (const r of ROUTES) {
    errors.length = 0;
    await page.evaluate((hash) => { location.hash = `/${hash}`; }, r);
    await page.waitForTimeout(1300);
    const info = await page.evaluate(() => ({
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      h1: (document.querySelector('h1')?.textContent || '').trim().slice(0, 50),
      blank: (document.querySelector('main')?.innerText || '').trim().length < 20,
    }));
    out[vp.name][r] = { ...info, errors: [...errors] };
  }
  await ctx.close();
}
await browser.close();
const bad = [];
for (const [vp, routes] of Object.entries(out)) for (const [r, v] of Object.entries(routes)) {
  if (v.errors.length || v.overflowX > 0 || v.blank) bad.push(`${vp} #/${r}: ${JSON.stringify(v)}`);
}
console.log(`routes checked: ${ROUTES.length} x 2 viewports`);
console.log(bad.length ? 'PROBLEMS:\n' + bad.join('\n') : 'all clean: no console errors, no overflow, no blank screen');
