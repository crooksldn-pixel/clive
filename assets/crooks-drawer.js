/*
 * CROOKSLDN — menu drawer.
 * Hand-built: no library, no Radix, no Vaul. Vanilla ES2019.
 *
 * Behaviour required of a modal dialog:
 *   - role="dialog" + aria-modal="true" (set in markup)
 *   - focus moves into the drawer on open
 *   - Tab / Shift+Tab are trapped inside it
 *   - Escape closes
 *   - focus returns to the trigger on close
 *   - body scroll is locked while open
 *   - the rest of the page is inert to assistive tech (aria-hidden on siblings)
 */
(function () {
  'use strict';

  var FOCUSABLE = [
    'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
    'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  function focusable(root) {
    var out = [];
    var nodes = root.querySelectorAll(FOCUSABLE);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      // offsetParent is null for display:none; also skip zero-size controls
      if (el.offsetWidth || el.offsetHeight || el.getClientRects().length) out.push(el);
    }
    return out;
  }

  function init(header) {
    var trigger = header.querySelector('[data-crk-drawer-open]');
    var drawer = header.querySelector('[data-crk-drawer]');
    if (!trigger || !drawer) return;

    var closers = drawer.querySelectorAll('[data-crk-drawer-close]');
    var openLabel = trigger.getAttribute('data-crk-label-open') || 'MENU';
    var closeLabel = trigger.getAttribute('data-crk-label-close') || 'CLOSE';
    var lastFocused = null;
    var hidden = [];

    function siblingsHidden(on) {
      // Hide everything outside the header from assistive tech while open.
      if (on) {
        var kids = document.body.children;
        for (var i = 0; i < kids.length; i++) {
          var el = kids[i];
          if (el === header || el.contains(header)) continue;
          if (el.hasAttribute('aria-hidden')) continue;
          el.setAttribute('aria-hidden', 'true');
          hidden.push(el);
        }
      } else {
        for (var j = 0; j < hidden.length; j++) hidden[j].removeAttribute('aria-hidden');
        hidden = [];
      }
    }

    /* The attract board is loaded on demand, not on every page — see the note in
       crooks-header.liquid. Injected once, on the first open; the board's own
       auto-mount catches it because readyState is already 'complete' by then,
       and the explicit mountAll covers the case where it was loaded earlier. */
    var boardRequested = false;
    function loadBoard() {
      if (boardRequested) return;
      var src = header.getAttribute('data-crk-board-src');
      var canvas = drawer.querySelector('[data-crk-board]');
      if (!src || !canvas) return;
      boardRequested = true;
      if (window.CrooksBoard) { window.CrooksBoard.mountAll(drawer); return; }
      var tag = document.createElement('script');
      tag.src = src;
      tag.defer = true;
      tag.addEventListener('load', function () {
        if (window.CrooksBoard) window.CrooksBoard.mountAll(drawer);
      });
      document.head.appendChild(tag);
    }

    function open() {
      if (!drawer.hidden) return;
      loadBoard();
      lastFocused = document.activeElement;
      drawer.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      trigger.textContent = closeLabel;
      document.documentElement.classList.add('crk-scroll-locked');
      document.body.classList.add('crk-scroll-locked');
      siblingsHidden(true);
      var f = focusable(drawer);
      (f[0] || drawer).focus();
      document.addEventListener('keydown', onKeydown, true);
    }

    function close() {
      if (drawer.hidden) return;
      drawer.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      trigger.textContent = openLabel;
      document.documentElement.classList.remove('crk-scroll-locked');
      document.body.classList.remove('crk-scroll-locked');
      siblingsHidden(false);
      document.removeEventListener('keydown', onKeydown, true);
      if (lastFocused && lastFocused.focus) lastFocused.focus();
    }

    function onKeydown(e) {
      if (e.key === 'Escape' || e.key === 'Esc') {
        e.preventDefault();
        close();
        return;
      }
      if (e.key !== 'Tab') return;
      var f = focusable(drawer);
      if (!f.length) { e.preventDefault(); return; }
      var first = f[0], last = f[f.length - 1];
      var active = document.activeElement;
      // Wrap in both directions, and pull focus back if it escaped the drawer.
      if (e.shiftKey) {
        if (active === first || !drawer.contains(active)) { e.preventDefault(); last.focus(); }
      } else if (active === last || !drawer.contains(active)) {
        e.preventDefault();
        first.focus();
      }
    }

    trigger.addEventListener('click', function () {
      if (drawer.hidden) open(); else close();
    });
    for (var i = 0; i < closers.length; i++) {
      closers[i].addEventListener('click', close);
    }

    /* Another layer asking for the floor. The app-install sheet opens from a
       button inside this drawer; while the drawer is open it aria-hides every
       sibling and traps focus, so the sheet would open hidden from assistive
       tech with focus pulled back here. It closes this first. */
    document.addEventListener('crk:closedrawers', close);

    /* Submenus. The markup renders them open so it is never dependent on this
       file to be truthful; they are closed here, before the drawer has ever
       been shown, so nobody watches one collapse. Seven collection links under
       SHOP were most of the drawer's height. */
    var toggles = drawer.querySelectorAll('[data-crk-submenu-toggle]');
    for (var t = 0; t < toggles.length; t++) {
      (function (btn) {
        var sub = document.getElementById(btn.getAttribute('aria-controls'));
        if (!sub) return;
        var say = btn.querySelector('[data-crk-submenu-say]');

        function set(open) {
          btn.setAttribute('aria-expanded', open ? 'true' : 'false');
          sub.hidden = !open;
          if (say) {
            var next = open ? say.getAttribute('data-crk-close-label') : say.getAttribute('data-crk-open-label');
            if (next) say.textContent = next;
          }
        }
        btn.addEventListener('click', function () {
          set(btn.getAttribute('aria-expanded') !== 'true');
        });
        set(false);
      })(toggles[t]);
    }

    // The drawer starts hidden; without JS it never opens, which is why the
    // section also renders a <noscript> menu.
    drawer.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    trigger.hidden = false;
  }

  function mountAll(scope) {
    var root = scope && scope.querySelectorAll ? scope : document;
    var nodes = root.querySelectorAll('[data-crk-section="header"]');
    for (var i = 0; i < nodes.length; i++) {
      if (!nodes[i]._crkDrawer) { nodes[i]._crkDrawer = true; init(nodes[i]); }
    }
    if (root.matches && root.matches('[data-crk-section="header"]') && !root._crkDrawer) {
      root._crkDrawer = true; init(root);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { mountAll(document); });
  } else {
    mountAll(document);
  }
  document.addEventListener('shopify:section:load', function (e) { mountAll(e.target); });
})();
