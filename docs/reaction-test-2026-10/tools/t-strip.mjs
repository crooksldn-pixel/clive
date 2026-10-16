// A strip of the paint cooling: in-page snapshots of the canvas over the normal photo.
import { open } from './rxlib.mjs';
import fs from 'fs';
const [url, out] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page } = await open({ url, local: process.env.LOCAL === '1', jar: SP + 'cj-fd', net: SP + 'net-fd3' });
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1200);
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(4500);
const data = await page.evaluate(async () => {
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const c = document.querySelector('[data-crk-rx-canvas]'); const base = document.querySelector('.crk-rx__base');
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 5, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const snaps = [];
  const snap = async (label) => snaps.push([label, await createImageBitmap(c)]);
  ev('pointerdown', b.x + b.width * 0.18, b.y + b.height * 0.42);
  for (let i = 1; i <= 36; i++) {
    ev('pointermove', b.x + b.width * (0.18 + 0.64 * i / 36), b.y + b.height * (0.42 + 0.12 * Math.sin(i / 36 * Math.PI)));
    await new Promise((r) => requestAnimationFrame(r));
  }
  ev('pointerup', 0, 0);
  const t0 = performance.now();
  for (const ms of [0, 500, 1000, 1500, 2000]) {
    while (performance.now() - t0 < ms) await new Promise((r) => requestAnimationFrame(r));
    await snap(ms / 1000 + 's');
  }
  const w = c.width, h = c.height, s = 0.45, cw = Math.round(w * s), ch = Math.round(h * s);
  const out = document.createElement('canvas'); out.width = cw * snaps.length + 12 * (snaps.length - 1); out.height = ch + 40;
  const g = out.getContext('2d'); g.fillStyle = '#0B0A0E'; g.fillRect(0, 0, out.width, out.height);
  snaps.forEach(([label, bmp], k) => {
    const x = k * (cw + 12);
    g.drawImage(base, x, 0, cw, ch);
    g.drawImage(bmp, x, 0, cw, ch);
    g.fillStyle = '#A77AC7'; g.font = '22px monospace'; g.fillText('+' + label, x + 8, ch + 30);
  });
  return out.toDataURL('image/png');
});
fs.writeFileSync(out, Buffer.from(data.split(',')[1], 'base64'));
await browser.close();
