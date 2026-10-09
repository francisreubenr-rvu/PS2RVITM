import { chromium } from 'playwright';

// Walks the first-run tour step by step and reports, for each step: whether its target is found and highlighted, where the
// card sits, whether the card overlaps the highlighted element or leaves the screen. Also checks WHEN the tour appears in
// the real sign-in flow (login -> chooser -> app). Screenshots go to $TMPDIR/tour-*.png.
const URL = process.env.APP_URL || 'http://127.0.0.1:3050';
const OUT = process.env.TMPDIR || '/tmp';
const browser = await chromium.launch();
const report = { flow: {}, steps: {} };

const dialogInfo = (page) =>
  page.evaluate(() => {
    const d = document.querySelector('[role=dialog][aria-labelledby=tour-title]');
    if (!d) return null;
    const c = d.getBoundingClientRect();
    const ring = document.querySelector('.tour-ring');
    const rr = ring ? ring.getBoundingClientRect() : null;
    const ringOn = ring ? Number(getComputedStyle(ring).opacity) > 0.5 && rr.width > 4 : false;
    const overlap = ringOn
      ? !(c.right <= rr.left || c.left >= rr.right || c.bottom <= rr.top || c.top >= rr.bottom)
      : false;
    return {
      title: (d.querySelector('#tour-title')?.textContent || '').trim(),
      card: { x: Math.round(c.left), y: Math.round(c.top), w: Math.round(c.width), h: Math.round(c.height) },
      offscreen: c.left < 0 || c.top < 0 || c.right > innerWidth + 1 || c.bottom > innerHeight + 1,
      highlighted: ringOn,
      ring: ringOn ? { x: Math.round(rr.left), y: Math.round(rr.top), w: Math.round(rr.width), h: Math.round(rr.height) } : null,
      cardOverlapsHighlight: overlap,
    };
  });

// A. The real flow: fresh visitor signs in with admin / admin.
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${URL}/?nointro#/login`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(1500);
  await page.getByLabel(/email/i).first().fill('admin');
  await page.getByLabel(/password/i).first().fill('admin');
  await page.getByRole('button', { name: /sign in/i }).first().click();
  await page.waitForTimeout(2500);
  report.flow.afterSignIn = { hash: await page.evaluate(() => location.hash), tourOpen: Boolean(await dialogInfo(page)) };
  await page.screenshot({ path: `${OUT}/tour-flow-1-after-signin.png` });
  const notYet = page.getByRole('button', { name: /not yet/i }).first();
  if (await notYet.count()) { await notYet.click(); await page.waitForTimeout(600); }
  const looking = page.getByRole('button', { name: /just looking/i }).first();
  if (await looking.count()) { await looking.click(); await page.waitForTimeout(2500); }
  report.flow.afterChoosingLookingAround = { hash: await page.evaluate(() => location.hash), tourOpen: Boolean(await dialogInfo(page)) };
  await page.screenshot({ path: `${OUT}/tour-flow-2-after-choice.png` });
  report.flow.tourSeenKeys = await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith('tour-')));
  await ctx.close();
}

// B. Every step, desktop and phone, tour opened directly.
for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('growit-signed-in', JSON.stringify({ email: 'admin', name: 'admin', sub: 'admin', at: 0 })); } catch { /* storage blocked */ }
  });
  const page = await ctx.newPage();
  await page.goto(`${URL}/?nointro#/home`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2600);
  const rows = [];
  let info = await dialogInfo(page);
  rows.push({ step: 'welcome', ...info });
  await page.screenshot({ path: `${OUT}/tour-${vp.name}-00-welcome.png` });
  if (info) {
    const dlg = page.locator('[role=dialog][aria-labelledby=tour-title]');
    await dlg.getByRole('button', { name: /english/i }).first().click().catch(() => {});
    for (let i = 1; i <= 14; i += 1) {
      await page.waitForTimeout(900);
      info = await dialogInfo(page);
      if (!info) break;
      rows.push({ step: i, ...info });
      await page.screenshot({ path: `${OUT}/tour-${vp.name}-${String(i).padStart(2, '0')}.png` });
      const next = page.locator('[role=dialog][aria-labelledby=tour-title]').getByRole('button', { name: /^next/i }).first();
      if (!(await next.count())) break;
      await next.click({ timeout: 5000 });
    }
  }
  report.steps[vp.name] = rows;
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(report, null, 1));
