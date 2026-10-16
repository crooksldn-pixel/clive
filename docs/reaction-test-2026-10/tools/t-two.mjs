import { open, frameBox } from './rxlib.mjs';
const [url, out] = process.argv.slice(2);
const SP = new URL('.', import.meta.url).pathname;
const { browser, page, errs } = await open({ url, jar: SP + 'cj-t', net: SP + 'net-t' });
await page.goto(url, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(1500);
const cards = await page.$$('[data-crk-reaction]');
console.log('cards', cards.length);
for (let k = 0; k < cards.length; k++) {
  await cards[k].evaluate((el) => el.querySelector('.crk-rx__stage').scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(1800);
  const fb = await cards[k].evaluate((el) => { const r = el.querySelector('[data-crk-rx-frame]').getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; });
  await page.mouse.move(fb.x + fb.w * 0.2, fb.y + fb.h * 0.45); await page.mouse.down();
  await page.mouse.move(fb.x + fb.w * 0.8, fb.y + fb.h * 0.5, { steps: 20 }); await page.mouse.up();
  await page.waitForTimeout(300);
  console.log('card', k, await cards[k].evaluate((el) => ({ teaser: el.getAttribute('data-crk-rx-teaser'), word: el.querySelector('[data-crk-rx-word]').textContent, accent: getComputedStyle(el).getPropertyValue('--crk-rx-accent'), mt: getComputedStyle(el).marginTop, cols: getComputedStyle(el).gridTemplateColumns })));
  const box = await cards[k].boundingBox();
  await page.screenshot({ path: `${out}-${k}.png`, clip: { x: box.x - 8, y: Math.max(0, box.y - 8), width: box.width + 16, height: Math.min(box.height + 16, 900) } });
}
console.log('events', await page.evaluate(() => window.__rx));
console.log('errors', errs.filter((e) => !/Failed to load resource|Failed to fetch|privacy_banner/.test(e)));
await browser.close();
