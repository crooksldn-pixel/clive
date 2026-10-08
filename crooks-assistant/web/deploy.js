/* Deploy now, on the Builds screen (DEC-072; the owner's rulings 6, 7 and 8 of 8 October 2026).
 *
 * George's words (8 Oct): "i want to say yes to deploy - but, once deploy should be instant, not deploy
 * and then the deploy service runs and takes hours. deploy as in, implement this now".
 *
 * Drawn inside the Builds screen, straight under its heading (web/builds.js places it), from GET
 * /release/deploy (app/routes/release.py), as it comes:
 *   - the offer: the version waiting to go live, only when the trunk's head is ahead of what runs and
 *     GitHub acceptance passed on exactly that version: its title, the pull requests since what is live
 *     in their own titles, and the hold. Holding the button (a press of 0.9 s) asks for his passkey for
 *     exactly that version (POST /release/deploy/challenge, then POST /release/deploy). When his hold
 *     cannot deploy it now, the card says why instead of offering it. Dry run is said on the button.
 *   - the progress: the deploy his approval started, from the release service's own status: a road of
 *     dots (Started, Checks, Installing, Health, Done, Kept), lit as far as it has gone, the stage it is
 *     at in blue, red where it stopped, and one line saying where it is or how it ended and why. Asked
 *     every three seconds while it runs (?progress=1: this server's files only, never GitHub); while
 *     CLIVE restarts onto the new build the page says so and keeps asking.
 *   - kept: once the release service says done and this CLIVE is the new build, the page asks /whoami
 *     itself and hands its token to POST /release/kept, which keeps the deploy once that line is in
 *     CLIVE's journal (DEPLOY_LINUX.md). On any owner page of CLIVE, opened or not (watch()).
 *
 * Every word from CLIVE lands through textContent; no attribute is built from what CLIVE sent (only this
 * file's class names). No dependency on the rest of the page beyond window.CliveBuilds (time in words,
 * opening the screen), so it runs under Node against tests/web/dom-shim.js (tests/web/deploy.test.js).
 */
(function (root, factory) {
  const api = factory(root);
  root.CliveDeploy = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const HOLD_MS = 900;
  const POLL_MS = 3000;
  const KEEP_TRIES = 8;
  const DOT = { lit: 'is-lit', now: 'is-now', stop: 'is-stop', dim: 'is-dim' };
  const WATCHING = 'clive.deploy.watching';

  const doc = () => (typeof document !== 'undefined' ? document : globalThis.document);
  const text = (v) => (v === null || v === undefined ? '' : String(v));
  const list = (v) => (Array.isArray(v) ? v : []);
  const ago = (iso, now) => (root.CliveBuilds && typeof root.CliveBuilds.ago === 'function' ? root.CliveBuilds.ago(iso, now) : '');

  function el(tag, cls, said) {
    const node = doc().createElement(tag);
    if (cls) node.className = cls;
    if (said !== undefined && said !== null && said !== '') node.textContent = text(said);
    return node;
  }
  function svg(tag, attrs) {
    const node = doc().createElementNS(NS, tag);
    for (const k of Object.keys(attrs || {})) node.setAttribute(k, String(attrs[k]));
    return node;
  }
  function add(parent, ...kids) {
    for (const kid of kids) if (kid) parent.appendChild(kid);
    return parent;
  }

  // ---------------------------------------------------------------- the hold

  /* A button held for HOLD_MS does its one thing: a finger, a mouse, or Space or Enter held down. Let go
   * early and nothing happens. The fill shows how far the hold has gone. */
  function holdButton(label, onHeld) {
    const button = el('button', 'dn-hold');
    button.type = 'button';
    const fill = el('span', 'dn-fill');
    const words = el('span', 'dn-words', label);
    add(button, fill, words);
    let timer = null;
    const start = (event) => {
      if (event && event.preventDefault) event.preventDefault();
      if (button.disabled || timer !== null) return;
      button.classList.add('is-holding');
      words.textContent = 'Keep holding…';
      timer = setTimeout(() => {
        timer = null;
        button.classList.remove('is-holding');
        button.disabled = true;
        words.textContent = 'Asking for your passkey…';
        onHeld(button, words);
      }, HOLD_MS);
    };
    const stop = () => {
      if (timer === null) return;
      clearTimeout(timer);
      timer = null;
      button.classList.remove('is-holding');
      words.textContent = label;
    };
    button.addEventListener('pointerdown', start);
    for (const kind of ['pointerup', 'pointerleave', 'pointercancel']) button.addEventListener(kind, stop);
    button.addEventListener('contextmenu', (event) => { if (event && event.preventDefault) event.preventDefault(); });
    button.addEventListener('keydown', (event) => {
      if (event && (event.key === ' ' || event.key === 'Enter') && !event.repeat) start(event);
    });
    button.addEventListener('keyup', (event) => { if (event && (event.key === ' ' || event.key === 'Enter')) stop(); });
    return button;
  }

  // ---------------------------------------------------------------- the offer

  function offerNode(offer, on) {
    const o = on || {};
    const card = el('section', 'dn-card is-offer');
    card.setAttribute('aria-label', 'Deploy now');
    add(card, el('p', 'dn-eyebrow', 'Ready to go live'), el('h2', 'dn-title', offer.title));
    const count = Number(offer.count) || list(offer.changes).length;
    add(card, el('p', 'dn-meta', `${count} change${count === 1 ? '' : 's'} since what’s live · acceptance passed on this exact version`));
    const changes = list(offer.changes).map(text).filter(Boolean);
    if (changes.length) {
      const ul = el('ul', 'dn-changes');
      for (const title of changes) ul.appendChild(el('li', 'dn-change', title));
      if (Number(offer.more) > 0) ul.appendChild(el('li', 'dn-change is-more', `and ${Number(offer.more)} more`));
      card.appendChild(ul);
    }
    const hold = offer.hold && typeof offer.hold === 'object' ? offer.hold : {};
    if (hold.can) {
      const said = el('p', 'dn-said');
      said.setAttribute('role', 'status');
      const button = holdButton(text(hold.label) || 'Hold to deploy', (btn, words) => {
        if (typeof o.deploy === 'function') o.deploy(offer, { button: btn, words, said, label: text(hold.label) || 'Hold to deploy' });
      });
      add(card, button, said);
      if (hold.dry_run) add(card, el('p', 'dn-note', 'Dry run is on: the release service checks everything and says what it would do. Nothing changes.'));
      if (text(hold.note)) add(card, el('p', 'dn-note', hold.note));
      add(card, el('p', 'dn-note', `Your passkey confirms it. ${text(offer.takes)}`.trim()));
    } else {
      add(card, el('p', 'dn-why', hold.why_not || 'This one can’t be deployed from here.'));
    }
    card.appendChild(techNode([['Version', offer.short, true],
      ['Acceptance runs', list(offer.acceptance && offer.acceptance.runs).map(text).join(', '), true]]));
    return card;
  }

  function techNode(rows) {
    const more = el('details', 'dn-tech');
    add(more, el('summary', 'dn-techsum', 'Technical details'));
    for (const [label, words, code] of rows) {
      if (text(words)) add(more, el('p', 'dn-tk', label), el('p', code ? 'dn-tv is-code' : 'dn-tv', words));
    }
    return more;
  }

  // ---------------------------------------------------------------- the progress

  function road(stages) {
    const nodes = list(stages).filter((s) => s && typeof s === 'object');
    const wrap = el('div', 'dn-road');
    const w = 300; const h = 28; const pad = 25;
    const step = nodes.length > 1 ? (w - pad * 2) / (nodes.length - 1) : 0;
    const box = svg('svg', { viewBox: `0 0 ${w} ${h}`, class: 'dn-dots', 'aria-hidden': 'true', focusable: 'false' });
    nodes.forEach((n, i) => {
      const x = pad + i * step;
      const state = Object.prototype.hasOwnProperty.call(DOT, text(n.state)) ? DOT[text(n.state)] : 'is-dim';
      if (i > 0) {
        const reached = state === 'is-lit' || state === 'is-now' || state === 'is-stop';
        for (let k = 1; k <= 3; k++) box.appendChild(svg('circle', { cx: (x - step + (step * k) / 4).toFixed(2), cy: h / 2, r: 1.4, class: reached ? 'dn-run is-lit' : 'dn-run' }));
      }
      if (state === 'is-stop') {
        box.appendChild(svg('circle', { cx: x.toFixed(2), cy: h / 2, r: 6.2, class: 'dn-n is-stop is-ring' }));
        box.appendChild(svg('circle', { cx: x.toFixed(2), cy: h / 2, r: 2.3, class: 'dn-n is-stop is-core' }));
      } else {
        box.appendChild(svg('circle', { cx: x.toFixed(2), cy: h / 2, r: state === 'is-dim' ? 3.7 : 5.2, class: `dn-n ${state}` }));
      }
    });
    const labels = el('div', 'dn-stages');
    for (const n of nodes) {
      const state = Object.prototype.hasOwnProperty.call(DOT, text(n.state)) ? DOT[text(n.state)] : 'is-dim';
      labels.appendChild(el('span', `dn-stage ${state}`, n.label));
    }
    add(wrap, box, labels);
    return wrap;
  }

  const HEADS = { done: 'Deployed', rolled_back: 'Rolled back', halted: 'Stopped part way', refused: 'Not deployed',
    dry_run: 'Dry run', expired: 'Not deployed', not_started: 'Not deployed', lapsed: 'Approval expired' };

  function progressNode(p, on) {
    const o = on || {};
    const end = text(p.end);
    const card = el('section', `dn-card is-progress${end ? ` is-${end.replace(/[^a-z_]/g, '')}` : ''}`);
    card.setAttribute('aria-label', 'Deploy');
    const head = end === 'done' && text(p.kept_at) ? 'Deployed and kept' : HEADS[end] || 'Deploying';
    add(card, el('p', 'dn-eyebrow', head), el('h2', 'dn-title', p.title));
    card.appendChild(road(p.stages));
    const line = el('p', 'dn-line', o.restarting && !p.final ? 'CLIVE is restarting onto the new build…' : p.line);
    line.setAttribute('role', 'status');
    card.appendChild(line);
    const when = text(p.kept_at) ? `Kept ${ago(p.kept_at, o.now)}` : text(p.started_at) ? `Started ${ago(p.started_at, o.now)}`
      : `Approved ${ago(p.given_at, o.now)}`;
    if (when.split(' ').length > 1) add(card, el('p', 'dn-when', when));
    if (text(o.keepSaid)) add(card, el('p', 'dn-why', o.keepSaid));
    card.appendChild(techNode([['Version', p.short, true]]));
    return card;
  }

  function draw(payload, on) {
    const o = on || {};
    const p = payload && typeof payload === 'object' ? payload : {};
    const box = el('div', 'dn');
    if (p.progress && typeof p.progress === 'object') box.appendChild(progressNode(p.progress, o));
    if (p.offer && typeof p.offer === 'object') box.appendChild(offerNode(p.offer, o));
    for (const problem of list(p.problems)) if (text(problem)) box.appendChild(el('p', 'dn-problem', problem));
    if (text(o.flash)) box.appendChild(el('p', 'dn-flash', o.flash));
    return box;
  }

  // ---------------------------------------------------------------- talking to CLIVE

  const S = { payload: null, node: null, at: 0, timer: null, restarting: false, keeping: false, keepSaid: '', flash: '',
    host: null };

  async function call(path, body) {
    const f = typeof fetch === 'function' ? fetch : globalThis.fetch;
    const response = await f(path, body === undefined ? { cache: 'no-store' } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), cache: 'no-store',
    });
    const data = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, data };
  }

  function enc(buffer) {
    const bytes = new Uint8Array(buffer);
    let s = '';
    for (let i = 0; i < bytes.length; i += 1) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function dec(s) {
    const raw = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4));
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function passkey(options) {
    const o = Object.assign({}, options);
    o.challenge = dec(o.challenge);
    o.allowCredentials = list(o.allowCredentials).map((c) => ({ type: c.type, id: dec(c.id) }));
    const credential = await navigator.credentials.get({ publicKey: o });
    const r = credential.response;
    return { id: credential.id, rawId: enc(credential.rawId), type: credential.type, response: {
      clientDataJSON: enc(r.clientDataJSON), authenticatorData: enc(r.authenticatorData),
      signature: enc(r.signature), userHandle: r.userHandle ? enc(r.userHandle) : null } };
  }

  /* His hold: the prompt for exactly this version, his passkey, and the approval sent. Nothing is
   * deployed unless all three hold; a refusal is said on the card in CLIVE's own words. */
  async function deploy(offer, ui) {
    const fail = (words) => {
      ui.said.textContent = words;
      ui.button.disabled = false;
      ui.words.textContent = ui.label;
    };
    let asked;
    try {
      asked = await call('/release/deploy/challenge', { sha: text(offer.sha) });
    } catch (e) {
      return fail('CLIVE could not be reached. Nothing was deployed.');
    }
    if (!asked.ok) {
      fail(text(asked.data && asked.data.detail) || `CLIVE answered ${asked.status}. Nothing was deployed.`);
      return refresh();
    }
    let approval;
    try {
      approval = await passkey(asked.data.publicKey);
    } catch (e) {
      return fail(e && e.name === 'NotAllowedError' ? 'Cancelled, or the passkey prompt timed out. Nothing was deployed.'
        : 'Your passkey could not be asked. Nothing was deployed.');
    }
    ui.words.textContent = 'Starting the deploy…';
    let done;
    try {
      done = await call('/release/deploy', { sha: text(offer.sha), ticket: text(asked.data.ticket), approval });
    } catch (e) {
      return fail('CLIVE could not be reached, so your approval was not sent. Nothing was deployed.');
    }
    if (!done.ok) return fail(text(done.data && done.data.detail) || `CLIVE answered ${done.status}. Nothing was deployed.`);
    try { if (root.sessionStorage) root.sessionStorage.setItem(WATCHING, text(done.data.approved && done.data.approved.approval)); } catch (e) { /* only this tab's reminder */ }
    S.payload = Object.assign({}, S.payload || {}, { progress: done.data.progress, offer: null });
    S.at = Date.now();
    render();
    follow();
    return done.data;
  }

  /* While his deploy runs, ask again every few seconds (this server's files only); through CLIVE's own
   * restart, say so and keep asking. Once it is done on the new build, keep it. */
  function follow() {
    if (S.timer) { clearTimeout(S.timer); S.timer = null; }
    const p = S.payload && S.payload.progress;
    if (!p || (p.final && !p.keep_check)) return;
    if (p.keep_check) { keep(p); return; }
    S.timer = setTimeout(async () => { S.timer = null; await refresh(true); follow(); }, POLL_MS);
  }

  async function refresh(progressOnly) {
    let got;
    try {
      got = await call(progressOnly ? '/release/deploy?progress=1' : '/release/deploy');
    } catch (e) {
      S.restarting = Boolean(S.payload && S.payload.progress && !S.payload.progress.final);
      render();
      return S.payload;
    }
    S.restarting = false;
    if (got.ok) {
      // ?progress=1 never reads the trunk: the offer last read stays, but not beside a deploy still running.
      const running = got.data.progress && !got.data.progress.final;
      const offer = progressOnly ? (running ? null : (S.payload && S.payload.offer) || null) : got.data.offer;
      S.payload = Object.assign({}, got.data, { offer });
    } else if (got.status === 403) {
      S.payload = null;                           // not the owner's page: nothing of this is shown
    } else if (got.status >= 500 && S.payload && S.payload.progress) {
      S.restarting = !S.payload.progress.final;   // CLIVE answering while it restarts
    }
    if (!progressOnly) S.at = Date.now();         // when the trunk was last read: the screen's own refresh
    render();
    return S.payload;
  }

  /* The deploy is done on the new build: this page asks /whoami itself, then hands its token to CLIVE,
   * which keeps the deploy once that very line is in its journal. Asked again a few times while the
   * journal catches up. */
  async function keep(p) {
    if (S.keeping) return;
    S.keeping = true;
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    try {
      let who = null;
      for (let i = 0; i < 3 && !(who && who.ok); i += 1) {
        try { who = await call('/whoami'); } catch (e) { who = null; await sleep(2000); }
      }
      const me = who && who.data ? who.data : {};
      if (!who || !who.ok || !/^[0-9a-f]{8}$/.test(text(me.check))) {
        S.keepSaid = 'CLIVE could not be asked who this device is. Not kept yet.';
        render();
        return;
      }
      if (me.owner !== true || me.through !== 'tailscale') {
        S.keepSaid = `This device didn't get through as you (${text(me.owner_refusal) || text(me.through) || 'unknown'}), so the deploy isn't kept from here. Open CLIVE on your phone.`;
        render();
        return;
      }
      for (let i = 0; i < KEEP_TRIES; i += 1) {
        let kept;
        try { kept = await call('/release/kept', { sha: text(p.sha), check: text(me.check) }); } catch (e) { kept = null; }
        if (kept && kept.ok) {
          S.keepSaid = '';
          S.payload = Object.assign({}, S.payload || {}, { progress: kept.data.progress });
          try { if (root.sessionStorage) root.sessionStorage.removeItem(WATCHING); } catch (e) { /* only a reminder */ }
          render();
          return;
        }
        S.keepSaid = kept ? text(kept.data && kept.data.detail) : 'CLIVE could not be reached. Not kept yet.';
        render();
        if (kept && (kept.status === 400 || kept.status === 403)) return;
        await sleep(2000);          // the journal catching up with the line his phone just wrote
      }
    } finally {
      S.keeping = false;
    }
  }

  // ---------------------------------------------------------------- on the page

  function render() {
    const node = draw(S.payload, { deploy, now: new Date(), restarting: S.restarting, keepSaid: S.keepSaid, flash: S.flash });
    if (S.node && S.node.parentNode) S.node.parentNode.replaceChild(node, S.node);
    S.node = node;
    if (S.host && node.parentNode !== S.host) place(S.host);
    else stepAside(S.host);
    return node;
  }

  /* While a card is shown, the release service's own one line above it (web/builds.js releaseNode) steps
   * aside: the card says the same from fresher reads, and the line can be minutes old. */
  function stepAside(host) {
    const line = host && host.querySelector ? host.querySelector('.bd-release') : null;
    if (line) line.hidden = Boolean(S.node && S.node.querySelector && S.node.querySelector('.dn-card'));
  }

  /* web/builds.js calls this on every draw of the Builds screen: the card goes straight under the heading,
   * and is read again when it is older than the screen's own refresh. */
  function place(host) {
    if (!host) return null;
    S.host = host;
    const node = S.node || render();
    const hello = host.querySelector ? host.querySelector('.bd-hello') : null;
    const after = hello && hello.parentNode === host ? hello.nextSibling : host.firstChild;
    if (node.parentNode !== host) {
      if (after) host.insertBefore(node, after); else host.appendChild(node);
    }
    stepAside(host);
    if (!S.at || Date.now() - S.at > 25000) { S.at = Date.now(); refresh(false).then(follow); }
    return node;
  }

  /* On every owner page of CLIVE as it opens: a deploy he approved that is still running, or done and not
   * yet kept, is followed (and kept) here; the tab he approved it from opens the Builds screen on it. */
  async function watch() {
    const got = await refresh(true);
    const p = got && got.progress;
    if (!p || (p.final && !p.keep_check)) return;
    let mine = false;
    try { mine = Boolean(root.sessionStorage && root.sessionStorage.getItem(WATCHING) === text(p.approval)); } catch (e) { mine = false; }
    if (mine && root.CliveBuilds && typeof root.CliveBuilds.open === 'function') root.CliveBuilds.open();
    follow();
  }

  if (typeof document !== 'undefined' && typeof window !== 'undefined' && typeof fetch === 'function' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => { watch().catch(() => {}); });
  }

  return { draw, offerNode, progressNode, holdButton, road, place, refresh, deploy, keep, watch, follow, state: () => S, HOLD_MS };
});
