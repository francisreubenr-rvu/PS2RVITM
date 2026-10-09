import { chromium } from 'playwright';

// Screenshots of the reference site with the first-run tour out of the way, for the glow and the floating orb.
const REF = process.env.REF_URL || 'https://growit-studio.vercel.app/';
const OUT = process.env.TMPDIR || '/tmp';
const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('tour-seen:local', '1'); localStorage.setItem('intro-seen', '1'); } catch { /* storage blocked */ }
  });
  const page = await ctx.newPage();
  for (const [name, hash] of [['home', '#/home'], ['talk', '#/voice']]) {
    await page.goto(`${REF}${hash}`, { waitUntil: 'networkidle', timeout: 45000 }).catch(() => {});
    await page.waitForTimeout(4500);
    await page.screenshot({ path: `${OUT}/ref-${vp.name}-${name}-a.png` });
    await page.waitForTimeout(2200);
    await page.screenshot({ path: `${OUT}/ref-${vp.name}-${name}-b.png` });
    const info = await page.evaluate(() => ({
      backdrop: document.documentElement.dataset.backdrop,
      canvases: [...document.querySelectorAll('canvas')].map((c) => ({ cls: String(c.className).slice(0, 50), w: Math.round(c.getBoundingClientRect().width), h: Math.round(c.getBoundingClientRect().height) })),
      appBackdrop: document.querySelector('.app-backdrop')?.className,
      bodyText: document.body.innerText.replace(/\s+/g, ' ').slice(0, 120),
    }));
    console.log(vp.name, name, JSON.stringify(info));
  }
  await ctx.close();
}
await browser.close();
