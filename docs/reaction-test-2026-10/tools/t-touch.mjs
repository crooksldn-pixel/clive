// Touch rules: a finger on the garment paints in any direction and never scrolls;
// a finger on the empty ground or the card text scrolls.
// usage: node t-touch.mjs <url> [local]
import { open, coverage, frameBox, state } from './rxlib.mjs';
const [url, local] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page, errs, ctx } = await open({ url, width: 390, height: 844, mobile: true, local: local === 'local', jar: SP + 'cj-tt', net: SP + 'net-tt' });
const cdp = await ctx.newCDPSession(page);
const log = (k, v) => console.log(k.padEnd(44), typeof v === 'string' ? v : JSON.stringify(v));
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1200);
await page.addStyleTag({ content: '.crk-stickybar{visibility:hidden!important}' });
async function drag(x0, y0, x1, y1, steps = 16) {
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x0, y: y0, id: 1 }] });
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x0 + (x1 - x0) * t, y: y0 + (y1 - y0) * t, id: 1 }] });
    await page.waitForTimeout(16);
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(700);
}
async function center() { await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' })); await page.waitForTimeout(2000); return frameBox(page); }
async function trial(label, fx0, fy0, fx1, fy1, from = 'frame') {
  let fb = await center();
  let x0, y0, x1, y1;
  if (from === 'frame') { x0 = fb.x + fb.w * fx0; y0 = fb.y + fb.h * fy0; x1 = fb.x + fb.w * fx1; y1 = fb.y + fb.h * fy1; }
  else { const b = await page.evaluate((s) => { const r = document.querySelector(s).getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }, from); x0 = b.x + b.w * fx0; y0 = b.y + b.h * fy0; x1 = x0 + (fx1 - fx0) * 300; y1 = y0 + (fy1 - fy0) * 300; }
  const sy = await page.evaluate(() => scrollY), c0 = await coverage(page);
  await drag(x0, y0, x1, y1);
  const sy2 = await page.evaluate(() => scrollY), c1 = await coverage(page);
  log(label, { scrolled: Math.round(sy2 - sy), painted: +(c1 - c0).toFixed(4) });
}
await trial('jacket, straight up', 0.5, 0.75, 0.5, 0.2);
await trial('jacket, straight down', 0.45, 0.3, 0.45, 0.85);
await trial('jacket, sideways', 0.2, 0.55, 0.8, 0.6);
await trial('jacket, diagonal', 0.3, 0.8, 0.7, 0.35);
await trial('empty ground (top-left), straight up', 0.03, 0.12, 0.03, 0.0);
await trial('empty ground (bottom-left), straight up', 0.02, 0.97, 0.03, 0.6);
await trial('card title, straight up', 0.5, 0.5, 0.5, -0.6, '.crk-rx__title');
await trial('status line, straight up', 0.3, 0.5, 0.3, -0.6, '.crk-rx__status');
const s = await state(page);
log('events', s.events);
log('errors (not network)', errs.filter((e) => !/Failed to load resource|Failed to fetch|privacy_banner/.test(e)));
await browser.close();
