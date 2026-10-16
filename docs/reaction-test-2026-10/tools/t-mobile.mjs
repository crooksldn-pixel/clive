// Mobile (touch): order under the buy panel, vertical swipe scrolls the page and does
// not paint, sideways swipe paints and does not scroll, tap dabs, rotation keeps paint,
// frame timing under 4x CPU throttle, CLS.
// usage: node t-mobile.mjs <url> <outprefix> [local]
import { open, coverage, state, frameBox } from './rxlib.mjs';
const [url, out, local] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page, errs, ctx, bytes } = await open({ url, width: 390, height: 844, mobile: true, local: local === 'local', jar: SP + 'cj-m', net: SP + 'net-m' });
const log = (k, v) => console.log(k.padEnd(30), typeof v === 'string' ? v : JSON.stringify(v));
const cdp = await ctx.newCDPSession(page);
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1500);
await page.addStyleTag({ content: '.crk-stickybar{visibility:hidden!important}' });

const order = await page.evaluate(() => {
  const r = (s) => { const e = document.querySelector(s); const b = e.getBoundingClientRect(); return { y: Math.round(b.y + scrollY), h: Math.round(b.height) }; };
  return { gallery: r('[data-crk-gallery]'), panel: r('.crk-panel-record'), buy: r('[data-crk-buy]'), card: r('.crk-rx'), stage: r('.crk-rx__stage'), stack: r('.crk-stack') };
});
log('vertical order', order);
log('gap buy panel -> card', order.card.y - (order.panel.y + order.panel.h));

async function touchDrag(x0, y0, x1, y1, steps = 14, ms = 16) {
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: x0, y: y0, id: 1 }] });
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: x0 + (x1 - x0) * t, y: y0 + (y1 - y0) * t, id: 1 }] });
    await page.waitForTimeout(ms);
  }
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await page.waitForTimeout(400);
}

// Bring the card into view and let the sample stroke draw.
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(2200);
await page.screenshot({ path: `${out}-1-card.png` });
log('state in view', await state(page));
let cov0 = await coverage(page);
log('coverage (teaser)', cov0);

// 1. Vertical swipe starting on the photo: the page must scroll, nothing paints.
let fb = await frameBox(page);
let sy = await page.evaluate(() => scrollY);
await touchDrag(fb.x + fb.w * 0.5, fb.y + fb.h * 0.75, fb.x + fb.w * 0.52, fb.y + fb.h * 0.15, 16);
await page.waitForTimeout(800);
let sy2 = await page.evaluate(() => scrollY);
log('vertical swipe: scrollY', [sy, sy2, 'moved ' + (sy2 - sy)]);
log('vertical swipe: coverage', [cov0, await coverage(page)]);
log('vertical swipe: events', (await state(page)).events);

// 2. Sideways swipes: paint, no scroll.
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(500);
fb = await frameBox(page);
sy = await page.evaluate(() => scrollY);
for (const fy of [0.4, 0.55, 0.7]) await touchDrag(fb.x + fb.w * 0.15, fb.y + fb.h * fy, fb.x + fb.w * 0.85, fb.y + fb.h * (fy + 0.06), 16);
sy2 = await page.evaluate(() => scrollY);
const covSide = await coverage(page);
log('sideways swipes: scrollY', [sy, sy2]);
log('sideways swipes: coverage', [cov0, covSide]);
log('sideways swipes: state', await state(page));
await page.screenshot({ path: `${out}-2-painted.png` });

// 3. Diagonal that starts sideways then goes down: keeps painting, page stays put.
sy = await page.evaluate(() => scrollY);
await touchDrag(fb.x + fb.w * 0.2, fb.y + fb.h * 0.3, fb.x + fb.w * 0.5, fb.y + fb.h * 0.3, 6);
await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: fb.x + fb.w * 0.2, y: fb.y + fb.h * 0.25, id: 1 }] });
for (let i = 1; i <= 8; i++) { await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: fb.x + fb.w * (0.2 + 0.05 * i), y: fb.y + fb.h * 0.25 + (i > 4 ? (i - 4) * 30 : 0), id: 1 }] }); await page.waitForTimeout(16); }
await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
await page.waitForTimeout(400);
log('sideways-then-down: scrollY', [sy, await page.evaluate(() => scrollY)]);

// 4. Tap leaves a dab.
const covBeforeTap = await coverage(page);
await page.touchscreen.tap(fb.x + fb.w * 0.5, fb.y + fb.h * 0.9);
await page.waitForTimeout(400);
log('tap: coverage', [covBeforeTap, await coverage(page)]);

// 5. Buttons by tap.
await page.locator('[data-crk-rx-toggle]').tap();
await page.waitForTimeout(500);
log('tap VIEW FULL', (await state(page)).view);
await page.screenshot({ path: `${out}-3-full.png` });
await page.locator('[data-crk-rx-toggle]').tap();
await page.waitForTimeout(400);
log('tap VIEW ORIGINAL', (await state(page)).view);

// 6. Rotate: landscape and back. Paint must stay.
const covR = await coverage(page);
await page.setViewportSize({ width: 844, height: 390 });
await page.waitForTimeout(800);
log('landscape coverage (was)', [await coverage(page), covR]);
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(300);
await page.screenshot({ path: `${out}-4-landscape.png` });
log('landscape stage', await page.evaluate(() => { const b = document.querySelector('.crk-rx__stage').getBoundingClientRect(); return { w: Math.round(b.width), h: Math.round(b.height), vh: innerHeight }; }));
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(800);
log('portrait again coverage', await coverage(page));

// 7. Reset.
await page.locator('[data-crk-rx-reset]').tap();
await page.waitForTimeout(300);
log('reset', [await coverage(page), (await state(page)).word]);

// 8. Frame time while painting with the CPU throttled 4x (mid-range phone).
await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
const r = await page.evaluate(async () => {
  const f = document.querySelector('[data-crk-rx-frame]'); const b = f.getBoundingClientRect();
  const ev = (type, x, y) => f.dispatchEvent(new PointerEvent(type, { pointerId: 9, pointerType: 'pen', isPrimary: true, button: 0, buttons: 1, clientX: x, clientY: y, bubbles: true, cancelable: true }));
  const frames = []; let last = performance.now();
  ev('pointerdown', b.x + b.width * 0.15, b.y + b.height * 0.3);
  for (let i = 0; i <= 40; i++) {
    ev('pointermove', b.x + b.width * (0.15 + 0.7 * i / 40), b.y + b.height * (0.3 + 0.4 * i / 40));
    await new Promise((res) => requestAnimationFrame(res));
    const now = performance.now(); frames.push(now - last); last = now;
  }
  ev('pointerup', 0, 0);
  frames.sort((a, c) => a - c);
  return { median: frames[20].toFixed(1), p90: frames[36].toFixed(1), canvas: document.querySelector('[data-crk-rx-canvas]').width + 'x' + document.querySelector('[data-crk-rx-canvas]').height, dpr: devicePixelRatio };
});
await cdp.send('Emulation.setCPUThrottlingRate', { rate: 1 });
log('4x throttled paint frames', r);
log('CLS', await page.evaluate(() => ({ cls: +window.__cls.toFixed(4), shifts: window.__shifts })));
log('errors (not network)', errs.filter((e) => !/Failed to load resource|Failed to fetch|privacy_banner/.test(e)));
log('image bytes', Object.entries(bytes).filter(([u]) => /\/files\/.*\.(png|jpe?g|webp)/.test(u)).map(([u, n]) => u.replace(/^.*\/files\//, '').slice(0, 90) + ' ' + n));
await browser.close();
