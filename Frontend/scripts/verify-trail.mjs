import { chromium } from 'playwright';

// Checks the pixel-trail backdrop: it mounts, paints squares, follows the mouse through the glass panels, and is quiet.
const URL = process.env.APP_URL || 'http://127.0.0.1:3050';
const OUT = process.env.TMPDIR || '/tmp';
const browser = await chromium.launch();
const results = {};

const painted = (page) =>
  page.evaluate(() => {
    const canvas = document.querySelector('.backdrop-trail canvas');
    if (!canvas) return { canvas: false };
    const ctx = canvas.getContext('2d');
    const { width, height } = canvas;
    const data = ctx.getImageData(0, 0, width, height).data;
    let n = 0;
    for (let i = 3; i < data.length; i += 4) if (data[i] > 8) n += 1;
    return { canvas: true, width, height, paintedPixels: n };
  });

for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const rec = { errors: [] };
  results[vp.name] = rec;
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, hasTouch: vp.name === 'mobile' });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('growit-signed-in', JSON.stringify({ email: 'admin', name: 'admin', sub: 'admin', at: 0 })); } catch { /* storage blocked */ }
  });
  const page = await ctx.newPage();
  page.on('console', (m) => { if (m.type() === 'error') rec.errors.push(m.text().slice(0, 160)); });
  page.on('pageerror', (e) => rec.errors.push('pageerror: ' + String(e.message).slice(0, 160)));
  try {
    await page.goto(`${URL}/?nointro#/home`, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(2500);
    // The first-run walkthrough dims the page; dismiss it so the backdrop is what the screenshot shows.
    const skip = page.getByText('Skip tour', { exact: false }).first();
    if (await skip.count()) { await skip.click().catch(() => {}); await page.waitForTimeout(800); }
    rec.backdrop = await page.evaluate(() => document.documentElement.dataset.backdrop);
    rec.before = await painted(page);
    await page.screenshot({ path: `${OUT}/trail-${vp.name}-before.png` });
    // Sweep the mouse over the middle of the page, where the glass panels sit on top of the backdrop.
    const { width, height } = vp;
    for (let i = 0; i <= 24; i += 1) {
      await page.mouse.move(width * (0.15 + 0.7 * (i / 24)), height * (0.3 + 0.35 * Math.sin(i / 4)));
      await page.waitForTimeout(25);
    }
    rec.after = await painted(page);
    await page.screenshot({ path: `${OUT}/trail-${vp.name}-after.png` });
    rec.overflowX = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    rec.imageLoaded = await page.evaluate(() => {
      const img = document.querySelector('.backdrop-trail img');
      return img ? { complete: img.complete, w: img.naturalWidth, src: img.getAttribute('src') } : null;
    });
  } catch (e) {
    rec.error = String(e.message).slice(0, 300);
  }
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(results, null, 2));
