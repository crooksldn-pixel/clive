// Execute the actual browser script with a minimal DOM and mocked, read-only HTTP.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const [before, after] = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const scripts = [...fs.readFileSync(process.argv[2], 'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)];
let source = scripts.at(-1)[1];
source = source.slice(0, source.lastIndexOf('route();'));
let rendered = '', reads = 0;
const handlers = {};
const host = { setAttribute() {}, replaceChildren() {} };
const document = {
  hidden: false, title: '',
  getElementById: () => host,
  createElement: () => ({set innerHTML(value) { rendered = value; }, childNodes: []}),
  addEventListener: (name, callback) => { (handlers[name] ||= []).push(callback); },
};
const window = { addEventListener() {} }; window.top = window.self = window;
const context = vm.createContext({document, window,
  location: {pathname: '/admin', search: `?shipment=${before.id}`},
  URLSearchParams, Intl, console, structuredClone, sessionStorage: {getItem: () => null}, setInterval() {}, setTimeout, clearTimeout,
  fetch: async (url, options) => {
    reads++;
    assert.equal(options.method || 'GET', 'GET');
    assert.ok(url.endsWith(`/shipments/${before.id}`));
    return {ok: true, status: 200, json: async () => after};
  }, before, after});
vm.runInContext(source, context);
(async () => {
  vm.runInContext('state.shipment = before; renderShipment();', context);
  assert.ok(rendered.includes('temporarily unavailable'));
  assert.ok(rendered.includes('CLIVE will retry automatically'));
  assert.ok(rendered.includes('Parcel2Go'));
  await vm.runInContext('refreshQuoteRecovery()', context);
  assert.equal(reads, 1);
  assert.ok(!rendered.includes('temporarily unavailable'));
  assert.ok(rendered.includes('£3.01'));
  assert.equal(vm.runInContext('state.shipment.shipping.recommended.provider', context), 'Easyship');
  for (const guard of ['state.busy = true', 'state.preview = {}', 'quoteFormDirty = true', 'state.shipment.label = {}']) {
    vm.runInContext('state.shipment = structuredClone(before); state.busy = false; state.preview = null; quoteFormDirty = false;', context);
    vm.runInContext(guard, context);
    await vm.runInContext('refreshQuoteRecovery()', context);
    assert.equal(reads, 1);
  }
  console.log('Quote UI recovery, rendering and safety guards passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
