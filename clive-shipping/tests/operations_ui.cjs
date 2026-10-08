const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
let source = [...fs.readFileSync(process.argv[2], 'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
source = source.slice(0, source.lastIndexOf('route();'));
let rendered = '', phase = 'review', requests = [], fields = {};
const handlers = {}, storage = new Map();
const host = {setAttribute() {}, replaceChildren() {}};
const document = {hidden:false, title:'',
  getElementById: id => fields[id] || host,
  querySelectorAll: () => [],
  createElement: () => ({set innerHTML(v) {rendered=v;}, childNodes:[]}),
  addEventListener: (name,fn) => {(handlers[name] ||= []).push(fn);}};
const location = {pathname:'/admin',search:''};
const history = {pushState:(_,__,url) => {location.search=new URL(url,'http://localhost').search;}, replaceState:(_,__,url)=>{location.search=new URL(url,'http://localhost').search;}};
const window = {addEventListener() {},confirm:()=>false};window.top=window.self=window;
const context = vm.createContext({document,window,location,history,data,URLSearchParams,URL,Intl,structuredClone,
 console,setTimeout,clearTimeout,setInterval(){},crypto:require('node:crypto').webcrypto,
 sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
 fetch:async(url,options)=>{
   requests.push({url,method:options.method,body:options.body ? JSON.parse(options.body) : null});
   let result;
   if(url.endsWith('/batches/preview')) result=data.review;
   else if(url.endsWith('/confirm')) {assert.equal(JSON.parse(options.body).confirm,true);phase='queued';result=data.queued;}
   else if(url.includes('/batches/')) result=phase==='queued'?data.complete:data.review;
   else if(url.includes('/inbox?')) result=structuredClone(url.includes('stage=bought')?data.bought_inbox:url.includes('stage=printed')?data.printed_inbox:data.inbox);
   else if(url.endsWith('/customs')) {result=structuredClone(data.detail);result.products[0].hs_code_value='01012100';}
   else throw new Error('Unexpected request '+url);
   return {ok:true,json:async()=>result};
 }});
vm.runInContext(source,context);
const execute = code => vm.runInContext(code,context);
const button = {setAttribute(){},removeAttribute(){},dataset:{line:'0'}};
context.button=button;
(async()=>{
  location.search='?stage=ready';
  execute('state.inbox=data.inbox; renderInbox();');
  // The list reads like Shopify's: when ordered (store time zone), who, where, what it costs.
  assert.ok(rendered.includes('Purchased') && rendered.includes('Customer') && rendered.includes('>Label<'));
  assert.ok(!rendered.includes('>Package<') && !rendered.includes('heading="1 selected"'));
  assert.ok(rendered.includes(data.inbox.rows[0].customer));
  assert.equal(execute('purchasedText(null, "Europe/London")'), '—');
  const now = new Date();
  assert.ok(execute(`purchasedText("${now.toISOString()}", "Europe/London")`).startsWith('Today at '));
  assert.ok(execute(`purchasedText("${new Date(now - 86400000).toISOString()}", "Europe/London")`).startsWith('Yesterday at '));
  assert.equal(execute('purchasedText("2025-03-07T12:00:00Z", "Europe/London")'), '7 Mar 2025');
  // Nothing selected: the bar is already there (same height), offering the server's "all ready".
  assert.ok(rendered.includes('id="bulk-bar"') && rendered.includes('id="pick-all"') && rendered.includes('2 ready'));
  // One box ticked: the bar changes in place; the page isn't redrawn.
  const drawn = rendered;
  for (const fn of handlers.change) fn({target:{dataset:{select:data.inbox.rows[0].id},checked:true,id:''}});
  assert.equal(rendered, drawn);  // no page render happened
  assert.equal(execute('state.selected.size'),1);
  // "Select all ready" asks the server again, then selects what may be bought now.
  const asked = requests.length;
  await execute('ACTIONS["select-stage"](button)');
  assert.ok(requests.slice(asked).some(r => r.url.includes('/inbox?stage=ready')));
  assert.equal(execute('state.selected.size'),2);
  assert.ok(rendered.includes('Buy labels — review'));
  assert.ok(!rendered.includes('Print labels — review')); // never Buy & Print together
  assert.ok(rendered.includes('aria-current="page"') && rendered.includes('Ready to ship (2)'));
  await execute('ACTIONS["bulk-buy"](button)');
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(document.title.includes('Review selected labels'));
  const reviewRequest = requests.find(r => r.url.endsWith('/batches/preview'));
  assert.deepEqual(reviewRequest.body.shipment_ids,data.review.children.map(c=>c.shipment_id));
  assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).length,0);
  assert.ok(rendered.includes('No action has run yet'));
  await execute('ACTIONS["confirm-batch"](button)');
  assert.ok(document.title.includes('Bulk operation progress'));
  await execute('pollBatch()');
  assert.ok(rendered.includes('2 purchased'));
  assert.equal(execute('state.batch.state'),'complete');
  location.search='?stage=bought';
  execute('state.selected.clear(); state.inbox=data.bought_inbox; renderInbox();');
  assert.equal(execute('visibleInboxRows().length'),1);  // the one never sent to the printer
  assert.ok(rendered.includes('Not printed') && rendered.includes('Select all unprinted'));
  await execute('ACTIONS["select-stage"](button)');
  assert.equal(execute('state.selected.size'),1);
  assert.ok(rendered.includes('Print labels — review') && !rendered.includes('Buy labels — review'));
  location.search='?stage=printed';
  execute('state.selected.clear(); state.inbox=data.printed_inbox; renderInbox();');
  assert.equal(execute('visibleInboxRows().length'),1);
  assert.ok(rendered.includes('Printed'));
  assert.ok(!rendered.includes('type="checkbox"'));  // Printed: no bulk reprint, only explicit Reprint
  assert.ok(!rendered.includes('select-stage'));
  execute('state.shipment=data.sent; renderShipment();');
  assert.ok(rendered.includes('Reprint label'));
  assert.ok(!rendered.includes('variant="primary" data-action="physical-print"'));
  const before=requests.length;
  await execute('ACTIONS["physical-reprint"](button)');
  assert.equal(requests.length,before); // Intentional copy requires confirmation.
  location.search='?shipment='+data.detail.id;
  fields={'customs-0-hs':{value:'01012100'},'customs-0-origin':{value:'CN'},'customs-0-desc':{value:'Cotton tee'}};
  execute('state.shipment=data.detail; renderShipment();');
  assert.ok(rendered.includes('Save product customs'));
  await execute('ACTIONS["edit-customs"](button)');
  assert.equal(requests.at(-1).body.hs_code,'01012100');
  assert.equal(requests.at(-1).body.subject,data.detail.products[0].subject);
  assert.equal(execute('state.shipment.products[0].hs_code_value'),'01012100');
  // A search lives in the URL, so a reload or the way back to the list keeps it.
  location.search='?stage=ready';
  execute('state.inbox=data.inbox; renderInbox();');
  for (const fn of handlers.input) fn({target:{id:'search',value:'2145'}});
  await new Promise(resolve=>setTimeout(resolve,400));
  assert.equal(new URLSearchParams(location.search).get('q'),'2145');
  assert.ok(requests.at(-1).url.includes('q=2145'));
  location.search='?shipment='+data.detail.id;
  execute('ACTIONS["go-inbox"]()');
  assert.equal(new URLSearchParams(location.search).get('q'),'2145');
  assert.equal(new URLSearchParams(location.search).get('stage'),'ready');
  await new Promise(resolve=>setTimeout(resolve,50));
  console.log('Lifecycle tabs, bulk selection/review/progress, print status and inline customs interactions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
