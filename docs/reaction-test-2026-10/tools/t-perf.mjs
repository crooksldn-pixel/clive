import { open, frameBox } from './rxlib.mjs';
const [url] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page, ctx } = await open({ url, local: process.argv[3] === 'local', jar: SP + 'cj-p', net: SP + 'net-p' });
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1500);
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(2000);
const fb = await frameBox(page);
let t = Date.now();
await page.mouse.move(5, 300); await page.mouse.move(5, 800, { steps: 30 });
console.log('30 moves outside the card:', Date.now() - t, 'ms');
t = Date.now();
await page.mouse.move(fb.x + fb.w * 0.2, fb.y + fb.h * 0.5); await page.mouse.move(fb.x + fb.w * 0.8, fb.y + fb.h * 0.5, { steps: 30 });
console.log('30 hover moves over the card:', Date.now() - t, 'ms');
// In-page timing of the paint path: synthetic pointer events, frames timed with rAF.
const r = await page.evaluate(async () => {
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 7, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const frames = []; let last = performance.now();
  ev('pointerdown', b.x + b.width * 0.2, b.y + b.height * 0.3);
  for (let i = 0; i <= 60; i++) {
    ev('pointermove', b.x + b.width * (0.2 + 0.6 * i / 60), b.y + b.height * (0.3 + 0.4 * i / 60));
    await new Promise((res) => requestAnimationFrame(res));
    const now = performance.now(); frames.push(now - last); last = now;
  }
  ev('pointerup', b.x + b.width * 0.8, b.y + b.height * 0.7);
  frames.sort((a, c) => a - c);
  return { median: frames[30].toFixed(1), p90: frames[54].toFixed(1), max: frames[60].toFixed(1), canvas: document.querySelector('[data-crk-rx-canvas]').width + 'x' + document.querySelector('[data-crk-rx-canvas]').height };
});
console.log('frame ms while painting (synthetic):', r);
const idle = await page.evaluate(async () => { const frames = []; let last = performance.now(); for (let i = 0; i < 30; i++) { await new Promise((res) => requestAnimationFrame(res)); const n = performance.now(); frames.push(n - last); last = n; } frames.sort((a, c) => a - c); return frames[15].toFixed(1); });
console.log('idle frame ms (headless baseline):', idle);
await browser.close();
