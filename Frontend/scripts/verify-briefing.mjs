import { chromium } from 'playwright';

const URL = process.env.APP_URL || 'http://127.0.0.1:3050';
const OUT = process.env.TMPDIR || '/tmp';
const browser = await chromium.launch({ args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
const page = await ctx.newPage();
const calls = [];
const sockets = [];
const errors = [];
page.on('response', (r) => { const u = r.url(); if (/voice\/token|talk\/agent|elevenlabs|livekit/.test(u)) calls.push(`${r.status()} ${u.slice(0, 80)}`); });
page.on('websocket', (ws) => sockets.push(ws.url().slice(0, 80)));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
page.on('pageerror', (e) => errors.push('pageerror: ' + String(e.message).slice(0, 200)));

await page.goto(`${URL}/#/memory`, { waitUntil: 'domcontentloaded', timeout: 30000 });
await page.waitForTimeout(3000);
const btn = page.getByRole('button', { name: /Start a briefing/ });
const enabled = await btn.count() ? await btn.first().isEnabled() : false;
if (enabled) {
  await btn.first().click();
  await page.waitForTimeout(10000);
}
const body = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
const status = ['Agnez is speaking', 'Listening', 'Paused', 'not set up', 'blocked', 'problem', 'Could not'].filter((s) => body.includes(s));
await page.screenshot({ path: `${OUT}/agnez-briefing.png` });
console.log(JSON.stringify({ enabled, status, calls, sockets, errors }, null, 2));
await browser.close();
