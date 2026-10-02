/*
 * CROOKSLDN — "get the app".
 *
 * The store installs to a phone's home screen as a web app. This file decides
 * whether to offer that at all, and if so which instructions to show.
 *
 * Already installed? Nothing is offered. A shopper who opened the store from
 * its home-screen icon does not need a button telling them to install it.
 *
 * Which steps:
 *   native   Chromium fired beforeinstallprompt, so one INSTALL button works.
 *            On this store it usually will not fire: Chrome's automatic prompt
 *            needs a service worker controlling the page, and Shopify will not
 *            let a theme serve one from the shop's root. Supported anyway, so
 *            it starts working the day that changes.
 *   ios      Share -> Add to Home Screen. There is no programmatic install on
 *            iOS; the steps are the only route.
 *   android  Browser menu -> Install app. Works from the manifest alone.
 *   desktop  Point them at their phone.
 */
(function () {
  'use strict';

  var sheet = document.querySelector('[data-crk-appsheet]');
  var triggers = document.querySelectorAll('[data-crk-app-open]');
  if (!sheet || !triggers.length) return;

  function installed() {
    try {
      if (window.matchMedia('(display-mode: standalone)').matches) return true;
      if (window.matchMedia('(display-mode: fullscreen)').matches) return true;
    } catch (e) {}
    return window.navigator.standalone === true;   /* iOS Safari */
  }
  if (installed()) return;   /* triggers stay hidden */

  var ua = navigator.userAgent || '';
  /* iPadOS 13+ reports itself as a Mac; the touch points give it away. */
  var isIOS = /iPad|iPhone|iPod/.test(ua) ||
              (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var isAndroid = /Android/i.test(ua);

  var deferred = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferred = e;
  });
  window.addEventListener('appinstalled', function () {
    deferred = null;
    for (var i = 0; i < triggers.length; i++) triggers[i].hidden = true;
    close();
  });

  for (var i = 0; i < triggers.length; i++) {
    triggers[i].hidden = false;
    triggers[i].addEventListener('click', open);
  }

  var panel = sheet.querySelector('[data-crk-appsheet-panel]');
  var opener = null;
  var isOpen = false;

  function pick() {
    if (deferred) return 'native';
    if (isIOS) return 'ios';
    if (isAndroid) return 'android';
    return 'desktop';
  }

  function onKey(e) {
    if (!isOpen) return;
    if (e.key === 'Escape') { e.preventDefault(); close(); return; }
    if (e.key !== 'Tab') return;
    var f = panel.querySelectorAll('button:not([hidden]), a[href]');
    var vis = Array.prototype.filter.call(f, function (el) { return el.offsetParent !== null; });
    if (!vis.length) return;
    var first = vis[0], last = vis[vis.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  function open(e) {
    if (e) e.preventDefault();
    if (isOpen) return;
    isOpen = true;

    /* If the menu drawer is open underneath, close it first — it aria-hides
       everything outside itself and traps focus. Done before reading the
       active element, because closing it moves focus to the MENU button,
       which is where focus should return when this sheet closes: the GET THE
       APP button that opened it is inside a drawer that is no longer shown. */
    try { document.dispatchEvent(new CustomEvent('crk:closedrawers')); } catch (x) {}
    opener = document.activeElement;

    var which = pick();
    var blocks = sheet.querySelectorAll('[data-crk-app-steps]');
    for (var b = 0; b < blocks.length; b++) {
      blocks[b].hidden = blocks[b].getAttribute('data-crk-app-steps') !== which;
    }

    sheet.hidden = false;
    window.requestAnimationFrame(function () { sheet.setAttribute('data-crk-open', 'true'); });
    document.documentElement.style.overflow = 'hidden';
    document.addEventListener('keydown', onKey, true);
    var closeBtn = sheet.querySelector('.crk-appsheet__close');
    if (closeBtn) closeBtn.focus();
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    sheet.removeAttribute('data-crk-open');
    document.documentElement.style.overflow = '';
    document.removeEventListener('keydown', onKey, true);
    var wait = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 240;
    window.setTimeout(function () { if (!isOpen) sheet.hidden = true; }, wait);
    if (opener && typeof opener.focus === 'function') opener.focus();
    opener = null;
  }

  sheet.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-crk-app-close]')) { e.preventDefault(); close(); }
  });

  var nativeBtn = sheet.querySelector('[data-crk-app-native]');
  if (nativeBtn) {
    nativeBtn.addEventListener('click', function () {
      if (!deferred) return;
      var ev = deferred;
      deferred = null;
      ev.prompt();
      if (ev.userChoice && ev.userChoice.then) {
        ev.userChoice.then(function () { close(); }, function () { close(); });
      } else {
        close();
      }
    });
  }
})();
