/*
 * CROOKS Returns desk. Find the order, choose what goes back, pick a deal, confirm.
 * Every offer, price and rule comes from the returns service; this file only presents what it
 * is told and sends back what the customer chose. Swaps and store credit lead; a refund is
 * always offered beside them with its cost shown plainly.
 */
(function () {
  if (customElements.get('returns-portal')) return;

  var STORE_KEY = 'crooks_returns_session';
  var NOTE_REASONS = ['faulty', 'not_as_described', 'wrong_item'];
  var FIT_REASONS = ['too_small', 'too_big'];
  var STATUS_NAME = {
    requested: 'Under review', awaiting_label: 'Approved', awaiting_shipment: 'Ready to post',
    in_transit: 'On its way', received: 'Arrived', completed: 'Done', declined: 'Declined', cancelled: 'Cancelled',
  };
  var STATUS_STEP = { requested: 1, awaiting_label: 2, awaiting_shipment: 3, in_transit: 4, received: 5, completed: 6 };
  // Shorter names for the reason chips; the server's own labels stay on the receipt.
  var CHIP = {
    too_small: 'Too small', too_big: 'Too big', changed_mind: 'Changed my mind',
    not_as_described: 'Not as pictured', faulty: 'Faulty', wrong_item: 'Wrong item',
  };
  var TICK = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="square" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"></path></svg>';

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function pence(money) {
    var n = parseFloat(String(money || '').replace(/[^0-9.\-]/g, ''));
    return isNaN(n) ? 0 : Math.round(n * 100);
  }
  function gbp(p) {
    return (p < 0 ? '-£' : '£') + (Math.abs(p) / 100).toFixed(2);
  }
  function remember(session) {
    try {
      if (session) sessionStorage.setItem(STORE_KEY, session);
      else sessionStorage.removeItem(STORE_KEY);
    } catch (e) {}
  }
  function recall() {
    try {
      return sessionStorage.getItem(STORE_KEY);
    } catch (e) {
      return null;
    }
  }
  function initials(title) {
    return String(title || '').split(/\s+/).map(function (w) { return w.charAt(0); }).join('').slice(0, 2).toUpperCase();
  }

  class ReturnsPortal extends HTMLElement {
    connectedCallback() {
      this.endpoint = (this.dataset.endpoint || '/apps/returns/api').replace(/\/$/, '');
      this.contact = this.dataset.contact || '/';
      this.state = { selected: {}, exchange: {} };
      this.addEventListener('submit', this.onSubmit.bind(this));
      this.addEventListener('click', this.onClick.bind(this));
      this.addEventListener('input', this.onInput.bind(this));
      var saved = recall();
      if (saved) this.resume(saved);
      else this.renderFind();
    }

    /* ------------------------------------------------------------------ transport */

    async post(path, body) {
      var res;
      try {
        res = await fetch(this.endpoint + path, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify(body),
        });
      } catch (e) {
        throw new Error('We could not reach the returns desk. Check your connection and try again.');
      }
      var data = {};
      try {
        data = await res.json();
      } catch (e) {}
      if (!res.ok) {
        if (res.status === 401) remember(null);
        var detail = data && data.detail;
        if (Array.isArray(detail)) detail = 'Please check the details and try again.';
        throw new Error(detail || 'Something went wrong. Please try again.');
      }
      return data;
    }

    async busy(button, busyText, work) {
      var error = this.querySelector('.rd-error');
      if (error) error.textContent = '';
      var label = button ? button.innerHTML : '';
      if (button) {
        button.disabled = true;
        button.setAttribute('data-busy', '');
        if (busyText) button.textContent = busyText;
      }
      try {
        await work();
      } catch (e) {
        error = this.querySelector('.rd-error');
        if (error) {
          error.textContent = e.message;
          error.focus();
        }
        var shake = this.querySelector('[data-shake]');
        if (shake) {
          shake.classList.remove('rd-shake');
          void shake.offsetWidth;
          shake.classList.add('rd-shake');
        }
        if (/session has expired/i.test(e.message)) setTimeout(this.renderFind.bind(this), 1600);
      } finally {
        if (button && button.isConnected) {
          button.disabled = false;
          button.removeAttribute('data-busy');
          button.innerHTML = label;
        }
      }
    }

    async resume(session) {
      try {
        var data = await this.post('/order', { session: session });
        this.state.session = session;
        this.state.order = data;
        this.renderStart();
      } catch (e) {
        remember(null);
        this.renderFind();
      }
    }

    /* ------------------------------------------------------------------ frame */

    // A re-render of the same screen (a tick, a chip) must not replay the entrance or pull
    // focus away from the control in use.
    still(view) {
      this.sameView = this.view === view;
      this.view = view;
      return this.sameView ? ' data-still' : '';
    }

    frame(view, step, parts) {
      var progress = '';
      if (step != null) {
        progress = '<div class="rd-progress" aria-label="Step ' + (step + 1) + ' of 4">' + [0, 1, 2, 3].map(function (i) {
          return '<span' + (i < step ? ' data-done' : '') + (i === step ? ' data-current' : '') + '></span>';
        }).join('') + '</div>';
      }
      var head = '<div class="rd-head">' + (parts.kicker ? '<p class="rd-kicker">' + parts.kicker + '</p>' : '') +
        '<h2 class="rd-title" tabindex="-1">' + esc(parts.title) + '</h2>' +
        (parts.sub ? '<p class="rd-sub">' + parts.sub + '</p>' : '') + '</div>';
      var screen = '<div class="rd-screen"' + this.still(view) + '>' + (parts.before || '') + head +
        '<p class="rd-error" role="alert" tabindex="-1"></p>' + (parts.body || '') + '</div>';
      var dock = parts.dock ? '<div class="rd-dock">' + parts.dock + '</div>' : '';
      this.innerHTML = progress + (parts.form ? '<form data-form="' + parts.form + '" novalidate>' + screen + dock + '</form>' : screen + dock);
      var title = this.querySelector('.rd-title');
      if (title && this.state.focused && !this.sameView) title.focus({ preventScroll: true });
      this.state.focused = true;
      // Only the thing that just changed animates; everything else stays put.
      this.fresh = null;
    }

    caseKicker() {
      return 'Case file / ' + esc(this.state.order ? this.state.order.order : '');
    }

    /* ------------------------------------------------------------------ 1. find */

    renderFind() {
      var params = new URLSearchParams(location.search);
      var order = params.get('order') || '';
      var proof = params.get('proof') || this.dataset.proof || '';
      this.state = { selected: {}, exchange: {}, focused: this.state && this.state.focused };
      this.view = null;
      this.frame('find', 0, {
        form: 'find',
        kicker: 'Open a case',
        title: 'Start a return',
        sub: 'Your order number, plus the email, postcode or phone you ordered with.',
        body:
          '<div class="rd-fieldset rd-cell" data-shake>' +
          '<div class="rd-field"><label class="rd-label" for="rd-order">Order number</label>' +
          '<input class="rd-input" id="rd-order" name="order" inputmode="numeric" autocomplete="off" placeholder="#1939" required value="' + esc(order) + '"></div>' +
          '<div class="rd-field"><label class="rd-label" for="rd-proof">Email, postcode or phone</label>' +
          '<input class="rd-input" id="rd-proof" name="proof" autocomplete="email" placeholder="you@example.com" required value="' + esc(proof) + '"></div></div>',
        dock: '<button class="rd-cta rd-press" type="submit">Find my order</button>',
      });
    }

    /* ------------------------------------------------------------------ status */

    renderStart() {
      var order = this.state.order;
      var open = order.returns || [];
      var canStart = order.lines.some(function (l) { return l.eligible && l.returnable_qty > 0; });
      if (!open.length) return canStart ? this.renderItems() : this.renderNothing();
      this.frame('start', null, {
        kicker: this.caseKicker(),
        title: 'Your returns',
        sub: 'Everything on this order, as it stands.',
        body: '<div class="rd-stagger" style="display:grid;gap:12px">' + open.map(this.caseCard.bind(this)).join('') + '</div>',
        dock:
          (canStart ? '<button class="rd-cta rd-cta--bone rd-press" type="button" data-go="items">Return something else</button>' : '') +
          '<div class="rd-dock__row"><button class="rd-ghost" type="button" data-go="find">Look up another order</button></div>',
      });
    }

    renderNothing() {
      var reasons = this.state.order.lines
        .map(function (l) { return l.message ? '<li>' + esc(l.title) + ': ' + esc(l.message) + '</li>' : ''; })
        .join('');
      this.frame('nothing', null, {
        kicker: this.caseKicker(),
        title: 'Nothing to send back yet',
        sub: 'There is nothing on this order we can take back online right now.',
        body: reasons ? '<ul class="rd-lines rd-cell" style="padding:16px 18px">' + reasons + '</ul>' : '',
        dock:
          '<a class="rd-cta rd-cta--bone rd-press" href="' + esc(this.contact) + '">Contact us</a>' +
          '<div class="rd-dock__row"><button class="rd-ghost" type="button" data-go="find">Look up another order</button></div>',
      });
    }

    timeline(ret) {
      var at = STATUS_STEP[ret.status];
      if (at == null) return '';
      var finish = ret.resolution === 'exchange' ? 'Swap sent out' : ret.resolution === 'store_credit' ? 'Credit added' : 'Refunded';
      var steps = ['Requested', 'Approved', ret.postage === 'self_ship' ? 'You post it' : 'Label sent', 'On its way back', 'Arrived with us', finish];
      return '<ol class="rd-timeline">' + steps.map(function (s, i) {
        var mark = i < at ? ' data-done' : i === at ? ' data-now' : '';
        return '<li' + mark + '><span class="rd-dot">' + (i < at ? '<span style="color:#0a0a0a">' + TICK + '</span>' : '') + '</span><span>' + esc(s) + '</span></li>';
      }).join('') + '</ol>';
    }

    caseCard(ret) {
      var lines = ret.items.map(function (i) {
        return '<li>' + esc(i.quantity + '× ' + i.title + (i.variant ? ' / ' + i.variant : '') + (i.exchange_for ? ' → ' + i.exchange_for : '')) + '</li>';
      }).join('');
      var outcome = ret.refund ? 'Refund ' + ret.refund : ret.credit ? ret.credit + ' store credit' : 'Free swap';
      var extra = '';
      if (ret.label_url) {
        extra += '<a class="rd-cta rd-press" href="' + esc(ret.label_url) + '" target="_blank" rel="noopener">Get your return label</a>';
      }
      if (ret.tracking) {
        extra += '<p class="rd-label">Tracking ' + (ret.tracking_url
          ? '<a class="rd-link" href="' + esc(ret.tracking_url) + '" target="_blank" rel="noopener">' + esc(ret.tracking) + '</a>'
          : esc(ret.tracking)) + '</p>';
      }
      if (ret.return_address && ret.return_address.length) {
        extra += '<div><p class="rd-label" style="margin:0 0 6px">Send it to</p><p class="rd-address">' + esc(ret.return_address.join('\n')) + '</p></div>';
      }
      if (ret.needs_tracking) {
        extra +=
          '<form data-form="tracking" data-return="' + esc(ret.id) + '" style="display:grid;gap:10px">' +
          '<div class="rd-cell rd-field" data-shake><label class="rd-label" for="rd-track-' + esc(ret.id) + '">Your tracking number</label>' +
          '<input class="rd-input" id="rd-track-' + esc(ret.id) + '" name="number" required autocomplete="off" placeholder="AB123456789GB"></div>' +
          '<button class="rd-cta rd-cta--bone rd-press" type="submit">Add tracking</button></form>';
      }
      if (ret.decline_reason) extra += '<p class="rd-sub">' + esc(ret.decline_reason) + '</p>';
      var good = ret.status === 'completed' || ret.status === 'awaiting_shipment';
      return (
        '<article class="rd-case rd-glass"' + (good ? ' data-good' : '') + '>' +
        '<div class="rd-case__head"><span class="rd-casestamp">' + esc(STATUS_NAME[ret.status] || ret.status) + '</span>' +
        '<span class="rd-label">' + esc(outcome) + '</span></div>' +
        '<p class="rd-case__msg">' + esc(ret.message) + '</p>' +
        '<ul class="rd-lines">' + lines + '</ul>' + this.timeline(ret) + extra + '</article>'
      );
    }

    /* ------------------------------------------------------------------ 2. items */

    reasonLabel(id) {
      var found = (this.state.order.reasons || []).find(function (r) { return r.id === id; });
      return found ? found.label : id;
    }

    renderItems() {
      var self = this;
      var rows = this.state.order.lines.map(function (line) {
        var usable = line.eligible && line.returnable_qty > 0;
        var sel = self.state.selected[line.id];
        var thumb = line.image
          ? '<img class="rd-thumb" src="' + esc(line.image + (line.image.indexOf('?') > -1 ? '&' : '?') + 'width=160') + '" alt="" loading="lazy" width="64" height="80">'
          : '<span class="rd-thumb" aria-hidden="true">' + esc(initials(line.title)) + '</span>';
        var more = '';
        if (sel) {
          var chips = line.reasons.map(function (r) {
            return '<button type="button" class="rd-chip rd-press" data-reason="' + esc(r) + '" data-line="' + esc(line.id) + '" aria-pressed="' + (sel.reason === r) + '">' + esc(CHIP[r] || self.reasonLabel(r)) + '</button>';
          }).join('');
          var qty = line.returnable_qty > 1
            ? '<div class="rd-stepper" aria-label="How many"><button type="button" data-qty="-1" data-line="' + esc(line.id) + '" aria-label="One fewer">−</button><span>' + sel.quantity + '</span><button type="button" data-qty="1" data-line="' + esc(line.id) + '" aria-label="One more">+</button></div>'
            : '';
          var hint = FIT_REASONS.indexOf(sel.reason) > -1 ? '<p class="rd-gap">Good news: size swaps are free.</p>' : '';
          var note = NOTE_REASONS.indexOf(sel.reason) > -1
            ? '<div class="rd-cell rd-field"><label class="rd-label" for="rd-n-' + esc(line.id) + '">Tell us what happened</label>' +
              '<textarea class="rd-textarea" id="rd-n-' + esc(line.id) + '" maxlength="300" data-note="' + esc(line.id) + '">' + esc(sel.note || '') + '</textarea></div>'
            : '';
          more = '<div class="rd-item__more"' + (self.fresh === 'pick:' + line.id ? ' data-fresh' : '') + '><p class="rd-label" style="margin:0">Why is it going back?</p><div class="rd-chips">' + chips + '</div>' + hint + qty + note + '</div>';
        }
        return (
          '<div class="rd-item"' + (sel ? ' data-on' : '') + (usable ? '' : ' data-off') + '>' +
          '<button type="button" class="rd-item__row rd-press" data-pick="' + esc(line.id) + '" aria-pressed="' + !!sel + '"' + (usable ? '' : ' disabled') + '>' +
          thumb + '<span><span class="rd-item__name">' + esc(line.title) + '</span><span class="rd-item__meta">' +
          esc((line.variant ? line.variant + ' · ' : '') + line.price) + '</span></span>' +
          (usable ? '<span class="rd-tick">' + TICK + '</span>' : '') + '</button>' +
          (line.message ? '<p class="rd-note">' + esc(line.message) + '</p>' : '') + more + '</div>'
        );
      }).join('');
      var picks = this.selections();
      var ready = picks.length && picks.every(function (p) { return p.reason; });
      this.frame('items', 1, {
        kicker: this.caseKicker(),
        title: "What's going back?",
        sub: 'Tap each item you are returning and tell us why.',
        body: '<div class="rd-items rd-cell rd-stagger">' + rows + '</div>',
        dock:
          '<button class="rd-cta rd-press" type="button" data-go="quote"' + (ready ? '' : ' disabled') + '>' +
          (picks.length ? 'See my options · ' + picks.length + (picks.length === 1 ? ' item' : ' items') : 'Pick an item') + '</button>' +
          '<div class="rd-dock__row"><button class="rd-ghost" type="button" data-go="find">Start again</button></div>',
      });
    }

    selections() {
      var self = this;
      return Object.keys(this.state.selected).map(function (id) {
        var s = self.state.selected[id];
        return { fulfillment_line_item_id: id, quantity: s.quantity, reason: s.reason, note: s.note || '' };
      });
    }

    /* ------------------------------------------------------------------ 3. deals */

    option(resolution) {
      return (this.state.quote.options || []).find(function (o) { return o.resolution === resolution; });
    }

    postageSeg(option) {
      var self = this;
      if (option.postage.length < 2) return '';
      var top = Math.max.apply(null, option.postage.map(function (p) { return pence(p.total); }));
      var buttons = option.postage.map(function (p) {
        var small = p.choice === 'paid_label' ? '−' + gbp(top - pence(p.total))
          : p.choice === 'free_label' ? 'Royal Mail, on us'
          : 'Your own way';
        var name = p.choice === 'paid_label' ? 'Our label' : p.choice === 'free_label' ? 'Free label' : "I'll post it";
        return '<button type="button" class="rd-press" data-post="' + esc(p.choice) + '" aria-pressed="' + (self.state.postage === p.choice) + '" aria-label="' + esc(p.label) + '">' + esc(name) + '<small>' + esc(small) + '</small></button>';
      }).join('');
      return '<div><p class="rd-label" style="margin:0 0 8px">Getting it back to us</p><div class="rd-seg rd-cell">' + buttons + '</div></div>';
    }

    renderDeals() {
      var self = this;
      var q = this.state.quote;
      var items = pence(q.items_total);
      var credit = this.option('store_credit');
      var refund = this.option('refund');
      var chosen = this.state.resolution;
      var cards = q.options.filter(function (o) { return o.resolution !== 'refund'; }).map(function (o) {
        var on = chosen === o.resolution;
        var inner, extra = '';
        if (o.resolution === 'exchange') {
          inner =
            '<span class="rd-deal__top"><span class="rd-deal__name">' + esc(o.headline) + '</span><span class="rd-stamp">Free</span></span>' +
            '<span class="rd-deal__value"><span class="rd-big">£0.00</span><span class="rd-label">to swap</span></span>' +
            '<span class="rd-deal__detail">' + esc(o.detail) + '</span>' +
            '<span class="rd-badges"><span class="rd-badge rd-badge--hot">Free return label</span><span class="rd-badge">In stock now</span></span>';
          if (on) {
            extra = '<div class="rd-sizes"' + (self.fresh === 'res:exchange' ? ' data-fresh' : '') + '>' + Object.keys(o.exchange_choices).map(function (fli) {
              var line = self.state.order.lines.find(function (l) { return l.id === fli; });
              var chips = o.exchange_choices[fli].map(function (v) {
                return '<button type="button" class="rd-chip rd-press" data-swap="' + esc(fli) + '" data-variant="' + esc(v.id) + '" aria-pressed="' + (self.state.exchange[fli] === v.id) + '">' + esc(v.title) + '</button>';
              }).join('');
              return '<p class="rd-label" style="margin:0">Swap ' + esc(line ? line.title + ' / ' + line.variant : '') + ' for</p><div class="rd-chips">' + chips + '</div>';
            }).join('') + '</div>';
          }
        } else {
          var total = pence(o.postage[0].total);
          inner =
            '<span class="rd-deal__top"><span class="rd-deal__name">Store credit</span><span class="rd-stamp">+' + esc(gbp(total - items)) + ' bonus</span></span>' +
            '<span class="rd-deal__value"><span class="rd-big">' + esc(gbp(total)) + '</span><span class="rd-was">' + esc(gbp(items)) + '</span></span>' +
            '<span class="rd-deal__detail">' + esc(o.detail) + '</span>' +
            '<span class="rd-badges"><span class="rd-badge rd-badge--hot">Free return label</span><span class="rd-badge">Spend it on anything</span></span>';
        }
        if (on) extra += self.postageSeg(o);
        return '<div class="rd-deal"' + (on ? ' data-on' : '') + (self.fresh === 'res:' + o.resolution ? ' data-fresh' : '') + '><button type="button" class="rd-deal__hit rd-press" data-res="' + esc(o.resolution) + '" aria-pressed="' + on + '">' + inner + '</button>' + extra + '</div>';
      }).join('');

      var refundRow = '';
      if (refund) {
        var totals = refund.postage.map(function (p) { return pence(p.total); });
        var best = Math.max.apply(null, totals);
        var low = Math.min.apply(null, totals);
        var on = chosen === 'refund';
        var detail = refund.postage.length > 1 && best !== low
          ? gbp(best) + ' if you post it yourself, or ' + gbp(low) + ' with our Royal Mail label. Back to your card once it arrives.'
          : gbp(best) + ' back to your card once it arrives' + (refund.postage.some(function (p) { return p.choice === 'free_label'; }) ? ', with a free return label.' : '.');
        var gap = credit ? pence(credit.postage[0].total) - best : 0;
        refundRow =
          '<div class="rd-refund"' + (on ? ' data-on' : '') + '>' +
          '<button type="button" class="rd-deal__hit rd-press" data-res="refund" aria-pressed="' + on + '">' +
          '<span class="rd-refund__top"><span class="rd-refund__name">Refund to card</span><span class="rd-refund__value">' + esc(best === low ? gbp(best) : gbp(low) + '–' + gbp(best)) + '</span></span>' +
          '<span class="rd-refund__detail">' + esc(detail) + '</span>' +
          (gap > 0 ? '<span class="rd-gap">' + esc(gbp(gap)) + ' less than store credit</span>' : '') +
          '</button>' + (on ? this.postageSeg(refund) : '') + '</div>';
      }

      var cta = 'Choose a deal';
      var ready = !!chosen && !!this.state.postage;
      var opt = chosen && this.option(chosen);
      if (opt) {
        var post = opt.postage.find(function (p) { return p.choice === self.state.postage; });
        if (chosen === 'exchange') {
          var missing = Object.keys(opt.exchange_choices).some(function (fli) { return !self.state.exchange[fli]; });
          ready = ready && !missing;
          cta = missing ? 'Pick your new size' : 'Swap it · free';
        } else if (chosen === 'store_credit') {
          cta = 'Take ' + (post ? post.total : '') + ' credit';
        } else {
          cta = 'Refund ' + (post ? post.total : '');
        }
      }
      this.frame('deals', 2, {
        kicker: this.caseKicker(),
        title: 'Pick your deal',
        sub: 'Swaps and store credit come with free returns. Credit gets a bonus on top.',
        body: '<div class="rd-deals rd-stagger">' + cards + refundRow + '</div>',
        dock:
          '<button class="rd-cta rd-press" type="button" data-go="confirm"' + (ready ? '' : ' disabled') + '>' + esc(cta) + '</button>' +
          '<div class="rd-dock__row"><button class="rd-ghost" type="button" data-go="items">Back</button></div>',
      });
    }

    choose(resolution) {
      this.state.resolution = resolution;
      var opt = this.option(resolution);
      this.state.postage = opt && opt.postage.length ? opt.postage[0].choice : null;
      // A refund starts on whichever postage gives the customer the most back.
      if (opt && resolution === 'refund') {
        this.state.postage = opt.postage.slice().sort(function (a, b) { return pence(b.total) - pence(a.total); })[0].choice;
      }
      if (opt && resolution === 'exchange') {
        var self = this;
        Object.keys(opt.exchange_choices).forEach(function (fli) {
          var list = opt.exchange_choices[fli];
          if (!self.state.exchange[fli] && list.length === 1) self.state.exchange[fli] = list[0].id;
        });
      }
    }

    /* ------------------------------------------------------------------ 4. confirm */

    renderConfirm() {
      var self = this;
      var opt = this.option(this.state.resolution);
      var post = opt.postage.find(function (p) { return p.choice === self.state.postage; });
      var rows = this.selections().map(function (s) {
        var line = self.state.order.lines.find(function (l) { return l.id === s.fulfillment_line_item_id; });
        var swap = '';
        if (opt.resolution === 'exchange') {
          var v = opt.exchange_choices[s.fulfillment_line_item_id].find(function (x) { return x.id === self.state.exchange[s.fulfillment_line_item_id]; });
          swap = v ? ' → ' + v.title : '';
        }
        return '<div><dt>' + esc(s.quantity + '× ' + line.title + ' / ' + line.variant + swap) + '</dt><dd>' + esc(self.reasonLabel(s.reason)) + '</dd></div>';
      }).join('');
      var deal = opt.resolution === 'exchange' ? 'Size swap' : opt.resolution === 'store_credit' ? 'Store credit' : 'Refund to card';
      var total = opt.resolution === 'exchange' ? 'Free' : post.total;
      this.frame('confirm', 3, {
        kicker: this.caseKicker(),
        title: 'Looks right?',
        sub: 'Unworn, unwashed, tags on. We will email you at every step.',
        body:
          '<div class="rd-receipt"><div class="rd-receipt__head"><span>Case file</span><span>' + esc(this.state.order.order) + '</span></div>' +
          '<dl>' + rows + '<div><dt>Deal</dt><dd>' + esc(deal) + '</dd></div><div><dt>Postage</dt><dd>' + esc(post.label) + '</dd></div></dl>' +
          '<div class="rd-receipt__total"><span>' + (opt.resolution === 'exchange' ? 'Cost' : 'You get') + '</span><strong>' + esc(total) + '</strong></div></div>',
        dock:
          '<button class="rd-cta rd-press" type="button" data-go="submit">Confirm return</button>' +
          '<div class="rd-dock__row"><button class="rd-ghost" type="button" data-go="deals">Back</button></div>',
      });
    }

    renderDone(ret) {
      this.frame('done', null, {
        before: '<span class="rd-bigstamp" aria-hidden="true">Case open</span>',
        kicker: this.caseKicker(),
        title: "We've got it",
        sub: this.state.postage === 'self_ship'
          ? 'We will email you as soon as it is approved.'
          : 'We will email you as soon as it is approved, with your Royal Mail label.',
        body: this.caseCard(ret),
        dock: '<button class="rd-cta rd-cta--bone rd-press" type="button" data-go="status">Back to my order</button>',
      });
    }

    /* ------------------------------------------------------------------ events */

    onSubmit(event) {
      var form = event.target.closest('form');
      if (!form) return;
      event.preventDefault();
      var self = this;
      var button = form.querySelector('button[type="submit"]');
      var data = new FormData(form);
      if (form.dataset.form === 'find') {
        var order = String(data.get('order') || '').trim();
        this.busy(button, 'Finding ' + (order.charAt(0) === '#' ? order : '#' + order), async function () {
          var found = await self.post('/lookup', { order: data.get('order'), proof: data.get('proof') });
          self.state.session = found.session;
          self.state.order = found;
          remember(found.session);
          self.renderStart();
        });
      } else if (form.dataset.form === 'tracking') {
        this.busy(button, 'Adding', async function () {
          await self.post('/tracking', { session: self.state.session, return_id: form.dataset.return, number: data.get('number') });
          self.state.order = await self.post('/order', { session: self.state.session });
          self.renderStart();
        });
      }
    }

    onInput(event) {
      var t = event.target;
      if (t.dataset.note && this.state.selected[t.dataset.note]) this.state.selected[t.dataset.note].note = t.value;
    }

    refocus(selector) {
      var el = this.querySelector(selector);
      if (el) el.focus({ preventScroll: true });
    }

    onClick(event) {
      var t = event.target;
      var self = this;
      var pick = t.closest('[data-pick]');
      if (pick) {
        var id = pick.dataset.pick;
        if (this.state.selected[id]) delete this.state.selected[id];
        else {
          this.state.selected[id] = { quantity: 1, reason: '' };
          this.fresh = 'pick:' + id;
        }
        this.renderItems();
        return this.refocus('[data-pick="' + CSS.escape(id) + '"]');
      }
      var reason = t.closest('[data-reason]');
      if (reason) {
        this.state.selected[reason.dataset.line].reason = reason.dataset.reason;
        this.renderItems();
        return this.refocus('[data-reason="' + CSS.escape(reason.dataset.reason) + '"][data-line="' + CSS.escape(reason.dataset.line) + '"]');
      }
      var qty = t.closest('[data-qty]');
      if (qty) {
        var line = this.state.order.lines.find(function (l) { return l.id === qty.dataset.line; });
        var sel = this.state.selected[qty.dataset.line];
        sel.quantity = Math.max(1, Math.min(line.returnable_qty, sel.quantity + parseInt(qty.dataset.qty, 10)));
        this.renderItems();
        return this.refocus('[data-qty="' + qty.dataset.qty + '"][data-line="' + CSS.escape(qty.dataset.line) + '"]');
      }
      var res = t.closest('[data-res]');
      if (res) {
        if (this.state.resolution !== res.dataset.res) {
          this.choose(res.dataset.res);
          this.fresh = 'res:' + res.dataset.res;
        }
        this.renderDeals();
        return this.refocus('[data-res="' + res.dataset.res + '"]');
      }
      var swap = t.closest('[data-swap]');
      if (swap) {
        this.state.exchange[swap.dataset.swap] = swap.dataset.variant;
        this.renderDeals();
        return this.refocus('[data-variant="' + CSS.escape(swap.dataset.variant) + '"]');
      }
      var post = t.closest('[data-post]');
      if (post) {
        this.state.postage = post.dataset.post;
        this.renderDeals();
        return this.refocus('[data-post="' + post.dataset.post + '"]');
      }
      var go = t.closest('[data-go]');
      if (!go) return;
      var where = go.dataset.go;
      if (where === 'find') {
        remember(null);
        this.renderFind();
      } else if (where === 'items') {
        this.renderItems();
      } else if (where === 'deals') {
        this.renderDeals();
      } else if (where === 'quote') {
        this.busy(go, 'Working out your options', async function () {
          self.state.quote = await self.post('/quote', { session: self.state.session, items: self.selections() });
          self.state.exchange = {};
          self.choose(self.state.quote.options[0].resolution);
          self.renderDeals();
        });
      } else if (where === 'confirm') {
        this.renderConfirm();
      } else if (where === 'submit') {
        this.busy(go, 'Opening your case', async function () {
          var opt = self.option(self.state.resolution);
          var made = await self.post('/submit', {
            session: self.state.session,
            items: self.selections(),
            resolution: opt.resolution,
            postage: self.state.postage,
            exchange: opt.resolution === 'exchange' ? self.state.exchange : {},
          });
          self.state.selected = {};
          self.state.exchange = {};
          self.renderDone(made.return);
        });
      } else if (where === 'status') {
        this.busy(go, 'Loading', async function () {
          self.state.order = await self.post('/order', { session: self.state.session });
          self.renderStart();
        });
      }
    }
  }

  customElements.define('returns-portal', ReturnsPortal);
})();
