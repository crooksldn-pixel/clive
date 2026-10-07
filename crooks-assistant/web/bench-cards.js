/* The card frame inside the test bench (web/bench-cards.html): a result's cards, drawn by CLIVE's own
 * renderer (web/ui.js) exactly as the tablet drew them. The bench screen (web/bench.js) calls
 * CliveBenchCards.draw(items) once the frame has loaded and sizes the frame to what it answers.
 *
 * Promises: only CrooksUI.render draws, so every string goes in as text, as on the tablet; nothing on
 * a card is wired, because the app that acts on a tap is not on this page; a card the renderer does
 * not know is named, not hidden.
 */
(function () {
  'use strict';

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function note(text) {
    const p = document.createElement('p');
    p.className = 'bench-none';
    p.textContent = text;
    return p;
  }

  function draw(items) {
    const stack = document.getElementById('cards');
    clear(stack);
    const out = window.CrooksUI.render(Array.isArray(items) ? items : [], {});
    out.nodes.forEach((node) => stack.appendChild(node));
    if (!out.nodes.length) {
      stack.appendChild(note(out.skipped.length
        ? 'CLIVE drew nothing this screen can show: ' + out.skipped.join(', ') + '.'
        : 'No cards.'));
    }
    return { height: Math.ceil(document.documentElement.scrollHeight), drawn: out.nodes.length, skipped: out.skipped };
  }

  window.CliveBenchCards = { draw: draw };
})();
