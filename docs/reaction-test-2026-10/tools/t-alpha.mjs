import { open } from './rxlib.mjs';
const [url] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page } = await open({ url, local: process.env.LOCAL === '1', jar: SP + 'cj-fd', net: SP + 'net-fd4' });
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1200);
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(4500);
const r = await page.evaluate(async () => {
  const src = [...document.scripts].map((s) => s.src).find((s) => /crooks-reaction\.js/.test(s));
  const txt = await (await fetch(src)).text();
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const c = document.querySelector('[data-crk-rx-canvas]'); const g = c.getContext('2d');
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 5, pointerType: 'mouse', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const y = 0.45;
  ev('pointerdown', b.x + b.width * 0.2, b.y + b.height * y);
  for (let i = 1; i <= 20; i++) { ev('pointermove', b.x + b.width * (0.2 + 0.6 * i / 20), b.y + b.height * y); await new Promise((r) => requestAnimationFrame(r)); }
  ev('pointerup', 0, 0);
  await new Promise((r) => requestAnimationFrame(r)); await new Promise((r) => requestAnimationFrame(r));
  // alpha along the stroke's centre line, on the jacket (reacted photo alpha ~ 1 there)
  const dpr = c.width / b.width, row = Math.round(b.height * y * dpr);
  const d = g.getImageData(0, row, c.width, 1).data; const vals = [];
  for (let x = Math.round(b.width * 0.25 * dpr); x < b.width * 0.75 * dpr; x += Math.round(20 * dpr)) vals.push(d[x * 4 + 3]);
  return { newBuild: txt.includes('Math.min(700'), fadeAttr: document.querySelector('[data-crk-reaction]').getAttribute('data-crk-rx-fade'), alphaAlongStroke: vals };
});
console.log(JSON.stringify(r));
await browser.close();
