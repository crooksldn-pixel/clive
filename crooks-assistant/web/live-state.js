/* CLIVE — the one interaction state, and the only thing allowed to decide it.
 *
 * V0.5 invariant 2: a single canonical state drives the microphone, the orb, the transcript,
 * the reasoning line, the results and the speech —
 *
 *     IDLE → LISTENING → HEARING → UNDERSTOOD → THINKING → WORKING → RESPONDING → IDLE
 *
 * and error, interruption and recovery are states in that machine, not exceptions to it.
 *
 * Until this file existed the page had no state; it had nine presentation words written into
 * `stage.dataset.state` from twenty-six places, and anything that wanted to know what CLIVE
 * was doing read one of them back off the DOM. That is why the dead interval between release
 * and the first tool was unexplainable: nothing owned it, so nothing could name it.
 *
 * The rules here, and nowhere else:
 *
 *   - Transitions are EVENTS, never assignments. `pointerDown()`, `partial()`, `final()`,
 *     `thinking()`, `working()`, `responding()`, `idle()`. A caller says what happened; this
 *     file decides what that means.
 *   - Every transition is checked against ALLOWED. An illegal one does not happen and is
 *     counted in `refusals()` — silently applying it is how a screen starts lying, and
 *     throwing would take the page down over a cosmetic ordering bug.
 *   - Nothing here reads the DOM, and nothing here writes it. The page subscribes.
 *   - The presentation words the Mac and the old page still speak are mapped in one table
 *     (`fromPresentation`), so the migration is a translation and not a second machine.
 *   - Evidence (invariant 11) is privacy-minimised by construction: this file is never given
 *     transcript text, only its length, so a history that leaks cannot leak what was said.
 */
(function (root, factory) {
  const api = factory();
  root.CrooksLiveState = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  // The canonical eight, plus the three the contract requires to be explicit.
  const STATES = [
    'IDLE',         // nothing in flight; the orb is asleep and the owner owns the turn
    'LISTENING',    // the pointer is down and the microphone is open
    'HEARING',      // speech is arriving — partial text, or energy where there is no recogniser
    'UNDERSTOOD',   // the pointer is up and the final transcript has settled on screen
    'THINKING',     // the turn is with the model and no tool has been named yet
    'WORKING',      // at least one job is running and can be named
    'RESPONDING',   // the first speakable words exist and speech has begun
    'INTERRUPTED',  // the owner spoke over CLIVE, or cancelled; work may still be in flight
    'FAULT',        // this turn cannot continue, and the screen says why
    'RECOVERING',   // a fault is being cleared — the owner is not stuck in FAULT
  ];

  // The turn is live: the page is not free to reset the screen, and a hold means "interrupt".
  const IN_TURN = ['THINKING', 'WORKING', 'RESPONDING'];
  // Speech is being captured.
  const CAPTURING = ['LISTENING', 'HEARING'];

  // What may follow what. The spine is the contract's arrow; the rest is the truth of a real
  // turn: a fast path answers without ever naming a tool (THINKING → RESPONDING), a read
  // comes back and the model thinks again (WORKING → THINKING), a job finishes while CLIVE
  // is already speaking (RESPONDING → WORKING), and the owner may start talking at any point
  // that is not already listening.
  const ALLOWED = {
    IDLE: ['LISTENING', 'FAULT'],
    LISTENING: ['HEARING', 'UNDERSTOOD', 'IDLE', 'FAULT'],
    HEARING: ['HEARING', 'UNDERSTOOD', 'IDLE', 'FAULT'],
    UNDERSTOOD: ['THINKING', 'WORKING', 'RESPONDING', 'INTERRUPTED', 'IDLE', 'FAULT'],
    THINKING: ['WORKING', 'RESPONDING', 'INTERRUPTED', 'IDLE', 'FAULT'],
    WORKING: ['WORKING', 'THINKING', 'RESPONDING', 'INTERRUPTED', 'IDLE', 'FAULT'],
    RESPONDING: ['WORKING', 'THINKING', 'INTERRUPTED', 'IDLE', 'FAULT'],
    INTERRUPTED: ['LISTENING', 'THINKING', 'WORKING', 'RESPONDING', 'IDLE', 'FAULT'],
    FAULT: ['RECOVERING', 'LISTENING', 'IDLE'],
    RECOVERING: ['IDLE', 'LISTENING', 'THINKING', 'WORKING', 'FAULT'],
  };

  // The words the rest of the system still speaks — the page's own `stage.dataset.state`, and
  // the running tool the Mac reports on /state — against the state each one MEANS. One table,
  // so there is exactly one place where the old vocabulary is understood.
  const FROM_PRESENTATION = {
    READY: 'IDLE', IDLE: 'IDLE',
    LISTENING: 'LISTENING',
    HEARING: 'HEARING',
    TRANSCRIBING: 'UNDERSTOOD',   // the hold is over; the Mac is settling what it heard
    UNDERSTOOD: 'UNDERSTOOD',
    THINKING: 'THINKING',
    'CHECKING SHOPIFY': 'WORKING',
    'CHECKING EMAIL': 'WORKING',
    WORKING: 'WORKING',
    SPEAKING: 'RESPONDING',
    RESPONDING: 'RESPONDING',
    SUCCESS: 'RESPONDING',        // a verified change is CLIVE answering, not a fourth mode
    ERROR: 'FAULT',
    FAULT: 'FAULT',
  };

  const HISTORY_LIMIT = 200;      // a long session must not grow the page's memory without end

  function create(options) {
    const opts = options || {};
    const now = opts.now || (() => Date.now());
    const listeners = [];

    let state = 'IDLE';
    let since = now();
    let turn = 0;               // which turn these marks belong to; a new hold starts a new one
    const history = [];
    const refused = [];
    let marks = emptyMarks();

    function emptyMarks() {
      return {
        turn,
        pointerDownAt: 0, releasedAt: 0,
        acknowledgedMs: null,       // pointer-down → the orb is visibly awake
        transcriptMs: null,         // release → the final transcript is on screen
        progressMs: null,           // release → the first honest "I am doing something"
        usefulMs: null,             // release → the first useful thing the owner can read
        respondingMs: null,         // release → speech begins
        partials: 0, heardChars: 0, // privacy-minimised: how much was said, never what
        interruptions: 0, faults: 0,
      };
    }

    function emit(from, to, reason) {
      const at = now();
      history.push({ turn, from, to, reason: reason || '', at });
      if (history.length > HISTORY_LIMIT) history.shift();
      for (const fn of listeners) {
        try { fn(to, from, reason || ''); } catch { /* a bad subscriber never stops the machine */ }
      }
      return at;
    }

    // The single door. Everything below is a caller saying what happened; this decides.
    function go(to, reason) {
      if (STATES.indexOf(to) < 0) { refused.push({ from: state, to, reason: 'unknown state' }); return false; }
      // Asking for the state the machine is already in is SATISFIED, not refused — and not a
      // transition either, so nothing is announced. (WORKING and HEARING are the exceptions:
      // they name themselves in ALLOWED because a second job and a second partial are each a
      // real event the page wants to hear about.)
      if (to === state && (ALLOWED[state] || []).indexOf(to) < 0) return true;
      if ((ALLOWED[state] || []).indexOf(to) < 0) {
        refused.push({ from: state, to, reason: reason || '' });
        return false;
      }
      const from = state;
      state = to;
      since = emit(from, to, reason);
      return true;
    }

    /* ----------------------------------------------------------------- events */

    // The pointer is down on the voice surface. This is the acknowledgement the owner is
    // waiting for, so it is measured from here and it happens SYNCHRONOUSLY — before the
    // recorder, before any permission prompt, before the first byte of audio.
    function pointerDown() {
      const at = now();
      // Cutting in is the first half of holding: the interruption is recorded against the
      // turn being cut off, which is the turn whose marks are still current.
      if (IN_TURN.indexOf(state) >= 0 || state === 'UNDERSTOOD') { marks.interruptions += 1; go('INTERRUPTED', 'barge-in'); }
      if (state === 'FAULT') go('RECOVERING', 'hold after fault');
      // A second pointer-down while already capturing is not a new turn. Deciding that BEFORE
      // anything is reset is the point: a refused hold must not throw away the marks of the
      // hold that is actually in progress.
      if ((ALLOWED[state] || []).indexOf('LISTENING') < 0) {
        refused.push({ from: state, to: 'LISTENING', reason: 'already capturing' });
        return false;
      }
      turn += 1;
      marks = emptyMarks();
      marks.pointerDownAt = at;
      go('LISTENING', 'pointer down');
      marks.acknowledgedMs = now() - at;
      return true;
    }

    // Speech is arriving while the owner is still speaking. `chars` is a LENGTH: this file is
    // never given the words, so nothing it keeps can repeat them.
    function partial(chars) {
      if (CAPTURING.indexOf(state) < 0) { refused.push({ from: state, to: 'HEARING', reason: 'partial outside capture' }); return false; }
      marks.partials += 1;
      marks.heardChars = Math.max(marks.heardChars, Number(chars) || 0);
      return go('HEARING', 'partial speech');
    }

    // The pointer is up and the transcript has settled. Release is the instant the owner
    // starts waiting, so every remaining mark is measured from it.
    function final(chars) {
      const at = now();
      if (!marks.releasedAt) marks.releasedAt = at;
      marks.heardChars = Math.max(marks.heardChars, Number(chars) || 0);
      const moved = go('UNDERSTOOD', 'final transcript');
      if (moved && marks.transcriptMs === null) marks.transcriptMs = at - marks.releasedAt;
      return moved;
    }

    // The pointer is up but nothing was heard — too short, or silence. The turn ends where it
    // started rather than leaving the orb awake with nothing behind it.
    function heardNothing(why) {
      if (!marks.releasedAt) marks.releasedAt = now();
      return go('IDLE', why || 'nothing heard');
    }

    function thinking(reason) {
      const moved = go('THINKING', reason || 'model');
      if (moved) noteProgress();
      return moved;
    }

    // At least one job is running and can be named. `reason` is the job's own verb, so the
    // history says which work moved the state, not merely that it moved.
    function working(reason) {
      const moved = go('WORKING', reason || 'job');
      if (moved) noteProgress();
      return moved;
    }

    function noteProgress() {
      if (marks.progressMs === null && marks.releasedAt) marks.progressMs = now() - marks.releasedAt;
    }

    // Something the owner can actually read has landed — a card, a number, a completed job's
    // summary. Not a spinner, and not a state word. This is the measurement the whole slice
    // exists to move, so it is recorded wherever the turn happens to be.
    function usefulResult(reason) {
      if (marks.usefulMs === null && marks.releasedAt) marks.usefulMs = now() - marks.releasedAt;
      emit(state, state, reason || 'useful result');
      return true;
    }

    function responding(reason) {
      const moved = go('RESPONDING', reason || 'speech');
      if (moved && marks.respondingMs === null && marks.releasedAt) marks.respondingMs = now() - marks.releasedAt;
      return moved;
    }

    // The owner cut in, or cancelled. Work already in flight is not this file's business —
    // invariant 5 says a job keeps going — so INTERRUPTED is about the CONVERSATION only.
    function interrupt(reason) {
      if (IN_TURN.indexOf(state) < 0 && state !== 'UNDERSTOOD') {
        refused.push({ from: state, to: 'INTERRUPTED', reason: 'nothing to interrupt' });
        return false;
      }
      marks.interruptions += 1;
      return go('INTERRUPTED', reason || 'owner interrupted');
    }

    function fault(reason) {
      marks.faults += 1;
      return go('FAULT', reason || 'fault');
    }

    // A fault is cleared deliberately, and the machine says so on the way out. Going straight
    // from FAULT to IDLE would make a recovered screen indistinguishable from one that never
    // failed, which is how a stale error line survives into the next question.
    function recover(reason) {
      if (state !== 'FAULT') { refused.push({ from: state, to: 'RECOVERING', reason: 'not in fault' }); return false; }
      return go('RECOVERING', reason || 'recovered');
    }

    function idle(reason) {
      return go('IDLE', reason || 'turn over');
    }

    // The bridge for everything not yet migrated: a presentation word in, the state it means
    // out. An unknown word is refused rather than guessed — a screen that invents a state is
    // worse than one that keeps the last true one.
    function fromPresentation(word, reason) {
      const mapped = FROM_PRESENTATION[String(word || '').toUpperCase()];
      if (!mapped) { refused.push({ from: state, to: String(word), reason: 'unknown presentation word' }); return false; }
      if (mapped === 'RESPONDING') return responding(reason || `presentation:${word}`);
      if (mapped === 'WORKING') return working(reason || `presentation:${word}`);
      if (mapped === 'FAULT') return fault(reason || `presentation:${word}`);
      return go(mapped, reason || `presentation:${word}`);
    }

    return {
      get state() { return state; },
      get turn() { return turn; },
      inTurn: () => IN_TURN.indexOf(state) >= 0,
      capturing: () => CAPTURING.indexOf(state) >= 0,
      heldFor: () => now() - since,
      subscribe(fn) { listeners.push(fn); return () => { const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); }; },
      pointerDown, partial, final, heardNothing,
      thinking, working, usefulResult, responding,
      interrupt, fault, recover, idle,
      fromPresentation,
      marks: () => Object.assign({}, marks),
      history: () => history.slice(),
      refusals: () => refused.slice(),
    };
  }

  return { STATES, IN_TURN, CAPTURING, ALLOWED, FROM_PRESENTATION, create };
});
