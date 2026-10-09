import { chromium } from 'playwright';

// Checks the walkthrough narration in a real browser: which clip plays on which step, that choosing a language switches to
// that language's clips, that the speaker button silences it, that Agnez's orb shows while a clip plays, and that every
// clip request succeeds as audio. It logs what the page tries to play; it does not judge the sound itself.
const APP = process.env.APP_URL || 'http://127.0.0.1:3050';
const browser = await chromium.launch({ args: ['--autoplay-policy=no-user-gesture-required'] });
const report = {};

for (const vp of [{ name: 'desktop', width: 1440, height: 900 }, { name: 'mobile', width: 390, height: 844 }]) {
  const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
  await ctx.addInitScript(() => {
    try { localStorage.setItem('growit-signed-in', JSON.stringify({ email: 'admin', name: 'admin', sub: 'admin', at: 0 })); } catch { /* storage blocked */ }
    window.__plays = [];
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function patched() {
      const src = new URL(this.src, location.href).pathname;
      window.__plays.push({ src, event: 'play' });
      this.addEventListener('ended', () => window.__plays.push({ src, event: 'ended' }), { once: true });
      return play.call(this);
    };
  });
  const page = await ctx.newPage();
  const errors = [];
  const clipResponses = [];
  page.on('pageerror', (e) => errors.push(String(e.message).slice(0, 120)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 120)); });
  page.on('response', (r) => { if (r.url().includes('/tour/audio/')) clipResponses.push({ path: new URL(r.url()).pathname, status: r.status(), type: r.headers()['content-type'] }); });
  const played = () => page.evaluate(() => window.__plays.filter((p) => p.event === 'play').map((p) => p.src.replace('/tour/audio/', '')));
  const dialog = page.locator('[role=dialog][aria-labelledby=tour-title]');
  const orbShown = () => dialog.locator('canvas[role=img]').count();

  await page.goto(`${APP}/?nointro#/home`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(3200);
  const out = { welcomePlays: await played(), orbOnWelcome: await orbShown() };

  // Choose Kannada: the greeting must stop and the Kannada narration for the first toured step must start.
  await dialog.getByRole('button', { name: /kannada/i }).first().click();
  await page.waitForTimeout(1500);
  const afterChoose = await played();
  out.afterChoosingKannada = afterChoose.slice(out.welcomePlays.length);
  out.orbOnStep = await orbShown();

  // Next: the next Kannada clip. Then the speaker off, Next again: nothing new should play.
  await dialog.getByRole('button', { name: /ಮುಂದೆ/ }).first().click();
  await page.waitForTimeout(1500);
  out.afterNext = (await played()).slice(afterChoose.length);
  const before = (await played()).length;
  await dialog.getByRole('button', { name: /ಓದಿ ಹೇಳು/ }).first().click(); // speaker button toggles off
  await dialog.getByRole('button', { name: /ಮುಂದೆ/ }).first().click();
  await page.waitForTimeout(1500);
  out.playsAfterSpeakerOff = (await played()).length - before;
  out.orbAfterSpeakerOff = await orbShown();

  out.clipResponses = clipResponses.map((c) => `${c.status} ${c.type} ${c.path}`);
  out.badClipResponses = clipResponses.filter((c) => ![200, 206].includes(c.status) || !/audio/.test(c.type || '')).length;
  out.errors = errors;
  report[vp.name] = out;
  await ctx.close();
}
await browser.close();
console.log(JSON.stringify(report, null, 1));
