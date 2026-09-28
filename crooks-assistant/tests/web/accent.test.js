/* The app's accent (round 9, G-03; round 11): the owner moved it from lilac to iOS blue on
 * 28 Sep 2026 ("remove the purple on the main clive app aswell and go for the ios blue"). What is
 * proved, by reading the stylesheets the app loads as CSS — their rules and custom properties:
 *
 * - The accent is one set of tokens on `body.alpha` (web/alpha.css), and they are iOS systemBlue
 *   and its filled-button blues; the lilac is gone from every stylesheet and script of the app.
 * - The change is appearance only: none of the app's stylesheets can reach anything — no url(),
 *   no @import, no image-set() — so a colour is all a stylesheet here can change.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const WEB = path.join(__dirname, '..', '..', 'web');
// The stylesheets web/index.html links, as the page loads them.
const INDEX = fs.readFileSync(path.join(WEB, 'index.html'), 'utf8');
const SHEETS = [...INDEX.matchAll(/<link[^>]+rel="stylesheet"[^>]+href="\/static\/([a-z0-9-]+\.css)"/g)].map((m) => m[1]);

// A stylesheet's rules: selector → { property: value }, comments taken out.
function rules(css) {
  const out = new Map();
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(text))) {
    const props = out.get(m[1].trim()) || {};
    for (const decl of m[2].split(';')) {
      const at = decl.indexOf(':');
      if (at > 0) props[decl.slice(0, at).trim()] = decl.slice(at + 1).trim();
    }
    out.set(m[1].trim(), props);
  }
  return out;
}

test('the app loads its stylesheets, alpha.css among them', () => {
  assert.ok(SHEETS.includes('alpha.css') && SHEETS.includes('style.css'), SHEETS.join(', '));
});

test('the accent is iOS systemBlue, set once on body.alpha, and the lilac is gone (G-03)', () => {
  const alpha = rules(fs.readFileSync(path.join(WEB, 'alpha.css'), 'utf8'));
  const tokens = alpha.get('body.alpha');
  assert.ok(tokens, 'body.alpha sets the tokens');
  assert.deepEqual(
    ['--acc', '--acc-glow', '--acc-f1', '--acc-f2', '--acc-t1', '--acc-t2'].map((k) => tokens[k]),
    ['10,132,255', '0,122,255', '10,132,255', '0,100,210', '64,156,255', '0,113,227'],
  );
  assert.equal(tokens['--border-active'], 'rgba(10,132,255,.6)');
  // The lilac triples the accent used to be, nowhere in the app's page files.
  for (const file of fs.readdirSync(WEB).filter((f) => /\.(css|js|html)$/.test(f))) {
    const text = fs.readFileSync(path.join(WEB, file), 'utf8').replace(/\s+/g, '');
    for (const lilac of ['196,161,240', '157,107,200', '122,85,189', '93,58,152', '150,110,214', '104,66,170']) {
      assert.ok(!text.includes(lilac), `${file} still has the lilac ${lilac}`);
    }
  }
});

test('the app’s stylesheets reach nothing: a colour is all they can change (G-03)', () => {
  for (const sheet of SHEETS) {
    const css = fs.readFileSync(path.join(WEB, sheet), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
    for (const reach of [/url\s*\(/i, /@import/i, /image-set\s*\(/i, /expression\s*\(/i]) {
      assert.ok(!reach.test(css), `${sheet} can reach something: ${reach}`);
    }
  }
});
