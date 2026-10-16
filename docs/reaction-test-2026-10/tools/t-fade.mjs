// Fade-back: paint one stroke, sample the paint and the status word over time.
// usage: node t-fade.mjs <url> <outprefix> [mobile]
import { open, coverage, frameBox, state } from './rxlib.mjs';
const [url, out, mob] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const mobile = mob === 'mobile';
const { browser, page, errs, ctx } = await open({ url, width: mobile ? 390 : 1440, height: mobile ? 844 : 900, mobile, local: process.env.LOCAL === '1', jar: SP + 'cj-fd', net: SP + 'net-fd' });
const cdp = await ctx.newCDPSession(page);
const log = (k, v) => console.log(k.padEnd(30), typeof v === 'string' ? v : JSON.stringify(v));
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1200);
await page.addStyleTag({ content: '.crk-stickybar{visibility:hidden!important}' });
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
// The sample stroke should draw, hold, then cool away on its own.
const tz = Date.now(); const teaser = [];
for (let i = 0; i < 16; i++) { await page.waitForTimeout(250); teaser.push([Date.now() - tz, await coverage(page), (await state(page)).word]); }
log('sample stroke over time', teaser.map(([t, c, w]) => `${(t / 1000).toFixed(1)}s ${c} ${w}`));
// Paint a stroke in-page (real timing, no harness lag), then sample.
const fb = await frameBox(page);
const t0 = await page.evaluate(async () => {
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 5, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  ev('pointerdown', b.x + b.width * 0.2, b.y + b.height * 0.45);
  for (let i = 1; i <= 30; i++) { ev('pointermove', b.x + b.width * (0.2 + 0.6 * i / 30), b.y + b.height * 0.45); await new Promise((r) => requestAnimationFrame(r)); }
  ev('pointerup', b.x + b.width * 0.8, b.y + b.height * 0.45);
  return performance.now();
});
const samples = []; const shots = { 100: 'a', 900: 'b', 1500: 'c' };
const start = Date.now();
for (const ms of [100, 400, 700, 900, 1200, 1500, 1800, 2100, 2600]) {
  const wait = ms - (Date.now() - start); if (wait > 0) await page.waitForTimeout(wait);
  const s = await state(page);
  samples.push(`${(ms / 1000).toFixed(1)}s cov=${await coverage(page)} ${s.word} reset=${s.resetDisabled === 'true' ? 'off' : 'on'}`);
  if (shots[ms]) await page.screenshot({ path: `${out}-${shots[ms]}.png` });
}
log('after a stroke', samples);
// No loop left running once it has cooled.
const loops = await page.evaluate(async () => { let n = 0; const orig = window.requestAnimationFrame; const t = performance.now(); window.requestAnimationFrame = function (cb) { n++; return orig.call(window, cb); }; await new Promise((r) => setTimeout(r, 1000)); window.requestAnimationFrame = orig; return n; });
log('rAF calls in 1s at rest', loops);
// Frame time while a long trail fades, CPU slowed 4x.
await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
const perf = await page.evaluate(async () => {
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 6, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const frames = []; let last = performance.now();
  ev('pointerdown', b.x + b.width * 0.15, b.y + b.height * 0.2);
  for (let i = 0; i <= 90; i++) {
    const t = i / 90; ev('pointermove', b.x + b.width * (0.15 + 0.7 * ((i % 30) / 30)), b.y + b.height * (0.2 + 0.6 * t));
    await new Promise((r) => requestAnimationFrame(r)); const now = performance.now(); frames.push(now - last); last = now;
  }
  ev('pointerup', 0, 0);
  for (let i = 0; i < 60; i++) { await new Promise((r) => requestAnimationFrame(r)); const now = performance.now(); frames.push(now - last); last = now; }
  frames.sort((a, c) => a - c);
  return { median: frames[75].toFixed(1), p90: frames[135].toFixed(1), max: frames[150].toFixed(1) };
});
await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
log('frames, 4x slower CPU', perf);
log('errors (not network)', errs.filter((e) => !/Failed to load resource|Failed to fetch|privacy_banner/.test(e)));
await browser.close();
