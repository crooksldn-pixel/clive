/* CROOKS OS — the application shell's service worker.
 *
 * This is an online operations app, not an offline copy of the store. The worker keeps exactly
 * one thing: the shell — the page, its scripts, its styles, its icons — so that opening the
 * installed app is instant and, when the Mac cannot be reached, the page still opens and can
 * say so in its own words instead of a browser error.
 *
 * Everything else is never touched. A request that is not for a shell file is not intercepted
 * at all, so /turn, /speak, /health, /state, /cancel, /reset, /audio-test and every other
 * call to the Mac — orders, email, customers, audio, answers — goes straight to the network
 * and is never stored, replayed or queued. Only GETs to this origin are considered, and only
 * for the paths listed below.
 *
 * The build id is written in by the Mac when this file is served, so the file changes — and
 * Chrome installs the new worker — whenever any page file does. The new worker waits until
 * the page says it is idle (not recording, not waiting, not speaking) before taking over.
 *
 * The page itself (round 10, B-07). What the Mac serves at '/' (app/main.py `index`) is
 * web/index.html with the build id written into it and nothing else: the same for every login,
 * before anything is asked for. That page, of this build, is the only page this worker keeps. An
 * answer at '/' is kept only when it is that page — a 200, HTML, not the end of a redirect, and
 * carrying this build's own mark — so a proxy's page, a sign-in page, an error page, another
 * build's page or anything else is passed on and never kept, and so never opened offline. The
 * screens are never the worker's: /display and every /displays call go to the Mac untouched.
 */
'use strict';

const BUILD = '__BUILD__';
const CACHE = `crooks-shell-${BUILD}`;
const CACHE_PREFIX = 'crooks-shell-';

// The shell, and nothing but the shell. A path that is not here is not ours to answer.
const SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/alpha.js',
  '/static/alpha.css',
  '/static/ui.js',
  '/static/action-state.js',
  '/static/live-state.js',
  '/static/jobs.js',
  '/static/telemetry.js',
  '/static/collide.js',
  '/static/touch.js',
  '/static/notify.js',
  '/static/orb.js',
  '/static/dots.js',
  '/static/startup.js',
  '/static/startup.css',
  '/static/audio-viz.js',
  '/static/live-voice.js',   // live words and the real waveform while holding
  // Round 9: the remote for the screens. Code and styles only; what it shows is asked for.
  '/static/remote.js',
  '/static/remote.css',
  // Round 12: an objective in the shape of its kind (web/objective-cards.js).
  '/static/objective-cards.js',
  '/static/objective-cards.css',
  // Objectives by touch: the gestures and the bar the two above share (web/objective-touch.js).
  '/static/objective-touch.js',
  // Objectives by touch, part C: a number to reach (web/objective-number.js).
  '/static/objective-number.js',
  // Round 12: holding a record to put it on a screen. Code and styles only, like the remote.
  '/static/lift.js',
  '/static/lift.css',
  // Round 12: soft scroll edges, and cards that form out of the orb and its dots.
  '/static/edges.js',
  '/static/edges.css',
  '/static/dots-app.js',
  '/static/dots-app.css',
  // Objectives by touch, part B: the next six weeks and the pinch between the three distances.
  '/static/horizon.js',
  '/static/horizon.css',
  '/static/distances.js',
  // The Builds screen: every build in plain words, and the decisions it needs (web/builds.js).
  '/static/builds.js',
  '/static/builds.css',
  // Its Research section: research George gave CLIVE and his answers (web/research.js).
  '/static/research.js',
  '/static/research.css',
  // Customers: the order he meant, their story, a refund landing (web/customers.js).
  '/static/customers.js',
  '/static/customers.css',
  // CROOKS Returns: the returns card, the returns on an order, the row on the home.
  '/static/returns.js',
  '/static/returns.css',
  // [messaging] WeChat and WeCom conversations, the original one tap away.
  '/static/messages.js',
  '/static/messages.css',
  // CLIVE Shipping: the international orders, one order in full, what changed.
  '/static/shipping.js',
  '/static/shipping.css',
  // The design pass of 3 Oct: the answer in full, Home, approval weights, the dock (web/design.css).
  '/static/design.css',
  '/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/icon-maskable-192.png',
  '/static/icon-maskable-512.png',
];

// How long to wait for the Mac before opening from the shell instead. A peer that is off the
// tailnet can take a while to refuse; the owner should not stare at a blank screen for it.
const NETWORK_TIMEOUT_MS = 1500;

// The mark of this build's own page: web/index.html's `crooks-build` meta, as the Mac writes it in.
const PAGE_MARK = '<meta name="crooks-build" content="' + BUILD + '">';

// When the page itself just had to open from the shell, the Mac is away: its scripts and
// styles are served from the shell at once for a moment, instead of each waiting its turn.
const AWAY_GRACE_MS = 10000;
let awayUntil = 0;

// The very last resort: no worker cache yet (a first visit made while offline). Static text,
// nothing from any session.
const OFFLINE_HTML = '<!doctype html><html lang="en-GB"><head><meta charset="utf-8">'
  + '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#07070a">'
  + '<title>CLIVE</title><style>html,body{height:100%;margin:0;background:#07070a;color:#ebe8e0;'
  + 'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}body{display:grid;place-items:center;text-align:center}'
  + 'small{display:block;letter-spacing:.32em;color:#83827c;font-weight:800;font-size:12px;margin-bottom:28px}'
  + 'h1{margin:0 0 10px;font-size:20px;letter-spacing:.26em;text-transform:uppercase}p{margin:0;color:#b9b6ae}</style>'
  + '<meta http-equiv="refresh" content="8"></head><body><div><small>CLIVE</small>'
  + '<h1>System offline</h1><p>Waiting for CLIVE…</p></div></body></html>';

self.addEventListener('install', (event) => {
  // Nothing hurries this along: a new build installs quietly and takes over only when the
  // page says nothing is in progress (see the message handler).
  event.waitUntil(caches.open(CACHE).then(keepShell));
});

// The shell, fetched afresh for this build: the page first, and only if it is this build's own
// (isShell), then the files as they come. If the page is not, nothing is kept, the install fails,
// and the browser keeps the worker it has and tries again later.
async function keepShell(cache) {
  const page = await fetch(self.location.origin + '/', { cache: 'no-cache' });
  if (!(await isShell(page))) throw new Error('the page at / is not this build\'s shell');
  await cache.addAll(SHELL.filter((path) => path !== '/'));
  await cache.put('/', page);
}

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;                       // never a POST: nothing to replay
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;            // nothing but the Mac
  if (/^\/displays?(\/|$)/.test(url.pathname)) return;         // a screen, and its every call, is the Mac's
  // Only the app's own page is the shell. A navigation to /whoami, /health or /docs is a
  // page of its own — passed straight to the Mac, never stored under '/', or the next
  // offline launch would open as that JSON instead of the app.
  if (request.mode === 'navigate' && url.pathname !== '/') return;
  const path = request.mode === 'navigate' ? '/' : url.pathname;
  if (SHELL.indexOf(path) === -1) return;                     // not the shell: not intercepted
  event.respondWith(networkFirst(path, request));
});

// Fresh from the Mac whenever it answers, so a page open for weeks still gets today's files;
// the copy in the cache is for when it does not. A 5xx is the Tailscale proxy saying the
// backend is not there — that is "does not answer" too. A 4xx is an answer and is passed on.
async function networkFirst(path, request) {
  const cache = await caches.open(CACHE);
  if (path !== '/' && Date.now() < awayUntil) {
    const held = await cache.match(path);
    if (held) return held;
  }
  try {
    const response = await withTimeout(fetch(request), NETWORK_TIMEOUT_MS);
    if (response.status >= 500) throw new Error(`backend ${response.status}`);
    // Same origin by construction. The page slot takes this build's page only (isShell):
    // whatever else answers at '/' (a proxy's JSON or sign-in page, a redirect, a refusal, a
    // page of another build) is passed on but never kept as the app.
    if (path === '/') {
      if (await isShell(response)) cache.put(path, response.clone());
    } else if (response.ok) {
      cache.put(path, response.clone());
    }
    return response;
  } catch (error) {
    if (path === '/') awayUntil = Date.now() + AWAY_GRACE_MS;
    const cached = await cache.match(path);
    if (cached) return cached;
    if (path === '/') return new Response(OFFLINE_HTML, { status: 200, headers: { 'Content-Type': 'text/html; charset=utf-8' } });
    return Response.error();
  }
}

function isHtml(response) {
  const type = (response.headers && typeof response.headers.get === 'function' ? response.headers.get('content-type') : '') || '';
  return type.toLowerCase().indexOf('text/html') === 0;
}

// This build's own page, exactly as the Mac serves it at '/': a 200, HTML, not the end of a
// redirect, with this build's mark in it. Read from a copy, so the answer itself is untouched.
async function isShell(response) {
  if (!response || response.status !== 200 || response.redirected || !isHtml(response)) return false;
  try {
    return (await response.clone().text()).indexOf(PAGE_MARK) !== -1;
  } catch (error) {
    return false;
  }
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then((value) => { clearTimeout(timer); resolve(value); }, (error) => { clearTimeout(timer); reject(error); });
  });
}
