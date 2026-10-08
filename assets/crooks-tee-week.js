/* CROOKSLDN — T-shirt Week.
   Two tees drop each day at 6pm, shown side by side as case files. Opening one
   swings its cover back into a retro window and folds the other to a spine.
   Days still to come are chained shut with a padlock and a countdown.
   The tees, start date and drop hour come from the section's JSON
   (sections/crooks-tee-week.liquid). Add ?tw_day=1..7 to the URL to preview a
   day of the week (0 = before it starts). */
(function () {
  'use strict';

  var root = document.querySelector('[data-ctw]');
  var dataEl = root && root.querySelector('[data-ctw-data]');
  if (!root || !dataEl) return;
  var DATA;
  try { DATA = JSON.parse(dataEl.textContent); } catch (e) { return; }

  var COL = {
    black: { name: 'Black', hex: '#141317', ink: '#DDD7C9' },
    white: { name: 'White', hex: '#F2F0EA', ink: '#141317' },
    'light-grey': { name: 'Light Grey', hex: '#AAA9A8', ink: '#141317' },
    charcoal: { name: 'Charcoal', hex: '#64625F', ink: '#DDD7C9' },
    navy: { name: 'Navy', hex: '#18263F', ink: '#DDD7C9' },
    green: { name: 'Green', hex: '#063D1C', ink: '#DDD7C9' }
  };
  var COLS = ['black', 'white', 'light-grey', 'charcoal', 'navy', 'green'];
  var SIZES = ['XS', 'S', 'M', 'L', 'XL'];
  var FREE = [6, 10, 13];
  var PRICE = Number(DATA.price) || 20;
  /* Stand-in measurements from the CRX Garms tee: chest all the way round, length, shoulder (cm).
     The chart shows chest flat, pit to pit. Swap in the T-shirt Week blank's spec. */
  var FIT = {
    XS: [100.3, 67.3, 49.5], S: [105.4, 69.8, 52.1], M: [110.5, 72.4, 54.6],
    L: [115.6, 74.9, 57.1], XL: [119.4, 76.2, 59.7]
  };
  var WEEKDAYS = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY'];

  var SVG_MSG = '<svg viewBox="0 0 16 14" width="16" height="14" aria-hidden="true"><path d="M1.5 1.5h13v8h-7l-3.5 3v-3h-2.5z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>';
  var SVG_FOLDER = '<svg viewBox="0 0 14 11" width="14" height="11" aria-hidden="true"><path d="M0.5 1.5h5l1.5 1.5h6.5v7.5h-13z" fill="#C2B18B" stroke="#2B2116"/></svg>';
  var SVG_X = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M4 4L16 16M16 4L4 16" stroke="currentColor" stroke-width="1.5"/></svg>';
  var SVG_X16 = '<svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M5 5L15 15M15 5L5 15" stroke="currentColor" stroke-width="1.6"/></svg>';
  var SVG_RULER = '<svg viewBox="0 0 26 12" width="26" height="12" aria-hidden="true"><rect x="0.75" y="0.75" width="24.5" height="10.5" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5 1v4M9 1v3M13 1v5M17 1v3M21 1v4" stroke="currentColor" stroke-width="1.2"/></svg>';
  var SVG_LOCK = '<svg viewBox="0 0 64 80" width="56" height="70" aria-hidden="true">'
    + '<path d="M17 38V23a15 15 0 0 1 30 0V38" fill="none" stroke="url(#ctw-shackle)" stroke-width="7" stroke-linecap="round"/>'
    + '<path d="M17 38V23a15 15 0 0 1 30 0V38" fill="none" stroke="#2B2B33" stroke-width="1" opacity=".5"/>'
    + '<rect x="5" y="35" width="54" height="42" rx="5" fill="url(#ctw-lockbody)" stroke="#1B0B29" stroke-width="2"/>'
    + '<rect x="9" y="39" width="46" height="4" rx="2" fill="#F2F0EA" opacity=".25"/>'
    + '<circle cx="32" cy="53" r="5.5" fill="#0B0A0E"/><path d="M29.2 55h5.6l1.6 12h-8.8z" fill="#0B0A0E"/></svg>';

  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function money(n) { return '£' + (Math.round(n * 100) % 100 ? n.toFixed(2) : String(Math.round(n))); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function freeIn(n) { return FREE.filter(function (s) { return s <= n; }).length; }
  function fmt(cm) { return S.unit === 'in' ? (cm / 2.54).toFixed(1) : cm.toFixed(1); }
  function sizeSummary(list) {
    var counts = {};
    list.forEach(function (s) { counts[s] = (counts[s] || 0) + 1; });
    return SIZES.filter(function (s) { return counts[s]; }).map(function (s) { return counts[s] > 1 ? s + ' ×' + counts[s] : s; }).join(', ');
  }

  /* ---- Clock. Each drop is at the drop hour, London time. UK clocks go
     forward and back on the last Sunday of March and October at 01:00 UTC. */
  function ukOffset(ms) {
    var y = new Date(ms).getUTCFullYear();
    function lastSunday(m) { var d = new Date(Date.UTC(y, m + 1, 0)); return Date.UTC(y, m, d.getUTCDate() - d.getUTCDay(), 1); }
    return ms >= lastSunday(2) && ms < lastSunday(9) ? 3600000 : 0;
  }
  var START = String(DATA.start || '2026-10-12').split('-').map(Number);
  var HOUR = parseInt(DATA.dropHour, 10);
  if (isNaN(HOUR)) HOUR = 18;
  var HOUR_LABEL = (HOUR % 12 || 12) + (HOUR < 12 ? 'AM' : 'PM');
  function dropAt(i) {
    var wall = Date.UTC(START[0], START[1] - 1, START[2] + i, HOUR);
    return wall - ukOffset(wall - ukOffset(wall));
  }
  var DAYS = [0, 1, 2, 3, 4, 5, 6].map(function (i) {
    var d = new Date(Date.UTC(START[0], START[1] - 1, START[2] + i));
    var long = WEEKDAYS[d.getUTCDay()];
    var date = pad(d.getUTCDate()) + '.' + pad(d.getUTCMonth() + 1);
    return { name: long.slice(0, 3), date: date, long: long + ' ' + date };
  });

  /* Preview clock: ?tw_day=N (or the section setting) sets the clock to
     20:41:13 on day N, just after that day's drop, and lets it run on. */
  var simDay = null;
  try { simDay = new URLSearchParams(location.search).get('tw_day'); } catch (e) { /* old browser */ }
  if (simDay == null || simDay === '') simDay = DATA.previewDay;
  var skew = 0, SIM = false;
  if (simDay != null && simDay !== '' && !isNaN(Number(simDay))) {
    simDay = Math.max(0, Math.min(7, Math.round(Number(simDay))));
    var simAt = (simDay ? dropAt(simDay - 1) : dropAt(0) - 2 * 86400000) + (2 * 3600 + 41 * 60 + 13) * 1000;
    skew = simAt - Date.now();
    SIM = true;
  }
  function now() { return Date.now() + skew; }
  function today() {
    var t = now(), d = -1;
    for (var i = 0; i < 7; i++) if (t >= dropAt(i)) d = i;
    return d;
  }

  /* ---- The tees, in release order. */
  var DESIGNS = (DATA.designs || []).map(function (d, k) { d.k = k; return d; })
    .filter(function (d) { return d.handle && d.day >= 1 && d.day <= 7; })
    .sort(function (a, b) { return a.day - b.day || a.k - b.k; })
    .map(function (d, i) {
      var short = String(d.title || d.handle).replace(/ T-Shirt$/i, '');
      return {
        no: pad(i + 1),
        day: d.day - 1,
        handle: d.handle,
        slug: d.handle.replace(/-t-shirt$/, ''),
        short: short,
        title: short + ' T-Shirt',
        file: short.toUpperCase().replace(/[^A-Z0-9 ]/g, '').trim().replace(/ +/g, '_') + '.PNG',
        variants: d.variants || {}
      };
    });
  var BY = {};
  DESIGNS.forEach(function (d) { BY[d.handle] = d; });
  function dayDesigns(day) { return DESIGNS.filter(function (d) { return d.day === day; }); }
  function img(d, c, w) { return (DATA.imageBase || '') + 'crooksldn-' + d.slug + '-' + c + '-t-shirt.png?width=' + w; }
  function variantOf(b) { var d = BY[b.h]; return d && d.variants[b.c + '|' + b.s]; }

  /* ---- State. The bag, size and texts survive a reload. */
  var KEY = 'ctw-v1' + (SIM ? '-preview' : '');
  var TODAY = today();
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { saved = {}; }
  var S = {
    size: SIZES.indexOf(saved.size) >= 0 ? saved.size : null,
    day: Math.max(0, TODAY),
    open: 0,
    view: {},
    shot: {},
    bag: (Array.isArray(saved.bag) ? saved.bag : []).filter(function (b) {
      return b && BY[b.h] && BY[b.h].day <= TODAY && COL[b.c] && SIZES.indexOf(b.s) >= 0 && b.id > 0;
    }),
    nextId: 1,
    sheet: null,
    pending: null,
    chart: false,
    unit: 'cm',
    editItem: null,
    sms: { open: false, done: saved.sms && typeof saved.sms === 'object' ? saved.sms : {}, error: '', value: '' },
    toast: null
  };
  S.nextId = S.bag.reduce(function (m, b) { return Math.max(m, b.id + 1); }, 1);
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify({ size: S.size, bag: S.bag, sms: S.sms.done })); } catch (e) { /* private mode */ }
  }

  function ref(name) { return root.querySelector('[data-ref="' + name + '"]'); }
  function inBag(h, c) { return S.bag.filter(function (b) { return b.h === h && b.c === c; }); }
  function colourOf(d) { return COLS[S.view[d.handle] || 0]; }
  function totals() {
    var n = S.bag.length, f = freeIn(n);
    return { n: n, f: f, pay: PRICE * (n - f), next: FREE.filter(function (s) { return s > n; })[0] };
  }

  /* Swap a container's HTML, keeping focus on the same control (by data-key) if it survives. */
  function paint(el, html, fallbacks) {
    var a = document.activeElement;
    var key = a && el.contains(a) ? a.getAttribute('data-key') : null;
    el.innerHTML = html;
    if (!key) return;
    var keys = [key].concat(fallbacks || []);
    for (var i = 0; i < keys.length; i++) {
      var t = el.querySelector('[data-key="' + keys[i] + '"]');
      if (t) { t.focus({ preventScroll: true }); return; }
    }
  }

  /* ---- Countdown and texts */
  function cdTarget() { var d = S.day > TODAY ? S.day : TODAY + 1; return d < 7 ? d : -1; }
  function left(d) {
    var s = Math.max(0, Math.floor((dropAt(d) - now()) / 1000));
    return { d: Math.floor(s / 86400), h: Math.floor(s % 86400 / 3600), m: Math.floor(s % 3600 / 60), s: s % 60 };
  }

  function renderCount() {
    var el = ref('count'), d = cdTarget();
    if (d < 0) { el.hidden = true; el.innerHTML = ''; return; }
    el.hidden = false;
    var done = !!S.sms.done[d], dn = DAYS[d].name;
    var h = '<section class="ctw-count" aria-label="Next drop">'
      + '<p class="ctw-count__label">' + (S.day > TODAY ? 'UNSEALS ' : 'NEXT DROP · ') + dn + ' ' + DAYS[d].date + ' · ' + HOUR_LABEL + '</p>'
      + '<div class="ctw-count__row"><div class="ctw-timer" role="timer" data-ref="timer"></div>'
      + '<button type="button" class="ctw-text-me' + (done ? ' is-set' : '') + '" data-act="sms-toggle" data-key="sms-toggle" aria-expanded="' + S.sms.open + '" aria-controls="ctw-sms">'
      + SVG_MSG + '<span>' + (done ? 'TEXT SET ✓' : 'TEXT ME') + '</span></button></div>';
    if (S.sms.open) {
      h += '<div class="ctw-sms" id="ctw-sms">'
        + '<label for="ctw-sms-input">GET A TEXT WHEN ' + dn + '’S TEES DROP</label>'
        + '<div class="ctw-sms__row"><span class="ctw-sms__cc">+44</span>'
        + '<input id="ctw-sms-input" type="tel" inputmode="tel" autocomplete="tel-national" placeholder="07700 900123" value="' + esc(S.sms.value) + '"'
        + (S.sms.error ? ' aria-invalid="true" aria-describedby="ctw-sms-err"' : '') + '></div>'
        + (S.sms.error ? '<p class="ctw-sms__err" id="ctw-sms-err" role="alert">' + esc(S.sms.error) + '</p>' : '')
        + '<button type="button" class="ctw-add" data-act="sms-submit" data-key="sms-submit">TEXT ME AT ' + HOUR_LABEL + ' ' + dn + '</button>'
        + '<p class="ctw-sms__small">' + (DATA.smsLive
          ? 'One text for this drop. Reply STOP to opt out.'
          : 'Preview: texts aren’t switched on yet. When they are, it’s one text for this drop. Reply STOP to opt out.') + '</p>'
        + '</div>';
    }
    h += '</section>';
    paint(el, h);
    tickTimer();
  }

  function tickTimer() {
    var d = cdTarget();
    if (d < 0) return;
    var p = left(d);
    var timer = ref('timer');
    if (timer) {
      var list = (p.d ? [[p.d, p.d === 1 ? 'DAY' : 'DAYS']] : []).concat([[pad(p.h), 'HRS'], [pad(p.m), 'MIN'], [pad(p.s), 'SEC']]);
      timer.innerHTML = list.map(function (x) {
        return '<span class="ctw-timer__part"><span class="ctw-timer__num">' + x[0] + '</span><span class="ctw-timer__unit">' + x[1] + '</span></span>';
      }).join('');
      timer.setAttribute('aria-label', 'Next drop in ' + (p.d ? p.d + (p.d === 1 ? ' day ' : ' days ') : '') + p.h + ' hours ' + p.m + ' minutes');
    }
    var opens = 'OPENS IN ' + (p.d ? p.d + 'D ' : '') + pad(p.h) + ':' + pad(p.m) + ':' + pad(p.s);
    root.querySelectorAll('[data-ref="opens"]').forEach(function (el) { el.textContent = opens; });
  }

  function tick() {
    var t = today();
    if (t !== TODAY) {
      if (S.day === Math.max(0, TODAY)) S.day = Math.max(0, t);
      TODAY = t;
      S.open = 0;
      renderAll();
      return;
    }
    tickTimer();
  }

  /* ---- Deals, days */
  function renderDeals() {
    var f = freeIn(S.bag.length);
    ref('deals').innerHTML = FREE.map(function (n, k) {
      return '<div class="ctw-deal' + (f > k ? ' is-hit' : '') + '"><b>' + n + ' FOR ' + money(PRICE * (n - k - 1)) + '</b><span>' + (k + 1) + ' FREE</span></div>';
    }).join('');
  }

  function renderDays() {
    paint(ref('days'), DAYS.map(function (d, i) {
      var status = i === TODAY ? 'TODAY' : i < TODAY ? 'ON SALE' : HOUR_LABEL;
      return '<button type="button" class="ctw-day' + (i === TODAY ? ' is-today' : '') + (i > TODAY ? ' is-locked' : '') + '"'
        + ' data-act="day" data-v="' + i + '" data-key="day:' + i + '" aria-current="' + (i === S.day) + '">'
        + '<b>' + d.name + '</b><span>' + status + '</span></button>';
    }).join(''));
    ref('dayhead').textContent = DAYS[S.day].long + ' · ' + (S.day === TODAY ? 'NEW TODAY' : S.day < TODAY ? 'STILL ON SALE' : 'DROPS AT ' + HOUR_LABEL);
  }

  /* ---- The case files */
  function fileState(i) { return !S.open ? 'split' : S.open === i + 1 ? 'open' : 'shut'; }

  function coverHTML(d, i) {
    var c = colourOf(d);
    return '<button type="button" class="ctw-cover" data-act="open" data-i="' + i + '" data-key="cover:' + i + '" aria-expanded="false" aria-label="Open tee ' + d.no + ', ' + esc(d.title) + '">'
      + '<span class="ctw-cover__head"><span class="ctw-cover__price">' + money(PRICE) + '</span><span>EVIDENCE</span></span>'
      + '<span class="ctw-mini"><span class="ctw-mini__bar"><span>' + esc(d.file) + '</span><i aria-hidden="true">_</i><i aria-hidden="true">×</i></span>'
      + '<span class="ctw-mini__stage"><img src="' + img(d, c, 360) + '" alt="" width="360" height="360"></span></span>'
      + '<span class="ctw-cover__no">SUSPECT ' + d.no + ' / ' + pad(DESIGNS.length) + '</span>'
      + '<span class="ctw-cover__title">' + esc(d.short) + '</span>'
      + '<span class="ctw-cover__meta">' + COLS.length + ' COLOURS</span>'
      + '<span class="ctw-cover__dots" aria-hidden="true">' + COLS.map(function (cc) { return '<i style="background:' + COL[cc].hex + '"></i>'; }).join('') + '</span>'
      + '<span class="ctw-cover__cta"><span>OPEN FILE ▸</span></span>'
      + '</button>';
  }

  function spineHTML(d, i) {
    return '<button type="button" class="ctw-spine" data-act="open" data-i="' + i + '" data-key="spine:' + i + '" aria-label="Switch to tee ' + d.no + ', ' + esc(d.title) + '">'
      + '<img src="' + img(d, colourOf(d), 120) + '" alt="" width="36" height="36">'
      + '<span class="ctw-spine__label">TEE ' + d.no + ' · ' + esc(d.short.toUpperCase()) + '</span>'
      + '<span class="ctw-spine__go" aria-hidden="true">' + (i ? '◂' : '▸') + '</span></button>';
  }

  function insideHTML(d, i) {
    var c = colourOf(d), col = COL[c], name = col.name.toUpperCase();
    var shot = S.shot[d.handle] || 'front';
    var here = inBag(d.handle, c), cnt = here.length;
    var missing = COLS.filter(function (cc) { return !inBag(d.handle, cc).length; });
    var n = S.bag.length, gain = freeIn(n + missing.length) - freeIn(n);
    var di = ' data-i="' + i + '"';
    var act = cnt
      ? '<div class="ctw-step"><button type="button" data-act="minus"' + di + ' data-key="minus" aria-label="Remove one ' + col.name + '">−</button>'
        + '<span>' + cnt + ' IN BAG</span>'
        + '<button type="button" data-act="plus"' + di + ' data-key="plus" aria-label="Add another ' + col.name + '">+</button></div>'
      : '<button type="button" class="ctw-add" data-act="add"' + di + ' data-key="add">ADD ' + name + ' · ' + money(PRICE) + '</button>';
    return '<div class="ctw-win">'
      + '<div class="ctw-win__bar">' + SVG_FOLDER + '<span class="ctw-win__name">' + esc(d.file) + '</span>'
      + '<button type="button" class="ctw-win__btn" data-act="close"' + di + ' data-key="min" aria-label="Minimise this file">_</button>'
      + '<span class="ctw-win__btn is-dead" aria-hidden="true">□</span>'
      + '<button type="button" class="ctw-win__btn" data-act="close"' + di + ' data-key="x" aria-label="Close this file">×</button></div>'
      + '<div class="ctw-win__menu" aria-hidden="true"><span><u>F</u>ile</span><span><u>C</u>olour</span><span><u>S</u>ize</span><span><u>H</u>elp</span><span>TEE ' + d.no + '</span></div>'
      + '<div class="ctw-win__stage">'
      + '<img class="' + (shot === 'print' ? 'is-print' : 'is-front') + '" src="' + img(d, c, shot === 'print' ? 1200 : 640) + '" width="640" height="640"'
      + ' alt="' + esc(d.title + ' in ' + col.name + (shot === 'print' ? ', close-up of the print' : ', front')) + '">'
      + '<span class="ctw-placard' + (cnt ? ' is-in' : '') + '">' + name + (cnt ? ' · ' + cnt + ' IN BAG' : '') + '</span></div>'
      + '<div class="ctw-win__tabs" role="group" aria-label="Photos">' + [['front', 'FRONT'], ['print', 'PRINT']].map(function (s) {
        return '<button type="button" class="ctw-win__tab" data-act="shot"' + di + ' data-v="' + s[0] + '" data-key="shot:' + s[0] + '" aria-pressed="' + (s[0] === shot) + '">' + s[1] + '</button>';
      }).join('') + '</div>'
      + '<div class="ctw-win__body">'
      + '<div class="ctw-win__row"><p>COLOUR · <span>' + name + '</span></p><p>' + (cnt ? 'IN BAG · ' + sizeSummary(here.map(function (b) { return b.s; })) : '') + '</p></div>'
      + '<div class="ctw-swatches">' + COLS.map(function (cc, k) {
        var tc = COL[cc], on = cc === c, have = inBag(d.handle, cc).length;
        return '<button type="button" class="ctw-sw' + (on ? ' is-on' : '') + '" data-act="view"' + di + ' data-v="' + k + '" data-key="view:' + k + '"'
          + ' aria-pressed="' + on + '" aria-label="Show ' + tc.name + (have ? ', ' + have + ' in your bag' : '') + '" style="--chip:' + tc.hex + ';--ink:' + tc.ink + '">'
          + '<span class="ctw-sw__chip">' + (k + 1) + (have ? '<span class="ctw-sw__badge">✓' + (have > 1 ? have : '') + '</span>' : '') + '</span>'
          + '<span class="ctw-sw__name">' + tc.name + '</span></button>';
      }).join('') + '</div>'
      + '<div class="ctw-act"><button type="button" class="ctw-sizechip' + (S.size ? '' : ' is-empty') + '" data-act="size-open" data-key="size"'
      + ' aria-label="' + (S.size ? 'Size ' + S.size + ', change' : 'Pick your size') + '"><span>SIZE</span><b>' + (S.size || 'PICK') + '</b></button>' + act + '</div>'
      + (missing.length > 1 ? '<button type="button" class="ctw-addall" data-act="addall"' + di + ' data-key="addall">'
        + (missing.length === COLS.length ? 'Add all ' : 'Add the other ') + missing.length + ' colours · +' + money(PRICE * (missing.length - gain)) + '</button>' : '')
      + '</div>'
      + '<div class="ctw-win__status"><span>' + COLS.length + ' colours · 200gsm · regular fit</span><span>' + money(PRICE) + '</span></div>'
      + '</div>';
  }

  function filesHTML(list) {
    return '<div class="ctw-files ctw-noanim" data-ref="row">' + list.map(function (d, i) {
      return '<div class="ctw-file is-split">'
        + '<span class="ctw-tab" aria-hidden="true">' + esc(d.short.toUpperCase()) + '</span>'
        + '<div class="ctw-body">'
        + '<div class="ctw-inside" role="region" aria-label="' + esc(d.title) + '" data-inside="' + i + '"></div>'
        + coverHTML(d, i) + spineHTML(d, i)
        + '</div></div>';
    }).join('') + '</div>';
  }

  function lockedHTML(list) {
    var day = DAYS[S.day];
    return '<div class="ctw-locked ctw-noanim" data-ref="row">' + list.map(function (d, i) {
      return '<div class="ctw-file ctw-file--locked is-split">'
        + '<span class="ctw-tab" aria-hidden="true">UNDER SEAL</span>'
        + '<div class="ctw-body"><button type="button" class="ctw-cover ctw-cover--locked" data-act="shake" data-i="' + i + '" data-key="sealed:' + i + '"'
        + ' aria-label="Tee ' + d.no + ' is sealed until ' + day.long + ' at ' + HOUR_LABEL + '">'
        + '<span class="ctw-cover__head"><span class="ctw-cover__price">' + money(PRICE) + '</span><span>EVIDENCE</span></span>'
        + '<span class="ctw-mini"><span class="ctw-mini__bar"><span>SEALED.PNG</span><i aria-hidden="true">×</i></span>'
        + '<span class="ctw-mini__stage"><img src="' + img(d, 'black', 360) + '" alt="" width="360" height="360"></span></span>'
        + '<span class="ctw-cover__no">SUSPECT ' + d.no + ' / ' + pad(DESIGNS.length) + '</span>'
        + '<span class="ctw-cover__title">UNDER SEAL</span>'
        + '<span class="ctw-cover__meta">' + COLS.length + ' COLOURS</span>'
        + '<span class="ctw-cover__cta"><span data-ref="opens"></span></span>'
        + '</button></div></div>';
    }).join('')
      + '<div class="ctw-chains" aria-hidden="true">' + list.map(function () { return '<span class="ctw-chain"></span><span class="ctw-chain"></span>'; }).join('') + '</div>'
      + list.map(function (d, i) {
        return '<button type="button" class="ctw-lock" data-act="shake" data-i="' + i + '" tabindex="-1" aria-hidden="true">' + SVG_LOCK + '</button>';
      }).join('')
      + '</div>';
  }

  function renderStage() {
    var el = ref('stage'), list = dayDesigns(S.day);
    if (!list.length) { el.innerHTML = ''; return; }
    var open = S.day <= TODAY;
    el.innerHTML = open ? filesHTML(list) : lockedHTML(list);
    if (open) list.forEach(function (d, i) { renderInside(i, true); });
    applyOpen();
    tickTimer();
    var row = ref('row');
    requestAnimationFrame(function () { requestAnimationFrame(function () { if (row) row.classList.remove('ctw-noanim'); }); });
  }

  function renderInside(i, quiet) {
    var d = dayDesigns(S.day)[i], el = root.querySelector('[data-inside="' + i + '"]');
    if (!d || !el) return;
    paint(el, insideHTML(d, i), ['plus', 'add', 'size']);
    var file = el.parentNode, c = colourOf(d);
    var ci = file.querySelector('.ctw-mini__stage img');
    if (ci) ci.src = img(d, c, 360);
    var si = file.querySelector('.ctw-spine img');
    if (si) si.src = img(d, c, 120);
    if (!quiet) layout();
  }

  function applyOpen() {
    var list = dayDesigns(S.day);
    root.querySelectorAll('.ctw-files > .ctw-file').forEach(function (f, i) {
      var st = fileState(i);
      f.classList.toggle('is-split', st === 'split');
      f.classList.toggle('is-open', st === 'open');
      f.classList.toggle('is-shut', st === 'shut');
      f.querySelector('.ctw-tab').textContent = st === 'shut' ? list[i].no : list[i].short.toUpperCase();
      f.querySelector('.ctw-cover').setAttribute('aria-expanded', String(st === 'open'));
    });
    layout();
  }

  /* Widths and heights are set here so the folders can animate between them:
     split = two halves, open = everything but a 44px spine for the other file. */
  function layout() {
    var row = ref('row');
    if (!row) return;
    var W = row.clientWidth, half = (W - 8) / 2, files = row.querySelectorAll(':scope > .ctw-file');
    row.style.setProperty('--ctw-cover-w', (half - 2) + 'px');
    row.style.setProperty('--ctw-inside-w', (W - 66) + 'px');
    var coverH = 0;
    row.querySelectorAll('.ctw-cover').forEach(function (c) {
      c.style.minHeight = '0';
      coverH = Math.max(coverH, c.offsetHeight);
      c.style.minHeight = '';
    });
    var H = coverH + 19;
    if (row.classList.contains('ctw-locked')) {
      /* Two chains cross each folder, meeting under the padlock 70% of the way down. */
      var bh = H - 17, cy = bh * 0.7, deg = Math.atan2(bh, half) * 180 / Math.PI, len = 2 * Math.sqrt(half * half + bh * bh) + 40;
      var chains = row.querySelectorAll('.ctw-chain'), locks = row.querySelectorAll('.ctw-lock');
      files.forEach(function (f, i) {
        f.style.width = half + 'px';
        var cx = i * (half + 8) + half / 2;
        [deg, -deg].forEach(function (a, s) {
          var el = chains[i * 2 + s];
          if (el) el.style.cssText = 'left:' + (cx + 4 - len / 2) + 'px;top:' + (cy - 7) + 'px;width:' + len + 'px;transform:rotate(' + a + 'deg)';
        });
        if (locks[i]) { locks[i].style.left = (cx - 28) + 'px'; locks[i].style.top = (17 + cy - 49) + 'px'; }
      });
    } else {
      files.forEach(function (f, i) {
        var st = fileState(i);
        f.style.width = (st === 'split' ? half : st === 'open' ? W - 52 : 44) + 'px';
        if (st === 'open') H = Math.max(H, f.querySelector('.ctw-inside').offsetHeight + 31);
      });
    }
    row.style.height = H + 'px';
  }

  function shake(i) {
    var lock = root.querySelectorAll('.ctw-lock')[i];
    if (lock) {
      lock.classList.remove('is-shaking');
      void lock.offsetWidth;
      lock.classList.add('is-shaking');
    }
    flash('SEALED UNTIL ' + DAYS[S.day].name + ' ' + DAYS[S.day].date + ' · ' + HOUR_LABEL);
  }

  /* ---- Bag */
  function addItems(list, size) {
    return list.map(function (x) {
      var id = S.nextId++;
      S.bag.push({ id: id, h: x.h, c: x.c, s: size });
      return id;
    });
  }

  /* Adding needs a size. With none picked yet, ask first, then finish the add. */
  function request(list, label) {
    if (!S.size) {
      S.pending = { list: list, label: label };
      openSheet('size');
      return;
    }
    flash(label + ' · ' + S.size, addItems(list, S.size));
    bagChanged();
  }

  function pickSize(s) {
    var p = S.pending;
    S.size = s;
    closeSheet();
    if (p) flash(p.label + ' · ' + s, addItems(p.list, s));
    else flash('SIZE ' + s + ' FOR EVERY TEE YOU ADD');
    bagChanged();
  }

  function removeOne(h, c) {
    for (var k = S.bag.length - 1; k >= 0; k--) {
      if (S.bag[k].h === h && S.bag[k].c === c) { S.bag.splice(k, 1); break; }
    }
    bagChanged();
  }

  function bagChanged() {
    save();
    renderDeals();
    renderBar();
    if (S.day <= TODAY) dayDesigns(S.day).forEach(function (d, i) { renderInside(i, true); });
    layout();
    if (S.sheet) renderSheet();
  }

  function renderBar() {
    var el = ref('bar'), t = totals();
    el.hidden = !t.n;
    if (!t.n) return;
    if (!el.firstChild) {
      el.innerHTML = '<div class="ctw-bar"><div class="ctw-bar__prog" aria-hidden="true" data-ref="prog"></div>'
        + '<div class="ctw-bar__row"><div><p class="ctw-bar__head" data-ref="barhead"></p><p class="ctw-bar__nudge" aria-live="polite" data-ref="nudge"></p></div>'
        + '<button type="button" class="ctw-bar__view" data-act="bag-open">VIEW BAG</button></div></div>';
    }
    var lo = 0, hi = t.next || FREE[FREE.length - 1], segs = '';
    if (t.next) FREE.forEach(function (s) { if (s <= t.n) lo = s; });
    for (var i = lo + 1; i <= hi; i++) segs += '<i class="' + (i <= t.n ? 'is-full' : t.next && i === hi ? 'is-target' : '') + '"></i>';
    var prog = ref('prog');
    prog.innerHTML = segs;
    prog.classList.toggle('is-max', !t.next);
    ref('barhead').textContent = t.n + (t.n === 1 ? ' TEE' : ' TEES') + ' · ' + money(t.pay);
    var nudge = ref('nudge'), hot = !t.next || t.next - t.n === 1;
    nudge.textContent = !t.next ? '3 free tees: that’s the max deal'
      : t.next - t.n === 1 ? 'Your next tee is free'
        : (t.next - t.n - 1) + ' more and your ' + t.next + 'th is free';
    nudge.classList.toggle('is-hot', hot);
  }

  var toastTimer;
  function flash(text, ids) {
    S.toast = { text: text, ids: ids || [] };
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { S.toast = null; renderToast(); }, 4500);
    renderToast();
  }
  function renderToast() {
    paint(ref('toast'), S.toast ? '<div class="ctw-toast"><span>' + esc(S.toast.text) + '</span>'
      + (S.toast.ids.length ? '<button type="button" data-act="undo" data-key="undo">UNDO</button>' : '') + '</div>' : '');
  }

  /* ---- Sheets: the bag and the size picker */
  var opener = null;
  function openSheet(kind) {
    if (!S.sheet) opener = document.activeElement;
    S.sheet = kind;
    S.editItem = null;
    renderSheet();
    document.documentElement.classList.add('ctw-noscroll');
    var x = ref('sheet').querySelector('.ctw-x');
    if (x) x.focus({ preventScroll: true });
  }
  function closeSheet() {
    S.sheet = null;
    S.pending = null;
    renderSheet();
    document.documentElement.classList.remove('ctw-noscroll');
    if (opener && opener.isConnected) opener.focus({ preventScroll: true });
    opener = null;
  }

  function renderSheet() {
    var el = ref('sheet');
    if (!S.sheet) { el.innerHTML = ''; el.hidden = true; return; }
    el.hidden = false;
    var sc = el.querySelector('[data-scroll]'), top = sc ? sc.scrollTop : 0;
    paint(el, S.sheet === 'bag' ? bagHTML() : sizeHTML(), ['x']);
    sc = el.querySelector('[data-scroll]');
    if (sc) sc.scrollTop = top;
  }

  function sheetOpen(label, id) {
    return '<div class="ctw-sheet"><button type="button" class="ctw-sheet__scrim" data-act="sheet-close" tabindex="-1" aria-label="' + label + '"></button>'
      + '<section class="ctw-sheet__panel" role="dialog" aria-modal="true" aria-labelledby="' + id + '">';
  }
  var X_BTN = '<button type="button" class="ctw-x" data-act="sheet-close" data-key="x" aria-label="Close">' + SVG_X + '</button>';

  function itemHTML(b, idx) {
    var d = BY[b.h], col = COL[b.c], free = FREE.indexOf(idx + 1) >= 0, ed = S.editItem === b.id, id = ' data-id="' + b.id + '"';
    return '<li class="ctw-item"><div class="ctw-item__row">'
      + '<span class="ctw-item__img"><img src="' + img(d, b.c, 120) + '" alt="" width="52" height="52" loading="lazy"></span>'
      + '<span class="ctw-item__txt"><b>' + esc(d.title.toUpperCase()) + '</b><span>' + col.name.toUpperCase() + '</span>'
      + '<button type="button" class="ctw-item__size" data-act="item-edit"' + id + ' data-key="edit:' + b.id + '" aria-expanded="' + ed + '"'
      + ' aria-label="Size ' + b.s + '. Change the size of this tee">SIZE ' + b.s + ' · <em>CHANGE</em></button></span>'
      + '<span class="ctw-item__price' + (free ? ' is-free' : '') + '">' + (free ? 'FREE' : money(PRICE)) + '</span>'
      + '<button type="button" class="ctw-item__rm" data-act="item-remove"' + id + ' data-key="rm:' + b.id + '" aria-label="Remove ' + esc(d.title) + ' in ' + col.name + '">' + SVG_X16 + '</button>'
      + '</div>'
      + (ed ? '<div class="ctw-mini-sizes">' + SIZES.map(function (s) {
        return '<button type="button" data-act="item-size"' + id + ' data-v="' + s + '" data-key="isz:' + b.id + ':' + s + '" aria-pressed="' + (s === b.s) + '">' + s + '</button>';
      }).join('') + '</div>' : '')
      + '</li>';
  }

  function canCheckout() { return S.bag.length > 0 && S.bag.every(variantOf); }

  function bagHTML() {
    var t = totals(), n = t.n, live = canCheckout();
    var common = n && S.bag.every(function (b) { return b.s === S.bag[0].s; }) ? S.bag[0].s : null;
    var h = sheetOpen('Close the bag', 'ctw-bag-h')
      + '<div class="ctw-sheet__head"><h2 id="ctw-bag-h">YOUR BAG <small>' + n + (n === 1 ? ' TEE' : ' TEES') + '</small></h2>' + X_BTN + '</div>';
    if (n > 1) {
      h += '<div class="ctw-setall"><span>SET ALL TO</span><div class="ctw-mini-sizes">' + SIZES.map(function (s) {
        return '<button type="button" data-act="set-all" data-v="' + s + '" data-key="set:' + s + '" aria-pressed="' + (s === common) + '">' + s + '</button>';
      }).join('') + '</div></div>';
    }
    h += '<div class="ctw-sheet__scroll" data-scroll>';
    h += n ? '<ol>' + S.bag.map(itemHTML).join('') + '</ol>' : '<p class="ctw-empty">Your bag is empty. Open a case file to start.</p>';
    if (n && t.next) {
      h += '<div class="ctw-nextfree"><p>' + (t.next - n === 1 ? 'Your next tee is free, today or any day this week.'
        : (t.next - n - 1) + ' more and your ' + t.next + 'th tee is free, today or any day this week.') + '</p>'
        + '<button type="button" data-act="sheet-close" data-key="keep">KEEP LOOKING</button></div>';
    }
    h += '</div><div class="ctw-sum">'
      + '<div class="ctw-sum__row"><span>Tees</span><span>' + n + (t.f ? ' (' + t.f + ' free)' : '') + '</span></div>'
      + '<div class="ctw-sum__row"><span>Delivery</span><span>Free · ships in 2–3 days</span></div>'
      + (t.f ? '<div class="ctw-sum__row is-save"><span>You save</span><span>' + money(t.f * PRICE) + '</span></div>' : '')
      + '<div class="ctw-sum__total"><span>Total · ' + money(n ? t.pay / n : 0) + ' a tee</span><b>' + money(t.pay) + '</b></div>'
      + '<button type="button" class="ctw-checkout" data-act="checkout" data-key="checkout"' + (live ? '' : ' aria-disabled="true"') + '>CHECKOUT</button>'
      + (n && !live ? '<p class="ctw-sum__note">Preview: checkout opens when the tees go live.</p>' : '')
      + '<div class="ctw-pay"><span>SHOP PAY</span><span>APPLE PAY</span><span>GOOGLE PAY</span><span>CARD</span></div>'
      + '<p class="ctw-sum__small">Free size swaps and easy returns within 14 days. <a href="' + esc(DATA.returnsUrl || '/pages/returns') + '">Returns desk</a></p>'
      + '</div></section></div>';
    return h;
  }

  function sizeHTML() {
    var sub = 'Every tee you add comes in this size.';
    if (S.pending) {
      var p = S.pending.list, d = BY[p[0].h];
      sub = p.length > 1 ? 'Pick one and we’ll add all ' + p.length + ' colours of the ' + d.title + '.'
        : 'Pick one and we’ll add the ' + COL[p[0].c].name.toLowerCase() + ' ' + d.title + '.';
    }
    var h = sheetOpen('Close', 'ctw-size-h')
      + '<div class="ctw-sheet__head"><h2 id="ctw-size-h">PICK YOUR SIZE</h2>' + X_BTN + '</div>'
      + '<div class="ctw-size" data-scroll><p class="ctw-size__sub">' + esc(sub) + '</p>'
      + '<div class="ctw-tags" role="radiogroup" aria-labelledby="ctw-size-h">' + SIZES.map(function (s) {
        return '<button type="button" class="ctw-tag" role="radio" aria-checked="' + (s === S.size) + '" data-act="size-pick" data-v="' + s + '" data-key="pick:' + s + '"><span>' + s + '</span></button>';
      }).join('') + '</div>'
      + '<p class="ctw-size__fit">Regular fit, true to size: take your usual size. 200gsm. You can change any single tee in the bag.</p>'
      + '<button type="button" class="ctw-chartbtn" data-act="chart" data-key="chart" aria-expanded="' + S.chart + '">' + SVG_RULER + '<span>SIZE CHART</span></button>';
    if (S.chart) {
      h += '<div class="ctw-chart"><div class="ctw-chart__top"><span>' + (S.unit === 'in' ? 'Inches, measured flat' : 'Centimetres, measured flat') + '</span>'
        + '<span class="ctw-chart__units">' + [['cm', 'CM'], ['in', 'IN']].map(function (u) {
          return '<button type="button" data-act="unit" data-v="' + u[0] + '" data-key="unit:' + u[0] + '" aria-pressed="' + (S.unit === u[0]) + '">' + u[1] + '</button>';
        }).join('') + '</span></div>'
        + '<div class="ctw-chart__row is-head"><span>SIZE</span><span>CHEST</span><span>LENGTH</span><span>SHOULDER</span></div>'
        + SIZES.map(function (s) {
          return '<div class="ctw-chart__row' + (s === S.size ? ' is-on' : '') + '"><b>' + s + '</b><span>' + fmt(FIT[s][0] / 2) + '</span><span>' + fmt(FIT[s][1]) + '</span><span>' + fmt(FIT[s][2]) + '</span></div>';
        }).join('') + '</div>';
    }
    return h + '</div></section></div>';
  }

  function checkout() {
    if (!canCheckout()) {
      flash(S.bag.length ? 'PREVIEW · CHECKOUT OPENS WHEN THE TEES GO LIVE' : 'YOUR BAG IS EMPTY');
      return;
    }
    var qty = {};
    S.bag.forEach(function (b) { var id = variantOf(b); qty[id] = (qty[id] || 0) + 1; });
    var base = (window.Shopify && window.Shopify.routes && window.Shopify.routes.root) || '/';
    fetch(base + 'cart/add.js', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ items: Object.keys(qty).map(function (id) { return { id: Number(id), quantity: qty[id] }; }) })
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      S.bag = [];
      save();
      location.href = base + 'checkout';
    }).catch(function () { flash('COULDN’T REACH THE CHECKOUT. TRY AGAIN'); });
  }

  function submitSms() {
    var input = root.querySelector('#ctw-sms-input');
    var digits = (input ? input.value : '').replace(/\D/g, '');
    S.sms.value = input ? input.value : '';
    if (digits.length < 10 || digits.length > 12) {
      S.sms.error = 'Enter a UK mobile number, like 07700 900123.';
      renderCount();
      var again = root.querySelector('#ctw-sms-input');
      if (again) again.focus();
      return;
    }
    var d = cdTarget();
    S.sms.open = false;
    S.sms.error = '';
    S.sms.value = '';
    if (DATA.smsLive) {
      S.sms.done[d] = true;
      save();
      flash('WE’LL TEXT YOU AT ' + HOUR_LABEL + ' ' + DAYS[d].name);
    } else {
      flash('PREVIEW · TEXTS AREN’T SWITCHED ON YET');
    }
    renderCount();
  }

  /* ---- Events */
  function act(name, el) {
    var i = Number(el.getAttribute('data-i')), v = el.getAttribute('data-v'), id = Number(el.getAttribute('data-id'));
    var d = S.day <= TODAY ? dayDesigns(S.day)[i] : null;
    switch (name) {
      case 'open':
        S.open = i + 1;
        applyOpen();
        var win = root.querySelector('[data-inside="' + i + '"] .ctw-win__btn');
        if (win) win.focus({ preventScroll: true });
        break;
      case 'close':
        S.open = 0;
        applyOpen();
        var cover = root.querySelectorAll('.ctw-files .ctw-cover')[i];
        if (cover) cover.focus({ preventScroll: true });
        break;
      case 'view':
        S.view[d.handle] = Number(v);
        renderInside(i);
        break;
      case 'shot':
        S.shot[d.handle] = v;
        renderInside(i);
        break;
      case 'add':
      case 'plus':
        request([{ h: d.handle, c: colourOf(d) }], 'ADDED · ' + COL[colourOf(d)].name.toUpperCase());
        break;
      case 'minus':
        removeOne(d.handle, colourOf(d));
        break;
      case 'addall':
        var missing = COLS.filter(function (cc) { return !inBag(d.handle, cc).length; });
        request(missing.map(function (cc) { return { h: d.handle, c: cc }; }), missing.length + ' ADDED');
        break;
      case 'size-open':
        S.pending = null;
        openSheet('size');
        break;
      case 'size-pick':
        pickSize(v);
        break;
      case 'chart':
        S.chart = !S.chart;
        renderSheet();
        break;
      case 'unit':
        S.unit = v;
        renderSheet();
        break;
      case 'bag-open':
        openSheet('bag');
        break;
      case 'sheet-close':
        closeSheet();
        break;
      case 'set-all':
        S.size = v;
        S.bag.forEach(function (b) { b.s = v; });
        bagChanged();
        break;
      case 'item-edit':
        S.editItem = S.editItem === id ? null : id;
        renderSheet();
        break;
      case 'item-size':
        S.bag.forEach(function (b) { if (b.id === id) b.s = v; });
        S.editItem = null;
        bagChanged();
        break;
      case 'item-remove':
        S.bag = S.bag.filter(function (b) { return b.id !== id; });
        bagChanged();
        break;
      case 'undo':
        var ids = S.toast ? S.toast.ids : [];
        S.bag = S.bag.filter(function (b) { return ids.indexOf(b.id) < 0; });
        S.toast = null;
        clearTimeout(toastTimer);
        renderToast();
        bagChanged();
        break;
      case 'checkout':
        checkout();
        break;
      case 'day':
        S.day = Number(v);
        S.open = 0;
        renderDays();
        renderCount();
        renderStage();
        break;
      case 'shake':
        shake(i);
        break;
      case 'sms-toggle':
        S.sms.open = !S.sms.open;
        S.sms.error = '';
        renderCount();
        var input = S.sms.open && root.querySelector('#ctw-sms-input');
        if (input) input.focus();
        break;
      case 'sms-submit':
        submitSms();
        break;
    }
  }

  root.addEventListener('click', function (e) {
    var el = e.target.closest('[data-act]');
    if (el && root.contains(el)) act(el.getAttribute('data-act'), el);
  });
  root.addEventListener('input', function (e) {
    if (e.target.id === 'ctw-sms-input') S.sms.value = e.target.value;
  });
  root.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.id === 'ctw-sms-input') { e.preventDefault(); submitSms(); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      if (S.sheet) closeSheet();
      else if (S.open) act('close', { getAttribute: function (a) { return a === 'data-i' ? String(S.open - 1) : null; } });
      return;
    }
    if (e.key !== 'Tab' || !S.sheet) return;
    var f = ref('sheet').querySelectorAll('.ctw-sheet__panel button, .ctw-sheet__panel a[href]');
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1], a = document.activeElement;
    if (!ref('sheet').contains(a)) { e.preventDefault(); first.focus(); }
    else if (e.shiftKey && a === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
  });

  var raf = 0;
  window.addEventListener('resize', function () {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(layout);
  });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(); });

  function renderAll() {
    var sim = ref('sim');
    if (SIM && sim) {
      sim.hidden = false;
      sim.textContent = simDay
        ? 'PREVIEW CLOCK · ' + DAYS[simDay - 1].long + ', JUST AFTER THE ' + HOUR_LABEL + ' DROP'
        : 'PREVIEW CLOCK · BEFORE THE WEEK STARTS';
    }
    renderCount();
    renderDeals();
    renderDays();
    renderStage();
    renderBar();
    renderToast();
    renderSheet();
  }

  renderAll();
  setInterval(tick, 1000);
})();
