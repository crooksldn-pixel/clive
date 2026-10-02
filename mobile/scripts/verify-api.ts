/**
 * Runs the app's own Storefront client against the live store.
 * Not a mock: if this passes, the screens are reading real data.
 *   npm run verify:api
 */
import { categoriesOf, getCatalogue, getProduct } from '../src/lib/catalogue';
import { addLine, createCart, fetchCart, removeLine, setLineQuantity } from '../src/lib/cart-api';
import { hasToken } from '../src/lib/config';
import { formatMoney } from '../src/lib/money';
import { initialSelection, isValueAvailable, resolveVariant } from '../src/lib/variants';

let failed = 0;
const ok = (cond: unknown, label: string, detail = '') => {
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${label}${detail ? '  ' + detail : ''}`);
  if (!cond) failed++;
};

(async () => {
  console.log(`token configured: ${hasToken()}\n--- catalogue`);
  const cards = await getCatalogue();
  ok(cards.length > 0, 'catalogue returns products', `n=${cards.length}`);
  ok(!cards.some((c) => c.productType === 'Sets'), 'no sets in the catalogue');
  ok(cards.every((c) => Number(c.price.amount) > 0), 'every card has a real price');
  console.log('      categories:', categoriesOf(cards).join(' | '));

  console.log('--- product (two options: Colour + Size)');
  const tee = await getProduct('crx-garms-t-shirt');
  ok(tee !== null, 'tee resolves by handle');
  if (tee) {
    ok(tee.options.map((o) => o.name).join() === 'Colour,Size', 'both options named', tee.options.map((o) => o.name).join(' + '));
    const sel = initialSelection(tee);
    ok(Object.keys(sel).length === 0, 'nothing pre-selected');
    ok(resolveVariant(tee, { Colour: 'Black' }) === null, 'half a selection resolves to nothing');
    const firstLive = tee.variants.find((v) => v.availableForSale)!;
    const full = Object.fromEntries(firstLive.selectedOptions.map((o) => [o.name, o.value]));
    ok(resolveVariant(tee, full)?.id === firstLive.id, 'full selection resolves the exact variant', JSON.stringify(full));
    ok(isValueAvailable(tee, {}, 'Size', firstLive.selectedOptions.find((o) => o.name === 'Size')!.value), 'a stocked size reads available');
    ok(tee.measurements === null || Array.isArray(tee.measurements), 'measurements parse (null without a token)', `${tee.measurements ? tee.measurements.length + ' rows' : 'null'}`);
  }
  ok((await getProduct('this-handle-does-not-exist')) === null, 'missing handle returns null, not a throw');

  console.log('--- cart lifecycle');
  const sweats = await getProduct('v2-baggies');
  const live = sweats?.variants.filter((v) => v.availableForSale) ?? [];
  ok(live.length >= 1, 'found a buyable variant', live.map((v) => v.selectedOptions[0].value).join(','));
  let cart = await createCart(live[0].id, 1);
  ok(cart.totalQuantity === 1, 'create: 1 item');
  ok(/^https:\/\/crooksldn\.com\/cart\/c\//.test(cart.checkoutUrl), 'checkoutUrl is the store\'s own checkout', cart.checkoutUrl.slice(0, 48) + '…');
  const target = live[1] ?? live[0];
  cart = await addLine(cart.id, target.id, 1);
  ok(cart.totalQuantity === 2, 'add: 2 items');
  const line = cart.lines[0];
  cart = await setLineQuantity(cart.id, line.id, 3);
  ok(cart.lines.find((l) => l.id === line.id)?.quantity === 3, 'update: quantity 3');
  cart = await removeLine(cart.id, line.id);
  ok(!cart.lines.some((l) => l.id === line.id), 'remove: line gone');
  const reread = await fetchCart(cart.id);
  ok(reread?.totalQuantity === cart.totalQuantity, 're-read matches', `qty=${reread?.totalQuantity}`);
  ok(formatMoney(cart.cost.totalAmount).startsWith('£'), 'totals formatted in GBP', formatMoney(cart.cost.totalAmount));

  console.log('--- money');
  ok(formatMoney({ amount: '60.0', currencyCode: 'GBP' }) === '£60', '£60 (no pence on whole amounts)');
  ok(formatMoney({ amount: '12.5', currencyCode: 'GBP' }) === '£12.50', '£12.50');
  ok(formatMoney(null) === '', 'null money is empty, not a crash');

  console.log(`\n${failed ? `${failed} FAILED` : 'ALL PASSED'}`);
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.error('CRASH', e); process.exit(2); });
