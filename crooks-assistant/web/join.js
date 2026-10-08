/* CLIVE · Join: a member of the team signs this phone in with the staff link George sent and the code
 * he told them (ruling 35, DEC-075; app/routes/staff_links.py, docs/STAFF_LINKS.md).
 *
 * The link's key is after the # in the address, so no server ever sees it in a request line, a log or a
 * Referer: this page reads it and sends it once, with the code, in the body of POST /join. The answer
 * signs the phone in with an HttpOnly cookie that this page never sees, and the page goes to Today in
 * place of itself (location.replace), so the spent link is not the page Back returns to. No script of
 * CLIVE's writes the address bar (tests/web/live-words-page.test.js); this one does not need to.
 * Every word on the page is one of these fixed sentences or the server's own refusal, put in as text.
 */
(function () {
  'use strict';

  const $ = (selector) => document.querySelector(selector);
  const TOKEN = /^[A-Za-z0-9_-]{43}$/;
  // In-app browsers keep their own cookies, so a phone signed in there is not signed in in Safari or
  // Chrome (docs/STAFF_LINKS.md, risk 9): said before they type the code.
  const IN_APP = /\b(Instagram|FBAN|FBAV|FB_IAB|Line\/|Snapchat|TikTok|musical_ly)\b/;
  let token = '';
  let busy = false;

  function say(text, mood) {
    const line = $('#line');
    line.textContent = text;
    line.classList.toggle('is-error', mood === 'error');
    line.classList.toggle('is-done', mood === 'done');
  }

  function closed(title, text) {
    $('#title').textContent = title;
    say(text, 'error');
    $('#form').hidden = true;
    $('#note').hidden = true;
  }

  async function join(code) {
    let response;
    try {
      response = await fetch('/join', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ token, code }),
      });
    } catch (error) {
      return { ok: false, code: 'unreached', detail: "CLIVE can't be reached. Check the phone is online, then try again." };
    }
    let data = {};
    try { data = await response.json(); } catch (error) { data = {}; }
    if (response.ok && data.ok) return data;
    return { ok: false, code: data.code || 'refused', detail: data.detail || 'That did not work. Try again.' };
  }

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const code = $('#code').value.replace(/\D/g, '');
    if (code.length !== 6) { say('The code is six numbers.', 'error'); $('#code').focus(); return; }
    busy = true;
    $('#go').disabled = true;
    say('Signing this phone in…');
    const done = await join(code);
    busy = false;
    $('#go').disabled = false;
    if (done.ok) {
      token = '';
      $('#title').textContent = `You're in, ${done.name}.`;
      say('Opening your work list…', 'done');
      $('#form').hidden = true;
      window.setTimeout(() => window.location.replace('/today'), 700);
      return;
    }
    if (done.code === 'wrong_code' || done.code === 'too_many' || done.code === 'unreached') {
      say(done.detail, 'error');
      $('#code').value = '';
      $('#code').focus();
      return;
    }
    closed(done.code === 'locked' ? 'This link is locked' : "This link doesn't work", done.detail);
  }

  document.addEventListener('DOMContentLoaded', () => {
    token = window.location.hash.slice(1);
    if (!TOKEN.test(token)) {
      token = '';
      closed('Join CLIVE', 'To use CLIVE on this phone, open the staff link George sent you, then type the code he tells you.');
      return;
    }
    // Inside another app's browser, its "Open in browser" carries the whole link to Safari or Chrome.
    $('#in-app').hidden = !IN_APP.test(navigator.userAgent || '');
    $('#form').hidden = false;
    $('#note').hidden = false;
    $('#form').addEventListener('submit', submit);
    $('#code').focus();
  });

  window.CliveJoin = { TOKEN, IN_APP };
}());
