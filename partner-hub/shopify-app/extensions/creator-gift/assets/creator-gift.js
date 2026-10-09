/*
 * CROOKS creator gift. When a creator code from the Partner Hub is on the
 * cart and the bag holds at least one CROOKS piece, a 1-pair pack of
 * MOTIONTEC socks goes in at £0 (the code's Buy X Get Y discount makes it
 * free). Rules come from the Hub through the app metafield printed by
 * blocks/creator-gift.liquid. See partner-hub/CREATOR_GIFT.md.
 *
 * Plain JS, no dependencies. reconcile() is pure and unit-tested; the rest
 * runs its actions against the cart API and Horizon's cart drawer.
 */
(function (root) {
  'use strict';

  var SOURCE = 'crooks-gift';
  var PROP = '_crooks_gift';

  function upper(s) {
    return String(s == null ? '' : s).trim().toUpperCase();
  }

  function isGift(item) {
    return !!(item && item.properties && item.properties[PROP]);
  }

  function ruleCodes(rules) {
    return ((rules && rules.codes) || []).map(upper).filter(Boolean);
  }

  function giftVariantIds(rules) {
    return ((rules && rules.gift && rules.gift.variantIds) || []).map(Number).filter(Boolean);
  }

  /** What the cart looks like from the gift's point of view. */
  function analyse(cart, rules) {
    var codes = ruleCodes(rules);
    var excluded = (rules && rules.gift && rules.gift.excludeProductTypes) || [];
    var giftCode = null;
    var discounts = (cart && cart.discount_codes) || [];
    for (var i = 0; i < discounts.length; i++) {
      var c = upper(discounts[i] && discounts[i].code);
      if (codes.indexOf(c) !== -1) {
        giftCode = c;
        break;
      }
    }
    var items = (cart && cart.items) || [];
    return {
      codes: codes,
      giftCode: giftCode,
      giftLines: items.filter(isGift),
      qualifying: items.filter(function (it) {
        return !isGift(it) && excluded.indexOf(it.product_type) === -1;
      }),
    };
  }

  /**
   * The rules table in CREATOR_GIFT.md section 3, as a list of actions:
   *   { type: 'add', code, variantIds }   add the first in-stock gift variant
   *   { type: 'remove', key }             remove a line
   *   { type: 'setQty', key, quantity }   set a line's quantity
   */
  function reconcile(cart, rules) {
    var a = analyse(cart, rules);
    var variantIds = giftVariantIds(rules);
    var actions = [];
    var removeAll = function () {
      a.giftLines.forEach(function (l) {
        actions.push({ type: 'remove', key: l.key });
      });
    };

    if (a.giftLines.length && (!a.giftCode || !a.qualifying.length)) {
      removeAll();
      return actions;
    }
    if (a.giftCode && a.qualifying.length && !a.giftLines.length) {
      if (variantIds.length) actions.push({ type: 'add', code: a.giftCode, variantIds: variantIds });
      return actions;
    }
    if (a.giftLines.length) {
      var first = a.giftLines[0];
      if (variantIds.length && variantIds.indexOf(Number(first.variant_id)) === -1) {
        // The gift changed in the Hub: swap the old one out.
        removeAll();
        actions.push({ type: 'add', code: a.giftCode, variantIds: variantIds });
        return actions;
      }
      a.giftLines.slice(1).forEach(function (l) {
        actions.push({ type: 'remove', key: l.key });
      });
      if (Number(first.quantity) > 1) actions.push({ type: 'setQty', key: first.key, quantity: 1 });
    }
    return actions;
  }

  /**
   * Runs actions through `api` ({ add(variantId, code), change(key, qty) },
   * each resolving to { ok, status }). Adds try each variant in order and move
   * on when Shopify says it's sold out (422).
   */
  function applyActions(actions, api) {
    var result = { soldOut: false, changed: false };
    var chain = Promise.resolve();
    actions.forEach(function (action) {
      chain = chain.then(function () {
        if (action.type === 'remove' || action.type === 'setQty') {
          return api.change(action.key, action.type === 'remove' ? 0 : action.quantity).then(function (r) {
            if (r.ok) result.changed = true;
          });
        }
        if (action.type === 'add') {
          var i = 0;
          var next = function () {
            if (i >= action.variantIds.length) {
              result.soldOut = true;
              return undefined;
            }
            var id = action.variantIds[i++];
            return api.add(id, action.code).then(function (r) {
              if (r.ok) {
                result.changed = true;
                result.addedVariantId = id;
                return undefined;
              }
              if (r.status === 422) return next();
              throw new Error('Adding the free socks failed (' + r.status + ')');
            });
          };
          return next();
        }
        return undefined;
      });
    });
    return chain.then(function () {
      return result;
    });
  }

  /** The other gift colour for the swap link, or null. */
  function swapTarget(cart, rules) {
    var a = analyse(cart, rules);
    if (!a.giftLines.length) return null;
    var current = Number(a.giftLines[0].variant_id);
    var variants = (rules && rules.gift && rules.gift.variants) || [];
    for (var i = 0; i < variants.length; i++) {
      if (Number(variants[i].id) !== current && variants[i].handle) return variants[i];
    }
    return null;
  }

  /** The message under/above the code box for this cart. */
  function message(cart, rules, soldOut) {
    var a = analyse(cart, rules);
    var label = (rules && rules.gift && rules.gift.label) || 'socks';
    if (!a.codes.length) return null;
    if (a.giftCode && a.giftLines.length) return { where: 'below', text: 'Free ' + label + ' added with ' + a.giftCode, swap: true };
    if (a.giftCode && soldOut) return { where: 'below', text: 'Free socks are sold out right now' };
    if (a.giftCode && !a.qualifying.length) {
      return { where: 'below', text: 'Add any CROOKS piece to your bag to unlock free socks with ' + a.giftCode + '.' };
    }
    if (!a.giftCode) return { where: 'above', text: 'Creator code? Enter it here for free socks.' };
    return null;
  }

  var api = { upper: upper, analyse: analyse, reconcile: reconcile, applyActions: applyActions, swapTarget: swapTarget, message: message };
  root.CrooksGift = api;

  if (typeof document === 'undefined' || typeof window === 'undefined') return;

  // ---------------------------------------------------------------- browser

  var rules = null;
  try {
    var el = document.getElementById('crooks-gift-rules');
    rules = el ? JSON.parse(el.textContent || 'null') : null;
  } catch (e) {
    rules = null;
  }
  if (!rules || !Array.isArray(rules.codes)) rules = { codes: [], gift: { variantIds: [] } };

  var rootUrl = (window.Shopify && window.Shopify.routes && window.Shopify.routes.root) || '/';
  var lastCart = null;
  var soldOut = false;
  var queue = Promise.resolve();
  var timer = null;
  var availability = {};

  function post(path, body) {
    return fetch(rootUrl + path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      return { ok: r.ok, status: r.status };
    });
  }

  var cartApi = {
    add: function (variantId, code) {
      var properties = {};
      properties[PROP] = code;
      return post('cart/add.js', { items: [{ id: variantId, quantity: 1, properties: properties }] });
    },
    change: function (key, quantity) {
      return post('cart/change.js', { id: key, quantity: quantity });
    },
  };

  function getCart() {
    return fetch(rootUrl + 'cart.js', { credentials: 'same-origin', headers: { Accept: 'application/json' } }).then(function (r) {
      return r.json();
    });
  }

  function announce(cart) {
    document.dispatchEvent(
      new CustomEvent('cart:update', {
        bubbles: true,
        detail: { resource: cart, sourceId: SOURCE, data: { source: SOURCE, itemCount: cart.item_count } },
      })
    );
  }

  /** Brings the cart in line with the rules, then redraws. Serialised. */
  function run() {
    queue = queue
      .then(getCart)
      .then(function (cart) {
        var actions = reconcile(cart, rules);
        if (!actions.length) return cart;
        return applyActions(actions, cartApi).then(function (res) {
          soldOut = res.soldOut;
          return getCart().then(function (fresh) {
            if (res.changed) announce(fresh);
            return fresh;
          });
        });
      })
      .then(function (cart) {
        if (!analyse(cart, rules).giftCode) soldOut = false;
        lastCart = cart;
        render();
      })
      .catch(function (e) {
        console.warn('[creator-gift]', e);
      });
    return queue;
  }

  function schedule(delay) {
    clearTimeout(timer);
    timer = setTimeout(run, delay == null ? 120 : delay);
  }

  function checkAvailable(target) {
    var hit = availability[target.handle];
    if (hit && Date.now() - hit.at < 60000) return Promise.resolve(hit.ids.indexOf(Number(target.id)) !== -1);
    return fetch(rootUrl + 'products/' + target.handle + '.js', { headers: { Accept: 'application/json' } })
      .then(function (r) {
        return r.ok ? r.json() : { variants: [] };
      })
      .then(function (p) {
        var ids = (p.variants || []).filter(function (v) { return v.available; }).map(function (v) { return Number(v.id); });
        availability[target.handle] = { at: Date.now(), ids: ids };
        return ids.indexOf(Number(target.id)) !== -1;
      })
      .catch(function () {
        return false;
      });
  }

  function swap() {
    var target = lastCart && swapTarget(lastCart, rules);
    if (!target) return;
    queue = queue
      .then(getCart)
      .then(function (cart) {
        var a = analyse(cart, rules);
        var line = a.giftLines[0];
        if (!line || !a.giftCode) return cart;
        var oldId = Number(line.variant_id);
        return cartApi
          .change(line.key, 0)
          .then(function () {
            return cartApi.add(Number(target.id), a.giftCode);
          })
          .then(function (r) {
            return r.ok ? r : cartApi.add(oldId, a.giftCode);
          })
          .then(getCart)
          .then(function (fresh) {
            announce(fresh);
            return fresh;
          });
      })
      .then(function (cart) {
        lastCart = cart;
        render();
      })
      .catch(function (e) {
        console.warn('[creator-gift]', e);
      });
  }

  function render() {
    if (!lastCart) return;
    var m = message(lastCart, rules, soldOut);
    var target = swapTarget(lastCart, rules);
    var components = document.querySelectorAll('cart-discount-component');
    for (var i = 0; i < components.length; i++) draw(components[i], m, target);
  }

  function draw(component, m, target) {
    var key = m ? m.where + '|' + m.text + '|' + (m.swap && target ? target.id : '') : '';
    var existing = component.querySelector(':scope > .crooks-gift');
    if (existing && existing.getAttribute('data-key') === key) return;
    if (existing) existing.remove();
    if (!m) return;

    var box = document.createElement('div');
    box.className = 'crooks-gift crooks-gift--' + m.where + ' cart-primary-typography';
    box.setAttribute('data-key', key);
    box.setAttribute('role', 'status');
    var p = document.createElement('p');
    p.className = 'crooks-gift__text';
    p.textContent = m.text;
    box.appendChild(p);

    if (m.swap && target) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'crooks-gift__swap button-unstyled';
      btn.textContent = 'Swap to ' + (target.name || 'the other colour');
      btn.hidden = true;
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        swap();
      });
      box.appendChild(btn);
      checkAvailable(target).then(function (ok) {
        btn.hidden = !ok;
      });
    }

    var content = component.querySelector('.cart-discount__content');
    if (m.where === 'above' && content) component.insertBefore(box, content);
    else if (content && content.nextSibling) component.insertBefore(box, content.nextSibling);
    else component.appendChild(box);
  }

  // The code box. Horizon applies a code straight away and clears it if it
  // isn't applying yet, so a gift code adds the socks first, then lets
  // Horizon apply it (it applies, because the socks are now in the bag).
  window.addEventListener(
    'submit',
    function (event) {
      var form = event.target;
      if (!(form instanceof HTMLFormElement) || !form.classList.contains('cart-discount__form')) return;
      if (form.dataset.crooksGiftReady === '1') {
        delete form.dataset.crooksGiftReady;
        schedule(900);
        return;
      }
      var input = form.querySelector('input[name="discount"]');
      var code = upper(input && input.value);
      if (!code || ruleCodes(rules).indexOf(code) === -1) return;

      event.preventDefault();
      event.stopImmediatePropagation();
      queue = queue
        .then(getCart)
        .then(function (cart) {
          var a = analyse(cart, rules);
          if (a.qualifying.length && !a.giftLines.length) {
            return applyActions([{ type: 'add', code: code, variantIds: giftVariantIds(rules) }], cartApi).then(function (res) {
              soldOut = res.soldOut;
            });
          }
          return undefined;
        })
        .catch(function (e) {
          console.warn('[creator-gift]', e);
        })
        .then(function () {
          form.dataset.crooksGiftReady = '1';
          form.requestSubmit();
        });
    },
    true
  );

  ['cart:update', 'discount:update'].forEach(function (name) {
    document.addEventListener(name, function (event) {
      if (event.detail && event.detail.sourceId === SOURCE) return;
      schedule();
    });
  });

  // Horizon re-renders the cart sections; put the message back afterwards.
  var drawPending = false;
  new MutationObserver(function () {
    if (drawPending) return;
    drawPending = true;
    requestAnimationFrame(function () {
      drawPending = false;
      render();
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { schedule(0); });
  else schedule(0);
})(typeof globalThis !== 'undefined' ? globalThis : this);
