/* The action state machine: one definition, shared by the renderer and the page.
 *
 * A card that offers a change passes through a small number of states, and until this file
 * existed each of them was a bare string invented where it was needed — `committing` in
 * ui.js, `done` and `settled` in app.js, the Mac's own codes on top of both. Nothing said
 * which of those meant finished. So the correction path guessed, and guessed one state too
 * narrowly:
 *
 *     if (current === 'arming' || current === 'armed') node.settle(state, label);
 *
 * A card the owner has tapped is in `committing` — the state that says "Applying…" — and
 * that guard refused to touch it. On 11 September the Mac proved a reply SENT at 00:21:53,
 * told the tablet at 00:21:55, and the tablet went on saying "Applying…" for the remaining
 * six minutes of the session, reconciling once a turn and changing nothing. The owner asked
 * twice; he was right and the machine was wrong.
 *
 * The rules here, and nowhere else:
 *
 *   - Ten named states. Four of them are terminal: VERIFIED, FAILED, EXPIRED, UNDONE.
 *   - The Mac's terminal status is authoritative and settles a card from ANY non-terminal
 *     state — not from two of them.
 *   - A terminal card is never settled again, by anyone. (That is what the old guard was
 *     reaching for: a background correction must not steal a card. It is kept exactly.)
 *   - A state this build does not know is LIVE, never terminal: an unknown word must stay
 *     correctable, and must never be mistaken for a change that finished.
 *   - Success is VERIFIED and only VERIFIED. EXECUTED — sent, not yet proven — settles
 *     nothing and shows nothing.
 *   - An undo offer is a property of a completed action. It is never counted as waiting.
 *
 * The dataset.state tokens are unchanged: the tablet has always written `arming`, `armed`,
 * `committing`, `done`, and the Mac's codes, and a screen in the owner's hand is not worth
 * a rename. The names above are what those tokens MEAN, in one table.
 */
(function (root, factory) {
  const api = factory();
  root.CrooksActionState = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const STATES = ['READY', 'STAGED', 'ARMING', 'ARMED', 'EXECUTING', 'VERIFYING', 'VERIFIED', 'FAILED', 'EXPIRED', 'UNDONE'];
  // Finished. Nothing moves a card out of one of these, and nothing animates in one.
  const TERMINAL = ['VERIFIED', 'FAILED', 'EXPIRED', 'UNDONE'];
  // The change is with the Mac: claimed and sending (EXECUTING), or sent and being proven
  // (VERIFYING). These are the only states a surface may animate in, and the only ones the
  // watchdog looks for.
  const IN_FLIGHT = ['EXECUTING', 'VERIFYING'];

  // What a surface writes into dataset.state for each named state.
  const TOKEN = {
    READY: 'unavailable', STAGED: 'pending', ARMING: 'arming', ARMED: 'armed',
    EXECUTING: 'committing', VERIFYING: 'verifying', VERIFIED: 'verified',
    FAILED: 'failed', EXPIRED: 'expired', UNDONE: 'undone',
  };

  // Every word that has ever reached dataset.state — from the renderer, from the page, and
  // from the Mac's own outcome codes — and the state it means. A word that is not here is
  // STAGED: live, correctable, and never mistaken for finished.
  const TOKENS = {
    '': 'READY', ready: 'READY', unavailable: 'READY', unsupported: 'READY',
    pending: 'STAGED', staged: 'STAGED', proposed: 'STAGED', batch_member: 'STAGED',
    arming: 'ARMING', holding: 'ARMING',
    armed: 'ARMED', held: 'ARMED', not_armed: 'ARMED',
    committing: 'EXECUTING', executing: 'EXECUTING', in_progress: 'EXECUTING',
    verifying: 'VERIFYING', executed: 'VERIFYING', unknown: 'VERIFYING',
    verified: 'VERIFIED', done: 'VERIFIED', already_executed: 'VERIFIED',
    undone: 'UNDONE',
    failed: 'FAILED', unverified: 'FAILED', stale: 'FAILED', refused: 'FAILED', blocked: 'FAILED',
    service_unavailable: 'FAILED', writes_disabled: 'FAILED', not_authorised: 'FAILED',
    not_authorised_local: 'FAILED', allow_list_missing: 'FAILED', scope_missing: 'FAILED',
    gmail_scope_missing: 'FAILED', identity_unverified: 'FAILED', wrong_session: 'FAILED', read_only: 'FAILED',
    expired: 'EXPIRED', settled: 'EXPIRED', revoked: 'EXPIRED',
  };

  // The words on the surface, for every outcome either side can produce. One table: the
  // renderer's settled label and the page's commit label were two copies of it.
  const LABELS = {
    verified: 'Applied', done: 'Applied', already_executed: 'Already applied', undone: 'Undone',
    executing: 'Applying…', executed: 'Applying…', committing: 'Applying…', in_progress: 'Applying…', verifying: 'Applying…',
    stale: 'Not applied', expired: 'Expired', settled: 'No longer waiting', revoked: 'Withdrawn',
    failed: 'Not applied', unverified: 'Not confirmed', refused: 'Refused', not_armed: 'Hold first',
    blocked: 'Refused', batch_member: 'Part of a batch', service_unavailable: 'Not applied',
    writes_disabled: 'Switched off', not_authorised: 'Not on the list',
    not_authorised_local: 'Not from the server itself', allow_list_missing: 'Not configured',
    scope_missing: 'Not permitted', wrong_session: 'Not this conversation', unknown: 'No longer waiting',
  };

  // What the Mac's status for a proposal does to a card on screen. A status that is not here
  // settles nothing: PENDING is still waiting, and EXECUTING/EXECUTED are the change being
  // made and proven — an outcome the owner has not been given yet, and must not be shown one.
  const SETTLED = {
    verified: ['done', 'Done'],
    unverified: ['failed', 'Not confirmed'],
    failed: ['failed', 'Failed'],
    stale: ['failed', 'It changed first'],
    expired: ['settled', 'Expired'],
    revoked: ['revoked', 'Withdrawn'],
  };

  function stateOf(token) {
    const word = String(token === null || token === undefined ? '' : token);
    if (STATES.indexOf(word) !== -1) return word;                       // already a state name
    return Object.prototype.hasOwnProperty.call(TOKENS, word) ? TOKENS[word] : 'STAGED';
  }

  function tokenFor(state) { return TOKEN[String(state)] || 'pending'; }

  function labelFor(token, fallback) {
    const word = String(token || '');
    return Object.prototype.hasOwnProperty.call(LABELS, word) ? LABELS[word] : (fallback === undefined ? 'Not available' : fallback);
  }

  function isTerminal(x) { return TERMINAL.indexOf(stateOf(x)) !== -1; }
  function isLive(x) { return !isTerminal(x); }
  function isInFlight(x) { return IN_FLIGHT.indexOf(stateOf(x)) !== -1; }

  function settledFor(status) {
    const entry = SETTLED[String(status || '').toLowerCase()];
    if (!entry) return null;
    return { token: entry[0], label: entry[1], state: stateOf(entry[0]) };
  }

  // ------------------------------------------------------------------ the surfaces on screen

  function surfaceIn(node) {
    return node && typeof node.querySelector === 'function' ? node.querySelector('.action-surface') : null;
  }

  function tokenOf(node) {
    const surface = surfaceIn(node);
    return surface && surface.dataset ? String(surface.dataset.state || '') : '';
  }

  // Every card with a proposal on it, once each, in the order given.
  function cards(nodes) {
    const out = [];
    const seen = new Set();
    for (const node of nodes || []) {
      if (!node || seen.has(node) || !node.dataset || !node.dataset.proposal) continue;
      seen.add(node);
      out.push({ node, id: String(node.dataset.proposal), token: tokenOf(node) });
    }
    return out;
  }

  /* One card, settled — or deliberately not.
   *
   * The whole of the D-1 fix is the second line: a card is settled from every state except a
   * terminal one, instead of from two of them. Returns true when it settled the card. */
  function settleCard(node, token, label) {
    if (!node || typeof node.settle !== 'function') return false;
    if (isTerminal(tokenOf(node))) return false;    // settled is settled, whoever is asking
    node.settle(token, label);
    return true;
  }

  function settleProposals(ids, token, label, nodes) {
    const wanted = new Set((ids || []).map(String));
    const settled = [];
    const refused = [];
    for (const card of cards(nodes)) {
      if (!wanted.has(card.id) || typeof card.node.settle !== 'function') continue;
      if (settleCard(card.node, token, label)) settled.push(card.id);
      else refused.push(card.id);
    }
    return { settled, refused };
  }

  // Every card still worth asking the Mac about: anything that has not finished. A settled
  // card is never asked about again — six reconciles of two finished proposals is what the
  // live session's telemetry recorded, once per turn, with nobody reading it.
  function liveProposalIds(nodes) {
    const ids = [];
    const seen = new Set();
    for (const card of cards(nodes)) {
      if (isTerminal(card.token) || seen.has(card.id)) continue;
      seen.add(card.id);
      ids.push(card.id);
    }
    return ids;
  }

  // The last resort. A surface that is still in flight after its proposal finished on the
  // Mac has no way back on its own — it may have no gesture wiring at all — so its state is
  // written here, directly. Never routine: every one of these is a defect, and the caller
  // records it as one.
  function force(node, token, label) {
    const surface = surfaceIn(node);
    if (!surface || !surface.dataset) return false;
    surface.dataset.state = token;
    if (typeof surface.setAttribute === 'function') surface.setAttribute('aria-disabled', 'true');
    const words = typeof surface.querySelector === 'function' ? surface.querySelector('.action-label') : null;
    const target = words || (surface.childNodes ? surface.childNodes[0] : null);
    if (target && label !== undefined) target.textContent = String(label);
    return true;
  }

  /* The whole correction pass: what the Mac says, applied to what is on screen.
   *
   * `states` is the map from GET /actions/states. Returns:
   *   corrected — cards settled by the Mac's terminal status, which is routine;
   *   stuck     — cards STILL in flight after that, which is not: each one is a surface the
   *               owner is watching spin over a change that finished. Corrected here and
   *               handed back so the caller can say so out loud. */
  function reconcile(nodes, states) {
    const list = cards(nodes);
    const corrected = [];
    const stuck = [];
    const answers = {};
    for (const id of Object.keys(states || {})) {
      const answer = settledFor(states[id] && states[id].status);
      if (!answer) continue;
      answers[id] = answer;
      if (settleProposals([id], answer.token, answer.label, nodes).settled.length) corrected.push(id);
    }
    for (const card of list) {
      const answer = answers[card.id];
      if (!answer) continue;
      const now = tokenOf(card.node);
      if (!isInFlight(now)) continue;
      force(card.node, answer.token, answer.label);
      stuck.push({
        proposal_id: card.id, was: stateOf(now), state: answer.state,
        status: String((states[card.id] || {}).status || '').toLowerCase(),
      });
    }
    return { corrected, stuck };
  }

  /* Every other card still offering a change to an entity that has just changed.
   *
   * A proposal is prepared from a read, and the Mac checks that read again before it writes:
   * once the thing has moved, a card prepared against the old state can only be refused as
   * stale. So the affordance goes now, with the reason on it, rather than after a gesture
   * that cannot work. `keep` is the proposal that just landed and `skip` the nodes its answer
   * drew — the success card and the undo it carries are not stale, they are the proof. */
  function staleAffordances(nodes, ref, keep, skip) {
    if (!ref) return [];
    const untouched = new Set(skip || []);
    const retired = [];
    for (const card of cards(nodes)) {
      if (card.id === String(keep || '') || untouched.has(card.node)) continue;
      if (String(card.node.dataset.ref || '') !== String(ref)) continue;
      if (String(card.node.dataset.type || '') !== 'confirmation') continue;
      // Not one that is finished, and not one the Mac is acting on this second.
      if (isTerminal(card.token) || isInFlight(card.token)) continue;
      if (settleCard(card.node, 'stale', 'It changed first')) retired.push(card.id);
    }
    return retired;
  }

  // What is actually waiting for the owner, and what is merely on offer. An undo is a
  // property of a change that is finished; counting it as unfinished work told the owner
  // "2 changes still waiting over there" when nothing was waiting at all.
  function waiting(states) {
    const pending = [];
    const undoable = [];
    for (const id of Object.keys(states || {})) {
      const entry = states[id] || {};
      if (String(entry.status || '').toLowerCase() !== 'pending') continue;
      if (entry.undo_of) undoable.push(String(id)); else pending.push(String(id));
    }
    return { pending, undoable };
  }

  return {
    STATES, TERMINAL, IN_FLIGHT, TOKENS, TOKEN, LABELS, SETTLED,
    stateOf, tokenFor, labelFor, isTerminal, isLive, isInFlight, settledFor,
    surfaceIn, tokenOf, cards, settleCard, settleProposals, liveProposalIds, force, reconcile,
    staleAffordances, waiting,
  };
});
