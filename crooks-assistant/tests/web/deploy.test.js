/* Deploy now on the Builds screen (web/deploy.js), run under Node with the page's own code (DEC-072).
 *
 * What is proved:
 * - the offer: its title, how many changes and that acceptance passed on this exact version, the pull
 *   requests' own titles, and the hold; dry run said on the button and under it; when his hold cannot
 *   deploy it, the reason instead of a button;
 * - the hold: only a press held for the whole 0.9 s does anything; letting go early, or a pointer that
 *   leaves, does nothing; Space or Enter held does the same as a finger;
 * - his hold, end to end against stand-ins for CLIVE and the passkey prompt: the challenge for exactly
 *   that version, his passkey, the approval sent with the ticket; then the progress; a cancelled prompt
 *   or a refusal said on the card, nothing deployed, the button back;
 * - the progress: six stages, each dot's class from the fixed table (lit, now, stop, dim), the line as
 *   CLIVE wrote it, and while CLIVE restarts, saying so;
 * - kept: the page asks /whoami itself, hands its token to CLIVE, and asks again while the journal
 *   catches up; a device that is not the owner's through Tailscale keeps nothing;
 * - the card goes straight under the Builds heading, before the Research section;
 * - every word from CLIVE lands as text, even a hostile one, and no attribute carries it.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const shim = require('./dom-shim.js');

globalThis.document = shim.document;
require(path.join(__dirname, '..', '..', 'web', 'builds.js'));
const D = require(path.join(__dirname, '..', '..', 'web', 'deploy.js'));

const HOSTILE = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
const SHA = '1'.repeat(32) + 'a1b2c3d4';

function walk(node, fn) { fn(node); for (const c of node.childNodes || []) if (c.nodeType === 1) walk(c, fn); }
function all(node, cls) { const out = []; walk(node, (n) => { if (n.classList && n.classList.contains(cls)) out.push(n); }); return out; }
function attributesOf(node) { const out = []; walk(node, (n) => { for (const v of Object.values(n.attributes)) out.push(v); }); return out; }

function offer(over) {
  return Object.assign({
    sha: SHA, short: SHA.slice(0, 8), title: 'Deploy now on the Builds screen', count: 3,
    changes: ['Deploy now on the Builds screen', 'The card George holds is always on top', 'Seven fixes from the review'],
    more: 0, acceptance: { green: true, runs: [77] },
    hold: { can: true, why_not: '', note: '', dry_run: false, label: 'Hold to deploy' },
    takes: 'Deploying takes a few minutes: checks, the install, a restart, then a health check.',
  }, over || {});
}

function progress(over) {
  return Object.assign({
    sha: SHA, short: SHA.slice(0, 8), approval: 'a'.repeat(32), title: 'Deploy now on the Builds screen',
    given_at: '2026-10-08T01:00:00Z', started_at: '2026-10-08T01:00:10Z', end: '', final: false, keep_check: false,
    kept_at: '', line: 'Installing the new build…',
    stages: [['started', 'Started', 'lit'], ['checks', 'Checks', 'lit'], ['installing', 'Installing', 'now'],
      ['health', 'Health', 'dim'], ['done', 'Done', 'dim'], ['kept', 'Kept', 'dim']]
      .map(([key, label, state]) => ({ key, label, state, at: '' })),
  }, over || {});
}

test('the offer: title, changes, acceptance, and the hold', () => {
  const node = D.offerNode(offer(), {});
  const said = node.allText();
  assert.equal(node.querySelector('.dn-eyebrow').allText(), 'Ready to go live');
  assert.equal(node.querySelector('.dn-title').allText(), 'Deploy now on the Builds screen');
  assert.match(said, /3 changes since what’s live · acceptance passed on this exact version/);
  assert.deepEqual(all(node, 'dn-change').map((n) => n.allText()), offer().changes);
  const hold = node.querySelector('.dn-hold');
  assert.equal(hold.allText(), 'Hold to deploy');
  assert.equal(hold.type, 'button');
  assert.match(said, /Your passkey confirms it\. Deploying takes a few minutes/);
  assert.doesNotMatch(said, /dry run/i);
  // The version is in the technical details, never on the card's face.
  assert.equal(node.querySelector('.dn-title').allText().includes(SHA.slice(0, 8)), false);
  assert.match(node.querySelector('.dn-tech').allText(), /a1b2c3d4|11111111/);
});

test('more changes than shown, dry run, and a hold that cannot deploy', () => {
  const more = D.offerNode(offer({ more: 4 }), {});
  assert.equal(all(more, 'dn-change').pop().allText(), 'and 4 more');
  const dry = D.offerNode(offer({ hold: { can: true, dry_run: true, label: 'Hold to try it (dry run)', note: '' } }), {});
  assert.equal(dry.querySelector('.dn-hold').allText(), 'Hold to try it (dry run)');
  assert.match(dry.allText(), /Dry run is on: the release service checks everything and says what it would do\. Nothing changes\./);
  const cannot = D.offerNode(offer({ hold: { can: false, why_not: 'The release service is switched off (CLIVE_RELEASE_ENABLED), so this one is deployed by hand.' } }), {});
  assert.equal(cannot.querySelector('.dn-hold'), null);
  assert.equal(cannot.querySelector('.dn-why').allText(), 'The release service is switched off (CLIVE_RELEASE_ENABLED), so this one is deployed by hand.');
});

test('the hold: only a press held for the whole time does anything', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let held = 0;
  const button = D.holdButton('Hold to deploy', () => { held += 1; });
  button.dispatch('pointerdown');
  assert.equal(button.allText(), 'Keep holding…');
  t.mock.timers.tick(D.HOLD_MS - 100);
  button.dispatch('pointerup');
  t.mock.timers.tick(1000);
  assert.equal(held, 0, 'let go early: nothing');
  assert.equal(button.allText(), 'Hold to deploy');
  button.dispatch('pointerdown');
  t.mock.timers.tick(300);
  button.dispatch('pointerleave');
  t.mock.timers.tick(1000);
  assert.equal(held, 0, 'the finger slid off: nothing');
  button.dispatch('pointerdown');
  t.mock.timers.tick(D.HOLD_MS);
  assert.equal(held, 1, 'held the whole time: once');
  assert.equal(button.disabled, true);
  const keys = D.holdButton('Hold to deploy', () => { held += 1; });
  keys.dispatch('keydown', { key: ' ', repeat: false });
  keys.dispatch('keydown', { key: ' ', repeat: true });
  t.mock.timers.tick(D.HOLD_MS);
  assert.equal(held, 2, 'Space held does what a finger does');
});

test('the progress: six stages from the fixed table, the line as CLIVE wrote it', () => {
  const node = D.progressNode(progress(), { now: new Date('2026-10-08T01:02:10Z') });
  assert.equal(node.querySelector('.dn-eyebrow').allText(), 'Deploying');
  assert.deepEqual(all(node, 'dn-stage').map((n) => n.allText()), ['Started', 'Checks', 'Installing', 'Health', 'Done', 'Kept']);
  assert.deepEqual(all(node, 'dn-stage').map((n) => n.className), ['dn-stage is-lit', 'dn-stage is-lit', 'dn-stage is-now',
    'dn-stage is-dim', 'dn-stage is-dim', 'dn-stage is-dim']);
  assert.equal(node.querySelector('.dn-line').allText(), 'Installing the new build…');
  assert.equal(node.querySelector('.dn-line').getAttribute('role'), 'status');
  assert.equal(node.querySelector('.dn-when').allText(), 'Started 2 min ago');
  const restarting = D.progressNode(progress(), { restarting: true });
  assert.equal(restarting.querySelector('.dn-line').allText(), 'CLIVE is restarting onto the new build…');
  const back = D.progressNode(progress({ end: 'rolled_back', final: true, line: 'Rolled back: /health after is not well. Production is back on the version it ran before.',
    stages: progress().stages.map((s, i) => Object.assign({}, s, { state: i < 3 ? 'lit' : i === 3 ? 'stop' : 'dim' })) }), {});
  assert.equal(back.querySelector('.dn-eyebrow').allText(), 'Rolled back');
  assert.equal(back.className, 'dn-card is-progress is-rolled_back');
  assert.equal(all(back, 'dn-stage')[3].className, 'dn-stage is-stop');
  const dots = [];
  walk(back, (n) => { const cls = n.getAttribute('class') || ''; if (cls.startsWith('dn-n ')) dots.push(cls); });
  assert.deepEqual(dots, ['dn-n is-lit', 'dn-n is-lit', 'dn-n is-lit', 'dn-n is-stop is-ring', 'dn-n is-stop is-core',
    'dn-n is-dim', 'dn-n is-dim'], 'a ring and its core where it stopped');
  const kept = D.progressNode(progress({ end: 'done', final: true, kept_at: '2026-10-08T01:03:00Z', line: 'Deployed and kept: your phone got through on the new build.' }),
    { now: new Date('2026-10-08T01:03:00Z') });
  assert.equal(kept.querySelector('.dn-eyebrow').allText(), 'Deployed and kept');
  // Review note 3: an approval that lapsed while the version was deployed another way is not "Not deployed".
  const lapsed = D.progressNode(progress({ end: 'lapsed', final: true, started_at: '', line: 'Your approval has expired. The release service’s record shows this version deployed at 01:20 UTC, not on this approval.' }), {});
  assert.equal(lapsed.querySelector('.dn-eyebrow').allText(), 'Approval expired');
  assert.equal(lapsed.className, 'dn-card is-progress is-lapsed');
  assert.match(lapsed.querySelector('.dn-line').allText(), /deployed at 01:20 UTC, not on this approval\.$/);
  const expired = D.progressNode(progress({ end: 'expired', final: true, line: 'Nothing was deployed.' }), {});
  assert.equal(expired.querySelector('.dn-eyebrow').allText(), 'Not deployed');
  const odd = D.progressNode(progress({ stages: [{ key: 'x', label: 'X', state: 'exploded' }] }), {});
  assert.equal(all(odd, 'dn-stage')[0].className, 'dn-stage is-dim', 'a state not in the table is drawn dim');
});

function world(answers) {
  const asked = [];
  globalThis.fetch = async (url, init) => {
    const body = init && init.body ? JSON.parse(init.body) : undefined;
    asked.push([url, body]);
    const next = answers[url];
    const answer = typeof next === 'function' ? next(body) : next;
    if (answer instanceof Error) throw answer;
    const { status = 200, data = {} } = answer || {};
    return { ok: status < 400, status, json: async () => data };
  };
  return asked;
}

function passkeyPrompt(result) {
  const seen = [];
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { credentials: { get: async (options) => {
    seen.push(options);
    if (result instanceof Error) throw result;
    const bytes = (s) => new TextEncoder().encode(s).buffer;
    return { id: 'cred', rawId: bytes('cred-id'), type: 'public-key',
      response: { clientDataJSON: bytes('{}'), authenticatorData: bytes('auth'), signature: bytes('sig'), userHandle: null } };
  } } } });
  return seen;
}

function ui() {
  const button = shim.document.createElement('button');
  const words = shim.document.createElement('span');
  const said = shim.document.createElement('p');
  button.disabled = true;
  return { button, words, said, label: 'Hold to deploy' };
}

test('his hold: the challenge for exactly that version, his passkey, the approval with its ticket', async () => {
  const asked = world({
    '/release/deploy/challenge': { data: { ok: true, ticket: 'T'.repeat(43), expires_at: '2026-10-08T01:10:00Z',
      publicKey: { challenge: 'AAAA', rpId: 'clive.example.ts.net', allowCredentials: [{ type: 'public-key', id: 'AAAA' }] } } },
    '/release/deploy': { data: { ok: true, approved: { sha: SHA, approval: 'a'.repeat(32) }, progress: progress({ line: 'Approved. Starting the release service…' }) } },
    '/release/deploy?progress=1': { data: { ok: true, progress: progress(), offer: null, release: {} } },
  });
  const seen = passkeyPrompt();
  const done = await D.deploy(offer(), ui());
  assert.ok(done && done.approved);
  assert.deepEqual(asked[0], ['/release/deploy/challenge', { sha: SHA }]);
  assert.equal(seen.length, 1);
  assert.ok(seen[0].publicKey.challenge instanceof Uint8Array, 'the challenge handed to the prompt as bytes');
  assert.ok(seen[0].publicKey.allowCredentials[0].id instanceof Uint8Array);
  const [url, body] = asked[1];
  assert.equal(url, '/release/deploy');
  assert.equal(body.sha, SHA);
  assert.equal(body.ticket, 'T'.repeat(43));
  assert.equal(body.approval.rawId, Buffer.from('cred-id').toString('base64url'));
  assert.equal(D.state().payload.progress.line, 'Approved. Starting the release service…');
  assert.equal(D.state().payload.offer, null);
  if (D.state().timer) { clearTimeout(D.state().timer); D.state().timer = null; }
});

test('a cancelled prompt or a refusal: said on the card, nothing deployed, the button back', async () => {
  world({ '/release/deploy/challenge': { data: { publicKey: { challenge: 'AAAA' }, ticket: 'T'.repeat(43) } } });
  const cancelled = Object.assign(new Error('no'), { name: 'NotAllowedError' });
  passkeyPrompt(cancelled);
  let u = ui();
  await D.deploy(offer(), u);
  assert.equal(u.said.allText(), 'Cancelled, or the passkey prompt timed out. Nothing was deployed.');
  assert.equal(u.button.disabled, false);
  assert.equal(u.words.allText(), 'Hold to deploy');
  world({ '/release/deploy/challenge': { status: 409, data: { ok: false, code: 'cannot_deploy', detail: 'The release service is switched off (CLIVE_RELEASE_ENABLED), so this one is deployed by hand.' } },
    '/release/deploy': { data: {} } });
  u = ui();
  await D.deploy(offer(), u);
  assert.equal(u.said.allText(), 'The release service is switched off (CLIVE_RELEASE_ENABLED), so this one is deployed by hand.');
  world({ '/release/deploy/challenge': { data: { publicKey: { challenge: 'AAAA' }, ticket: 'T'.repeat(43) } },
    '/release/deploy': { status: 409, data: { detail: 'That approval took too long and expired. Nothing was deployed. Hold the card again.' } } });
  passkeyPrompt();
  u = ui();
  await D.deploy(offer(), u);
  assert.equal(u.said.allText(), 'That approval took too long and expired. Nothing was deployed. Hold the card again.');
  assert.equal(u.button.disabled, false);
});

test('kept: the page asks /whoami itself and hands its token over, again while the journal catches up', async (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  let tries = 0;
  const asked = world({
    '/whoami': { data: { check: 'ab12cd34', owner: true, through: 'tailscale' } },
    '/release/kept': () => (++tries < 2 ? { status: 409, data: { code: 'not_in_journal', detail: 'Your phone’s check isn’t in CLIVE’s journal yet. Not kept yet.' } }
      : { data: { kept: { sha: SHA }, progress: progress({ end: 'done', final: true, kept_at: '2026-10-08T01:03:00Z', line: 'Deployed and kept: your phone got through on the new build.' }) } }),
  });
  const keeping = D.keep(progress({ end: 'done', keep_check: true }));
  for (let i = 0; i < 20 && tries < 2; i += 1) { await new Promise((r) => setImmediate(r)); t.mock.timers.tick(2000); }
  await keeping;
  assert.deepEqual(asked.map(([url]) => url), ['/whoami', '/release/kept', '/release/kept']);
  assert.deepEqual(asked[1][1], { sha: SHA, check: 'ab12cd34' });
  assert.equal(D.state().payload.progress.line, 'Deployed and kept: your phone got through on the new build.');
});

test('a device that is not the owner’s through Tailscale keeps nothing', async () => {
  const asked = world({ '/whoami': { data: { check: 'ab12cd34', owner: false, through: 'this_host', owner_refusal: 'not_authorised_local' } } });
  await D.keep(progress({ end: 'done', keep_check: true }));
  assert.deepEqual(asked.map(([url]) => url), ['/whoami']);
  assert.match(D.state().keepSaid, /didn't get through as you \(not_authorised_local\)/);
});

test('the card goes straight under the Builds heading, before the Research section', () => {
  world({ '/release/deploy': { data: { offer: offer(), progress: null, release: {} } } });
  const host = shim.document.createElement('div');
  const hello = shim.document.createElement('div');
  hello.className = 'bd-hello';
  const line = shim.document.createElement('div');
  line.className = 'bd-release';
  hello.appendChild(line);
  const research = shim.document.createElement('section');
  research.className = 'rs';
  host.appendChild(hello);
  host.appendChild(research);
  D.state().payload = { offer: offer(), progress: null };
  D.state().at = Date.now();
  D.state().node = null;
  const node = D.place(host);
  assert.deepEqual(host.children.map((n) => n.className), ['bd-hello', 'dn', 'rs']);
  assert.equal(node.querySelector('.dn-title').allText(), 'Deploy now on the Builds screen');
  assert.equal(line.hidden, true, 'the release service’s older line steps aside while the card says more');
  D.state().payload = { offer: null, progress: null };
  D.state().node = null;
  host.removeChild(host.children[1]);
  D.place(host);
  assert.equal(line.hidden, false, 'and comes back when there is no card');
});

test('every word from CLIVE lands as text, and no attribute carries it', () => {
  const node = D.draw({ offer: offer({ title: HOSTILE, changes: [HOSTILE], short: HOSTILE, hold: { can: false, why_not: HOSTILE } }),
    progress: progress({ title: HOSTILE, line: HOSTILE, short: HOSTILE, stages: [{ key: HOSTILE, label: HOSTILE, state: HOSTILE }] }),
    problems: [HOSTILE] }, {});
  assert.ok(node.allText().includes(HOSTILE));
  for (const value of attributesOf(node)) assert.equal(value.includes('<'), false, value);
  walk(node, (n) => { assert.notEqual(n.tagName, 'SCRIPT'); assert.notEqual(n.tagName, 'IMG'); });
});
