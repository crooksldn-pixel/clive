import { open, frameBox } from './rxlib.mjs';
const [url] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page } = await open({ url, local: process.env.LOCAL === '1', jar: SP + 'cj-fd', net: SP + 'net-fd2' });
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1200);
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(4500); // let the sample stroke finish cooling
const r = await page.evaluate(async () => {
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const c = document.querySelector('[data-crk-rx-canvas]'); const g = c.getContext('2d');
  const cov = () => { const d = g.getImageData(0, 0, c.width, c.height).data; let on = 0, sum = 0; for (let i = 3; i < d.length; i += 16) { if (d[i] > 8) on++; sum += d[i]; } return [+(on / (d.length / 16)).toFixed(4), Math.round(sum / (d.length / 16) * 10) / 10]; };
  const word = () => document.querySelector('[data-crk-rx-word]').textContent;
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 5, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const out = [];
  const t0 = performance.now();
  ev('pointerdown', b.x + b.width * 0.2, b.y + b.height * 0.45);
  for (let i = 1; i <= 30; i++) { ev('pointermove', b.x + b.width * (0.2 + 0.6 * i / 30), b.y + b.height * 0.45); await new Promise((r) => requestAnimationFrame(r)); if (i % 10 === 0) out.push(['move' + i, Math.round(performance.now() - t0), ...cov(), word()]); }
  ev('pointerup', b.x + b.width * 0.8, b.y + b.height * 0.45);
  const tu = performance.now();
  while (performance.now() - tu < 3000) { await new Promise((r) => setTimeout(r, 200)); out.push(['+' + Math.round(performance.now() - tu), ...cov(), word()]); }
  return out;
});
for (const row of r) console.log(JSON.stringify(row));
await browser.close();
