// Desktop: layout, teaser, mouse painting, events, VIEW FULL, RESET, resize, CLS, errors.
// usage: node t-desktop.mjs <url> <outprefix> [local]
import { open, coverage, state, frameBox, spyPublish } from './rxlib.mjs';
const [url, out, local] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page, errs, ctx } = await open({ url, local: local === 'local', jar: SP + 'cj-d', net: SP + 'net-d' });
const log = (k, v) => console.log(k.padEnd(28), typeof v === 'string' ? v : JSON.stringify(v));
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1500);
log('spy', await spyPublish(page));
log('CLS at load', await page.evaluate(() => +window.__cls.toFixed(4)));
await page.screenshot({ path: `${out}-1-top.png` });

// Where does the card sit? Under the gallery, buy panel beside it.
const lay = await page.evaluate(() => {
  const r = (s) => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return { x: Math.round(b.x), y: Math.round(b.y + scrollY), w: Math.round(b.width), h: Math.round(b.height) }; };
  return { gallery: r('[data-crk-gallery]'), panel: r('.crk-panel-record'), card: r('.crk-rx'), stage: r('.crk-rx__stage'), stack: r('.crk-stack') };
});
log('layout', lay);

// Scroll the card into view; the sample stroke should draw once.
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.waitForTimeout(2200);
log('after teaser', await state(page));
log('coverage after teaser', await coverage(page));
const panelInView = await page.evaluate(() => { const b = document.querySelector('.crk-panel-record [data-crk-buy]').getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom), vh: innerHeight }; });
log('buy button while testing', panelInView);
await page.screenshot({ path: `${out}-2-teaser.png` });

// Paint with the mouse: three passes across the jacket.
let fb = await frameBox(page);
const t0 = Date.now();
for (const fy of [0.38, 0.5, 0.62]) {
  await page.mouse.move(fb.x + fb.w * 0.2, fb.y + fb.h * fy);
  await page.mouse.down();
  await page.mouse.move(fb.x + fb.w * 0.8, fb.y + fb.h * (fy + 0.04), { steps: 30 });
  await page.mouse.up();
}
log('paint time ms', Date.now() - t0);
await page.waitForTimeout(400);
log('after painting', await state(page));
const covPaint = await coverage(page);
log('coverage after paint', covPaint);
await page.mouse.move(fb.x + fb.w * 0.5, fb.y + fb.h * 0.3);
await page.waitForTimeout(100);
await page.screenshot({ path: `${out}-3-painted.png` });
log('ring', await page.evaluate(() => { const r = document.querySelector('[data-crk-rx-ring]'); return { hidden: r.hidden, w: r.style.width }; }));

// Hold still: the spot should spread.
await page.mouse.move(fb.x + fb.w * 0.5, fb.y + fb.h * 0.78);
const covBeforeHold = await coverage(page);
await page.mouse.down();
await page.waitForTimeout(1500);
await page.mouse.up();
await page.waitForTimeout(200);
log('hold: coverage before/after', [covBeforeHold, await coverage(page)]);

// VIEW FULL REACTION and back.
await page.click('[data-crk-rx-toggle]');
await page.waitForTimeout(500);
log('full view', await state(page));
await page.screenshot({ path: `${out}-4-full.png` });
await page.click('[data-crk-rx-toggle]');
await page.waitForTimeout(500);
log('back to paint', await state(page));
log('coverage kept', await coverage(page));

// Keyboard: buttons reachable and operable.
await page.focus('[data-crk-rx-toggle]');
await page.keyboard.press('Enter');
await page.waitForTimeout(200);
log('keyboard Enter on toggle', (await state(page)).view);
await page.keyboard.press('Space');
await page.waitForTimeout(200);
log('keyboard Space on toggle', (await state(page)).view);

// Resize: paint must stay where it was.
const covA = await coverage(page);
await page.setViewportSize({ width: 1024, height: 768 });
await page.waitForTimeout(600);
log('1024 coverage (was)', [await coverage(page), covA]);
log('1024 layout', await page.evaluate(() => { const c = document.querySelector('.crk-rx').getBoundingClientRect(); return { w: Math.round(c.width) }; }));
await page.setViewportSize({ width: 800, height: 900 });
await page.waitForTimeout(600);
log('800 coverage', await coverage(page));
await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
await page.screenshot({ path: `${out}-5-800.png` });
await page.setViewportSize({ width: 1440, height: 900 });
await page.waitForTimeout(600);
log('1440 coverage', await coverage(page));

// RESET.
await page.click('[data-crk-rx-reset]');
await page.waitForTimeout(300);
log('after reset', await state(page));
log('coverage after reset', await coverage(page));
log('focus after reset', await page.evaluate(() => document.activeElement && document.activeElement.textContent));
await page.click('[data-crk-rx-reset]', { force: true });
await page.waitForTimeout(200);
log('reset while disabled: events', (await state(page)).events);

log('published to Shopify', await page.evaluate(() => window.__pub.map((p) => p[0] + ':' + p[1].reaction + ':' + p[1].product_handle)));
log('CLS total', await page.evaluate(() => ({ cls: +window.__cls.toFixed(4), shifts: window.__shifts })));
log('errors', errs);
await browser.close();
