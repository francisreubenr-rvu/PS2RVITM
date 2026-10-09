import { chromium } from 'playwright';

// Looks at the reference site (the deployed GrowIt studio) to see its glow: screenshots at desktop and phone width, and the
// computed styles of the elements that carry the glow (backdrop layers, canvases, anything with a big blur or shadow).
const REF = process.env.REF_URL || 'https://growit-studio.vercel.app/';
const OUT = process.env.TMPDIR || '/tmp';
const browser = await chromium.launch();
const report = {};
for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  const page = await ctx.newPage();
  const failed = [];
  page.on('requestfailed', (r) => failed.push(r.url().slice(0, 100)));
  const res = await page.goto(REF, { waitUntil: 'networkidle', timeout: 45000 }).catch((e) => ({ status: () => String(e.message).slice(0, 80) }));
  await page.waitForTimeout(3500);
  await page.screenshot({ path: `${OUT}/ref-${vp.name}-1.png` });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${OUT}/ref-${vp.name}-2.png` });
  report[vp.name] = await page.evaluate(() => {
    const out = { title: document.title, hash: location.hash, bodyBg: getComputedStyle(document.body).backgroundColor, text: document.body.innerText.replace(/\s+/g, ' ').slice(0, 200), glowish: [], canvases: [] };
    for (const c of document.querySelectorAll('canvas')) {
      const r = c.getBoundingClientRect();
      out.canvases.push({ cls: String(c.className).slice(0, 60), w: Math.round(r.width), h: Math.round(r.height), pos: getComputedStyle(c).position, z: getComputedStyle(c).zIndex });
    }
    for (const el of document.querySelectorAll('*')) {
      const cs = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) continue;
      const blurry = /blur\(\s*([2-9]\d|\d{3,})/.test(cs.filter) || /(\d{2,})px\s+(\d{2,})px/.test(cs.boxShadow) || /radial-gradient|conic-gradient/.test(cs.backgroundImage);
      if (blurry && out.glowish.length < 18) {
        out.glowish.push({ tag: el.tagName.toLowerCase(), cls: String(el.className).slice(0, 70), size: `${Math.round(r.width)}x${Math.round(r.height)}`, filter: cs.filter.slice(0, 60), shadow: cs.boxShadow.slice(0, 130), bg: cs.backgroundImage.slice(0, 200), anim: cs.animationName });
      }
    }
    return out;
  });
  report[vp.name].failedRequests = failed.slice(0, 5);
  report[vp.name].status = typeof res?.status === 'function' ? res.status() : 'n/a';
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(report, null, 1));
