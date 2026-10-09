import { chromium } from 'playwright';

// While a screen waits on a slow API, an orb (role=status with a canvas) must be on screen, never plain text or a blank page.
const URL = process.env.APP_URL || 'http://127.0.0.1:3050';
const ID = process.env.CAMPAIGN_ID || 'demo-613663d1220f';
const CASES = [
  { name: 'dashboard', hash: `/dashboard/${ID}`, slow: /\/campaign\/[^/]+\/dashboard/ },
  { name: 'plan', hash: `/plan/${ID}`, slow: /\/campaign\/[^/]+\/plan(\?|$)/ },
  { name: 'campaign board', hash: `/campaign/${ID}`, slow: /\/campaign\/[^/]+\/board/ },
];
const browser = await chromium.launch();
const rows = [];
for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  for (const c of CASES) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    await ctx.addInitScript(() => {
      try { localStorage.setItem('growit-signed-in', JSON.stringify({ email: 'admin', name: 'admin', sub: 'admin', at: 0 })); } catch { /* storage blocked */ }
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e.message).slice(0, 120)));
    await page.route(c.slow, async (route) => { await new Promise((r) => setTimeout(r, 3000)); route.continue().catch(() => {}); });
    await page.goto(`${URL}/?nointro#/${c.hash.split('/')[1]}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1200);
    const skip = page.getByText('Skip tour', { exact: false }).first();
    if (await skip.count()) { await skip.click().catch(() => {}); await page.waitForTimeout(400); }
    await page.evaluate((h) => { location.hash = h; }, c.hash);
    await page.waitForTimeout(1200);
    const state = await page.evaluate(() => {
      const orbs = [...document.querySelectorAll('[role=status] canvas[role=img]')].length;
      const main = (document.querySelector('main')?.innerText || '').replace(/\s+/g, ' ').trim();
      return { orbs, plainLoading: /^Loading/i.test(main), text: main.slice(0, 70) };
    });
    rows.push({ vp: vp.name, screen: c.name, ...state, errors });
    await ctx.close();
  }
}
await browser.close();
console.table(rows.map((r) => ({ viewport: r.vp, screen: r.screen, orbs: r.orbs, plainLoadingText: r.plainLoading, errors: r.errors.length, text: r.text })));
