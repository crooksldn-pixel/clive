/*
 * CROOKS Returns desk. Four steps: find the order, choose what goes back, pick an option,
 * confirm. Every offer, price and rule comes from the returns service; this file only
 * renders what it is told and sends back what the customer chose.
 */
(function () {
  if (customElements.get('returns-portal')) return;

  var STORE_KEY = 'crooks_returns_session';
  var NOTE_REASONS = ['faulty', 'not_as_described', 'wrong_item'];
  var STEP_TITLES = ['Find your order', "What's going back", 'Your options', 'Confirm'];

  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
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

  class ReturnsPortal extends HTMLElement {
    connectedCallback() {
      this.endpoint = (this.dataset.endpoint || '/apps/returns/api').replace(/\/$/, '');
      this.contact = this.dataset.contact || '/';
      this.state = { selected: {}, exchange: {} };
      this.addEventListener('submit', this.onSubmit.bind(this));
      this.addEventListener('click', this.onClick.bind(this));
      this.addEventListener('change', this.onChange.bind(this));
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

    async busy(button, work) {
      var error = this.querySelector('.rd-error');
      if (error) error.textContent = '';
      if (button) button.disabled = true;
      try {
        await work();
      } catch (e) {
        error = this.querySelector('.rd-error');
        if (error) {
          error.textContent = e.message;
          error.focus();
        }
        if (/session has expired/i.test(e.message)) setTimeout(this.renderFind.bind(this), 1600);
      } finally {
        if (button && button.isConnected) button.disabled = false;
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

    /* ------------------------------------------------------------------ chrome */

    frame(step, body) {
      var bars = STEP_TITLES.map(function (_, i) {
        return '<span' + (i < step ? ' data-done' : '') + (i === step ? ' data-current' : '') + '></span>';
      }).join('');
      this.innerHTML =
        '<div class="rd-step"' + this.still('step' + step) + '>' +
        '<div class="rd-progress" aria-hidden="true">' + bars + '</div>' +
        '<div class="rd-step__head"><h2 class="rd-step__title" tabindex="-1">' + esc(STEP_TITLES[step]) +
        '</h2><span class="rd-step__count">' + String(step + 1).padStart(2, '0') + ' / 04</span></div>' +
        '<p class="rd-error" role="alert" tabindex="-1"></p>' + body + '</div>';
      this.focusTitle();
    }

    plain(title, body) {
      this.innerHTML =
        '<div class="rd-step"' + this.still('plain' + title) + '><div class="rd-step__head">' +
        '<h2 class="rd-step__title" tabindex="-1">' + esc(title) + '</h2></div><p class="rd-error" role="alert" tabindex="-1"></p>' + body + '</div>';
      this.focusTitle();
    }

    // Re-rendering the same step (ticking a box, picking a reason) must not replay the entrance
    // or pull focus away from the control the customer is using.
    still(view) {
      this.sameView = this.view === view;
      this.view = view;
      return this.sameView ? ' data-still' : '';
    }

    focusTitle() {
      var title = this.querySelector('.rd-step__title');
      if (title && this.state.focused && !this.sameView) title.focus({ preventScroll: false });
      this.state.focused = true;
    }

    /* ------------------------------------------------------------------ 1. find */

    renderFind() {
      var params = new URLSearchParams(location.search);
      var order = params.get('order') || '';
      var proof = params.get('proof') || this.dataset.proof || '';
      this.state = { selected: {}, exchange: {}, focused: this.state && this.state.focused };
      this.view = null;
      this.frame(
        0,
        '<form data-form="find" novalidate><div class="rd-fields rd-fields--two">' +
          '<div class="rd-field"><label for="rd-order">Order number</label>' +
          '<input class="rd-input" id="rd-order" name="order" inputmode="numeric" autocomplete="off" placeholder="#1939" required value="' + esc(order) + '"></div>' +
          '<div class="rd-field"><label for="rd-proof">Email, postcode or phone</label>' +
          '<input class="rd-input" id="rd-proof" name="proof" autocomplete="email" required value="' + esc(proof) + '"></div>' +
          '</div><p class="rd-hint">Use the details from your order confirmation.</p>' +
          '<div class="rd-actions"><button class="rd-button" type="submit">Find my order</button></div></form>'
      );
    }

    /* ------------------------------------------------------------------ start / status */

    renderStart() {
      var order = this.state.order;
      var open = order.returns || [];
      var canStart = order.lines.some(function (l) {
        return l.eligible && l.returnable_qty > 0;
      });
      if (!open.length) return canStart ? this.renderItems() : this.renderNothing();
      var cases = open.map(this.caseCard.bind(this)).join('');
      this.plain(
        'Order ' + order.order,
        cases +
          '<div class="rd-actions">' +
          (canStart ? '<button class="rd-button" type="button" data-go="items">Return something else</button>' : '') +
          '<button class="rd-link" type="button" data-go="find">Look up another order</button></div>'
      );
    }

    renderNothing() {
      var reasons = this.state.order.lines
        .map(function (l) {
          return l.message ? '<li>' + esc(l.title) + ': ' + esc(l.message) + '</li>' : '';
        })
        .join('');
      this.plain(
        'Order ' + this.state.order.order,
        '<p>There is nothing on this order we can take back online right now.</p>' +
          (reasons ? '<ul>' + reasons + '</ul>' : '') +
          '<div class="rd-actions"><a class="rd-button" href="' + esc(this.contact) + '">Contact us</a>' +
          '<button class="rd-link" type="button" data-go="find">Look up another order</button></div>'
      );
    }

    caseCard(ret) {
      var items = ret.items
        .map(function (i) {
          return (
            '<div><dt>' + esc(i.quantity + ' × ' + i.title + (i.variant ? ' / ' + i.variant : '')) + '</dt><dd>' +
            esc(i.exchange_for ? 'Swap for ' + i.exchange_for : i.reason) + '</dd></div>'
          );
        })
        .join('');
      var money = ret.refund ? 'Refund ' + ret.refund : ret.credit ? ret.credit + ' store credit' : 'Exchange';
      var extra = '';
      if (ret.label_url) {
        extra +=
          '<div class="rd-actions"><a class="rd-button" href="' + esc(ret.label_url) +
          '" target="_blank" rel="noopener">Download return label</a></div>';
      }
      if (ret.tracking) {
        extra +=
          '<p class="rd-meta">Tracking ' + (ret.tracking_url
            ? '<a href="' + esc(ret.tracking_url) + '" target="_blank" rel="noopener">' + esc(ret.tracking) + '</a>'
            : esc(ret.tracking)) + '</p>';
      }
      if (ret.return_address && ret.return_address.length) {
        extra += '<p class="rd-meta">Send it to</p><p class="rd-address">' + esc(ret.return_address.join('\n')) + '</p>';
      }
      if (ret.needs_tracking) {
        extra +=
          '<form data-form="tracking" data-return="' + esc(ret.id) + '" class="rd-fields" style="margin-top:20px">' +
          '<div class="rd-field"><label for="rd-track-' + esc(ret.id) + '">Your tracking number</label>' +
          '<input class="rd-input" id="rd-track-' + esc(ret.id) + '" name="number" required autocomplete="off"></div>' +
          '<div><button class="rd-button" type="submit">Add tracking</button></div></form>';
      }
      if (ret.decline_reason) extra += '<p>' + esc(ret.decline_reason) + '</p>';
      return (
        '<article class="rd-case" data-status="' + esc(ret.status) + '">' +
        '<span class="rd-stamp">' + esc(ret.status.replace(/_/g, ' ')) + '</span>' +
        '<p class="rd-case__message">' + esc(ret.message) + '</p>' +
        '<dl class="rd-docket">' + items + '<div><dt>Outcome</dt><dd>' + esc(money) + '</dd></div></dl>' +
        extra + '</article>'
      );
    }

    /* ------------------------------------------------------------------ 2. items */

    reasonLabel(id) {
      var found = (this.state.order.reasons || []).find(function (r) {
        return r.id === id;
      });
      return found ? found.label : id;
    }

    renderItems() {
      var self = this;
      var rows = this.state.order.lines
        .map(function (line) {
          var usable = line.eligible && line.returnable_qty > 0;
          var sel = self.state.selected[line.id];
          var img = line.image
            ? '<img class="rd-item__img" src="' + esc(line.image + (line.image.indexOf('?') > -1 ? '&' : '?') + 'width=200') + '" alt="" loading="lazy" width="72" height="90">'
            : '<span class="rd-item__img" aria-hidden="true"></span>';
          var detail = '';
          if (sel) {
            var reasons = line.reasons
              .map(function (r) {
                return '<option value="' + esc(r) + '"' + (sel.reason === r ? ' selected' : '') + '>' + esc(self.reasonLabel(r)) + '</option>';
              })
              .join('');
            var qty = '';
            if (line.returnable_qty > 1) {
              var opts = '';
              for (var q = 1; q <= line.returnable_qty; q++) {
                opts += '<option' + (sel.quantity === q ? ' selected' : '') + '>' + q + '</option>';
              }
              qty =
                '<div class="rd-field"><label for="rd-q-' + esc(line.id) + '">How many</label>' +
                '<select class="rd-select" id="rd-q-' + esc(line.id) + '" data-line="' + esc(line.id) + '" data-key="quantity">' + opts + '</select></div>';
            }
            var note = NOTE_REASONS.indexOf(sel.reason) > -1
              ? '<div class="rd-field"><label for="rd-n-' + esc(line.id) + '">Tell us what happened</label>' +
                '<textarea class="rd-textarea" id="rd-n-' + esc(line.id) + '" maxlength="300" data-line="' + esc(line.id) + '" data-key="note">' + esc(sel.note || '') + '</textarea></div>'
              : '';
            detail =
              '<div class="rd-item__detail"><div class="rd-field"><label for="rd-r-' + esc(line.id) + '">Reason</label>' +
              '<select class="rd-select" id="rd-r-' + esc(line.id) + '" data-line="' + esc(line.id) + '" data-key="reason">' +
              '<option value="">Choose a reason</option>' + reasons + '</select></div>' + qty + note + '</div>';
          }
          return (
            '<li class="rd-item"' + (usable ? '' : ' data-disabled') + '>' + img + '<div>' +
            '<div class="rd-item__top"><div><p class="rd-item__title">' + esc(line.title) + '</p>' +
            '<p class="rd-meta">' + esc(line.variant || '') + '</p></div><span class="rd-price">' + esc(line.price) + '</span></div>' +
            (usable
              ? '<label class="rd-check"><input type="checkbox" data-pick="' + esc(line.id) + '"' + (sel ? ' checked' : '') + '> Return this</label>'
              : '<p class="rd-hint">' + esc(line.message) + '</p>') +
            (line.eligible && line.message ? '<p class="rd-hint">' + esc(line.message) + '</p>' : '') +
            detail + '</div></li>'
          );
        })
        .join('');
      this.frame(
        1,
        '<ul class="rd-items">' + rows + '</ul>' +
          '<div class="rd-actions"><button class="rd-button" type="button" data-go="quote">See my options</button>' +
          '<button class="rd-link" type="button" data-go="find">Start again</button></div>'
      );
    }

    selections() {
      var self = this;
      return Object.keys(this.state.selected).map(function (id) {
        var s = self.state.selected[id];
        return { fulfillment_line_item_id: id, quantity: s.quantity, reason: s.reason, note: s.note || '' };
      });
    }

    /* ------------------------------------------------------------------ 3. options */

    renderOptions() {
      var self = this;
      var quote = this.state.quote;
      var choice = this.state.resolution;
      var cards = quote.options
        .map(function (o, i) {
          return (
            '<label class="rd-choice">' + (i === 0 ? '<span class="rd-badge">Best value</span>' : '') +
            '<input type="radio" name="resolution" value="' + esc(o.resolution) + '"' + (choice === o.resolution ? ' checked' : '') + '>' +
            '<span><p class="rd-choice__headline">' + esc(o.headline) + '</p><p class="rd-choice__detail">' + esc(o.detail) + '</p></span></label>'
          );
        })
        .join('');
      var option = this.chosenOption();
      var more = '';
      if (option && option.resolution === 'exchange') {
        more += Object.keys(option.exchange_choices)
          .map(function (fli) {
            var line = self.state.order.lines.find(function (l) {
              return l.id === fli;
            });
            var chips = option.exchange_choices[fli]
              .map(function (v) {
                return '<button type="button" class="rd-chip" data-swap="' + esc(fli) + '" data-variant="' + esc(v.id) + '" aria-pressed="' +
                  (self.state.exchange[fli] === v.id) + '">' + esc(v.title) + '</button>';
              })
              .join('');
            return '<p class="rd-subhead">Swap ' + esc(line ? line.title + ' / ' + line.variant : '') + ' for</p><div class="rd-chips">' + chips + '</div>';
          })
          .join('');
      }
      if (option) {
        more +=
          '<p class="rd-subhead">Getting it back to us</p><div class="rd-options">' +
          option.postage
            .map(function (p) {
              return (
                '<label class="rd-choice"><input type="radio" name="postage" value="' + esc(p.choice) + '"' +
                (self.state.postage === p.choice ? ' checked' : '') + '><span><p class="rd-choice__headline" style="font-size:1rem">' +
                esc(p.label) + '</p>' + (option.resolution === 'exchange' ? '' : '<p class="rd-choice__detail rd-price">You get ' + esc(p.total) + '</p>') +
                '</span></label>'
              );
            })
            .join('') + '</div>';
      }
      this.frame(
        2,
        '<fieldset style="border:0;padding:0;margin:0"><legend class="rd-legend">Choose one</legend><div class="rd-options">' + cards + '</div></fieldset>' +
          more +
          '<div class="rd-actions"><button class="rd-button" type="button" data-go="confirm">Continue</button>' +
          '<button class="rd-link" type="button" data-go="items">Back</button></div>'
      );
    }

    chosenOption() {
      var r = this.state.resolution;
      return (this.state.quote.options || []).find(function (o) {
        return o.resolution === r;
      });
    }

    /* ------------------------------------------------------------------ 4. confirm */

    renderConfirm() {
      var self = this;
      var option = this.chosenOption();
      var postage = option.postage.find(function (p) {
        return p.choice === self.state.postage;
      });
      var rows = this.selections()
        .map(function (s) {
          var line = self.state.order.lines.find(function (l) {
            return l.id === s.fulfillment_line_item_id;
          });
          var swap = '';
          if (option.resolution === 'exchange') {
            var v = option.exchange_choices[s.fulfillment_line_item_id].find(function (x) {
              return x.id === self.state.exchange[s.fulfillment_line_item_id];
            });
            swap = v ? ' → ' + v.title : '';
          }
          return (
            '<div><dt>' + esc(s.quantity + ' × ' + line.title + ' / ' + line.variant + swap) + '</dt><dd>' +
            esc(self.reasonLabel(s.reason)) + '</dd></div>'
          );
        })
        .join('');
      var total = option.resolution === 'exchange' ? 'Free exchange' : postage.total;
      this.frame(
        3,
        '<dl class="rd-docket">' + rows +
          '<div><dt>Option</dt><dd>' + esc(option.headline) + '</dd></div>' +
          '<div><dt>Postage</dt><dd>' + esc(postage.label) + '</dd></div>' +
          '<div class="rd-total"><dt>' + (option.resolution === 'exchange' ? 'Cost' : 'You get') + '</dt><dd>' + esc(total) + '</dd></div></dl>' +
          '<p class="rd-hint">Items must be unworn, unwashed and have their tags. We will email you at every step.</p>' +
          '<div class="rd-actions"><button class="rd-button" type="button" data-go="submit">Confirm return</button>' +
          '<button class="rd-link" type="button" data-go="options">Back</button></div>'
      );
    }

    /* ------------------------------------------------------------------ events */

    onSubmit(event) {
      var form = event.target.closest('form');
      if (!form) return;
      event.preventDefault();
      var self = this;
      var button = form.querySelector('button[type="submit"]');
      if (form.dataset.form === 'find') {
        var data = new FormData(form);
        this.busy(button, async function () {
          var found = await self.post('/lookup', { order: data.get('order'), proof: data.get('proof') });
          self.state.session = found.session;
          self.state.order = found;
          remember(found.session);
          self.renderStart();
        });
      } else if (form.dataset.form === 'tracking') {
        var number = new FormData(form).get('number');
        this.busy(button, async function () {
          await self.post('/tracking', { session: self.state.session, return_id: form.dataset.return, number: number });
          self.state.order = await self.post('/order', { session: self.state.session });
          self.renderStart();
        });
      }
    }

    onChange(event) {
      var t = event.target;
      if (t.dataset.pick) {
        if (t.checked) this.state.selected[t.dataset.pick] = { quantity: 1, reason: '' };
        else delete this.state.selected[t.dataset.pick];
        this.renderItems();
        var focus = this.querySelector('#rd-r-' + CSS.escape(t.dataset.pick));
        if (focus) focus.focus();
      } else if (t.dataset.line) {
        var sel = this.state.selected[t.dataset.line];
        if (!sel) return;
        sel[t.dataset.key] = t.dataset.key === 'quantity' ? parseInt(t.value, 10) : t.value;
        if (t.dataset.key === 'reason') {
          this.renderItems();
          var again = this.querySelector('#rd-r-' + CSS.escape(t.dataset.line));
          if (again) again.focus();
        }
      } else if (t.name === 'resolution') {
        this.state.resolution = t.value;
        var option = this.chosenOption();
        this.state.postage = option && option.postage.length === 1 ? option.postage[0].choice : null;
        this.renderOptions();
      } else if (t.name === 'postage') {
        this.state.postage = t.value;
      }
    }

    onClick(event) {
      var swap = event.target.closest('[data-swap]');
      if (swap) {
        this.state.exchange[swap.dataset.swap] = swap.dataset.variant;
        this.querySelectorAll('[data-swap="' + CSS.escape(swap.dataset.swap) + '"]').forEach(function (b) {
          b.setAttribute('aria-pressed', String(b === swap));
        });
        return;
      }
      var go = event.target.closest('[data-go]');
      if (!go) return;
      var self = this;
      var where = go.dataset.go;
      if (where === 'find') {
        remember(null);
        this.renderFind();
      } else if (where === 'items') {
        this.renderItems();
      } else if (where === 'options') {
        this.renderOptions();
      } else if (where === 'quote') {
        this.busy(go, async function () {
          var picks = self.selections();
          if (!picks.length) throw new Error('Tick the items you are sending back.');
          if (picks.some(function (p) { return !p.reason; })) throw new Error('Choose a reason for each item.');
          self.state.quote = await self.post('/quote', { session: self.state.session, items: picks });
          self.state.resolution = null;
          self.state.postage = null;
          self.state.exchange = {};
          self.renderOptions();
        });
      } else if (where === 'confirm') {
        this.busy(go, async function () {
          var option = self.chosenOption();
          if (!option) throw new Error('Choose an option.');
          if (option.resolution === 'exchange') {
            var missing = Object.keys(option.exchange_choices).some(function (fli) {
              return !self.state.exchange[fli];
            });
            if (missing) throw new Error('Choose what to swap each item for.');
          }
          if (!self.state.postage) throw new Error('Choose how it gets back to us.');
          self.renderConfirm();
        });
      } else if (where === 'submit') {
        this.busy(go, async function () {
          var option = self.chosenOption();
          var made = await self.post('/submit', {
            session: self.state.session,
            items: self.selections(),
            resolution: option.resolution,
            postage: self.state.postage,
            exchange: option.resolution === 'exchange' ? self.state.exchange : {},
          });
          self.state.selected = {};
          self.state.exchange = {};
          self.plain(
            'Return requested',
            self.caseCard(made.return) +
              '<p>We have your request and will email you as soon as it is approved' +
              (self.state.postage === 'self_ship' ? '.' : ', with your Royal Mail label.') + '</p>' +
              '<div class="rd-actions"><button class="rd-link" type="button" data-go="status">Back to my order</button></div>'
          );
        });
      } else if (where === 'status') {
        this.busy(go, async function () {
          self.state.order = await self.post('/order', { session: self.state.session });
          self.renderStart();
        });
      }
    }
  }

  customElements.define('returns-portal', ReturnsPortal);
})();
