// Fallbacks: JS off, canvas unavailable, reduced motion, light mode.
// usage: node t-fallback.mjs <url> <outprefix> [local]
import { open, coverage, state } from './rxlib.mjs';
const [url, out, local] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const L = local === 'local';
const log = (k, v) => console.log(k.padEnd(30), typeof v === 'string' ? v : JSON.stringify(v));

// 1. JavaScript off.
{
  const { browser, page } = await open({ url, width: 390, height: 844, mobile: true, js: false, local: L, jar: SP + 'cj-f1', net: SP + 'net-f1' });
  await page.goto(url, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(800);
  const r = await page.evaluate(() => {
    const card = document.querySelector('.crk-rx');
    const vis = (s) => { const e = card.querySelector(s); return e ? getComputedStyle(e).display !== 'none' : null; };
    const base = card.querySelector('.crk-rx__base');
    return { buttons: vis('[data-crk-rx-js]'), hint: vis('[data-crk-rx-hint]'), status: vis('[data-crk-rx-status]'), details: !!card.querySelector('details.crk-rx__nojs'), baseAlt: base.alt, fullOpacity: getComputedStyle(card.querySelector('.crk-rx__full')).opacity };
  });
  log('no-JS', r);
  await page.evaluate(() => document.querySelector('.crk-rx').scrollIntoView());
  await page.locator('details.crk-rx__nojs > summary').tap();
  await page.waitForTimeout(1500);
  log('no-JS details open', await page.evaluate(() => { const d = document.querySelector('details.crk-rx__nojs'); const i = d.querySelector('img'); return { open: d.open, imgLoaded: i.complete && i.naturalWidth > 0, alt: i.alt }; }));
  await page.evaluate(() => document.querySelector('.crk-rx').scrollIntoView());
  await page.screenshot({ path: `${out}-nojs.png` });
  await browser.close();
}

// 2. Canvas unavailable (getContext returns null): VIEW FULL still works, RESET hidden.
{
  const { browser, page, errs } = await open({ url, local: L, jar: SP + 'cj-f2', net: SP + 'net-f2', init: [() => { HTMLCanvasElement.prototype.getContext = function () { return null; }; }] });
  await page.goto(url, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(1200);
  await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(600);
  const s1 = await state(page);
  log('no-canvas', { mode: s1.mode, hintOpacity: s1.hintOpacity, reset: await page.evaluate(() => getComputedStyle(document.querySelector('[data-crk-rx-reset]')).display) });
  await page.click('[data-crk-rx-toggle]');
  await page.waitForTimeout(500);
  const s2 = await state(page);
  log('no-canvas VIEW FULL', { view: s2.view, fullOpacity: s2.fullOpacity, word: s2.word, events: s2.events });
  log('no-canvas errors', errs.filter((e) => !/Failed to load resource|Failed to fetch|privacy_banner/.test(e)));
  await browser.close();
}

// 3. Reduced motion: the sample stroke lands at once, no transitions.
{
  const { browser, page } = await open({ url, local: L, reduced: true, jar: SP + 'cj-f3', net: SP + 'net-f3' });
  await page.goto(url, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(1200);
  await page.evaluate(() => document.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(250);
  log('reduced motion: coverage at 250ms', await coverage(page));
  log('reduced motion: transitions', await page.evaluate(() => ({ full: getComputedStyle(document.querySelector('.crk-rx__full')).transitionDuration, hint: getComputedStyle(document.querySelector('[data-crk-rx-hint]')).transitionDuration })));
  await browser.close();
}

// 4. Light mode (the site's own toggle stores it in sessionStorage).
{
  const { browser, page } = await open({ url, local: L, jar: SP + 'cj-f4', net: SP + 'net-f4', init: [() => { try { sessionStorage.setItem('crk-theme', 'light'); } catch (e) {} }] });
  await page.goto(url, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(1500);
  await page.evaluate(() => document.querySelector('.crk-rx').scrollIntoView({ block: 'start' }));
  await page.waitForTimeout(1500);
  log('light mode', await page.evaluate(() => document.documentElement.getAttribute('data-crk-theme')));
  await page.screenshot({ path: `${out}-light.png` });
  await browser.close();
}
