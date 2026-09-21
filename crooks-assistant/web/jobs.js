/* CLIVE — the work in flight, as objects with names, and the strip that shows them.
 *
 * V0.5 slice C. The old screen had one state word under the orb for however many reads were
 * running, so "Thinking" covered a fast lane answering in 300 ms and a four-tool read graph
 * that took eleven seconds, and nothing on the glass said which. Invariant 5 and 6 ask for
 * the opposite: independent work, each piece named, each finishing when it finishes, all of
 * it inside ONE session — not a second assistant, not a second workspace, not a Split.
 *
 * The rules here, and nowhere else:
 *
 *   - A job has a STABLE IDENTITY. The same read reported twice is the same job, updated in
 *     place; that is what lets the strip be a list of work rather than a scrolling log.
 *   - A label is a verb and an object, in the owner's words: "Checking today's orders". Never
 *     a tool name, never a queue position, never a percentage nobody can act on (invariant 7:
 *     architecture must not leak into interaction language).
 *   - QUEUED → WORKING → DONE, or → FAILED. A failure is a state, with the reason and —
 *     only where it is safe — a retry. A read is safe to retry; anything that changes the
 *     shop is not, and this file refuses to offer it (invariant 9).
 *   - A finished job whose result is ON SCREEN collapses. `represent(id)` is how the scene
 *     says so. Until something says so, a done job keeps its one line: a result nobody can
 *     see yet is not a result.
 *   - The strip is not a dashboard. `visible()` is empty whenever the work it would describe
 *     is not worth a surface — no jobs, or every job collapsed — and `endTurn()` clears the
 *     ones that are finished and represented. Failures survive a turn, because a failure the
 *     owner has not read is not finished.
 */
(function (root, factory) {
  const api = factory();
  root.CrooksJobs = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const STATES = ['QUEUED', 'WORKING', 'DONE', 'FAILED'];
  const FINISHED = ['DONE', 'FAILED'];
  // What each state says on the strip, beside the job's own words.
  const STATE_WORDS = { QUEUED: 'queued', WORKING: 'working', DONE: 'done', FAILED: 'failed' };

  const MAX_JOBS = 12;          // a turn that wants more than this is not a strip, it is a log
  const MAX_LABEL = 48;         // one line on a 390px phone

  function label(job) {
    const words = `${job.verb || ''} ${job.object || ''}`.trim().replace(/\s+/g, ' ');
    return words.length > MAX_LABEL ? `${words.slice(0, MAX_LABEL - 1).trimEnd()}…` : words;
  }

  function create(options) {
    const opts = options || {};
    const now = opts.now || (() => Date.now());
    const onChange = typeof opts.onChange === 'function' ? opts.onChange : null;
    const jobs = new Map();     // id -> job, in the order they were first heard of

    function announce(why) {
      if (onChange) { try { onChange(visible(), why); } catch { /* a bad renderer never stops the work */ } }
    }

    // Upsert by id. Everything but the id is optional: a second report of a job that is
    // already known updates only what it carries, so "still working" does not erase the
    // summary a previous report already produced.
    function note(id, fields) {
      const key = String(id || '');
      if (!key) return null;
      const patch = fields || {};
      let job = jobs.get(key);
      if (!job) {
        if (jobs.size >= MAX_JOBS) return null;
        job = {
          id: key, verb: '', object: '', state: 'QUEUED', summary: '', reason: '',
          retryable: false, represented: false, startedAt: now(), endedAt: 0,
        };
        jobs.set(key, job);
      }
      if (patch.verb !== undefined) job.verb = String(patch.verb);
      if (patch.object !== undefined) job.object = String(patch.object);
      if (patch.summary !== undefined) job.summary = String(patch.summary);
      if (patch.reason !== undefined) job.reason = String(patch.reason);
      // Only a READ may be retried from here. A job that changes the shop goes back through
      // the proposal and confirmation path or not at all — this file has no authority to
      // re-run a write, and offering a button that looks like it does would be a lie.
      if (patch.retryable !== undefined) job.retryable = Boolean(patch.retryable) && patch.writes !== true;
      if (patch.state !== undefined && STATES.indexOf(patch.state) >= 0) {
        // A finished job is finished. A late "still working" from a poll that was already in
        // flight when the answer landed must not reopen it.
        if (FINISHED.indexOf(job.state) < 0) {
          job.state = patch.state;
          if (FINISHED.indexOf(job.state) >= 0) job.endedAt = now();
        }
      }
      announce('note');
      return Object.assign({}, job);
    }

    const start = (id, verb, object) => note(id, { verb, object, state: 'WORKING' });
    const queue = (id, verb, object) => note(id, { verb, object, state: 'QUEUED' });
    const done = (id, summary) => note(id, { state: 'DONE', summary: summary || '' });
    const fail = (id, reason, retryable) => note(id, { state: 'FAILED', reason: reason || '', retryable: Boolean(retryable) });

    // The scene now shows this job's result, so its line on the strip is redundant. Only a
    // finished job can be represented: collapsing work that is still running would hide the
    // one thing the strip is for.
    function represent(id) {
      const job = jobs.get(String(id || ''));
      if (!job || FINISHED.indexOf(job.state) < 0) return false;
      if (job.represented) return true;
      job.represented = true;
      announce('represented');
      return true;
    }

    // What the strip should show right now: everything unfinished, plus finished work whose
    // result is not yet on screen. A done-and-represented job is gone; a failure stays until
    // it is dismissed, because nobody has read it yet.
    function visible() {
      const out = [];
      for (const job of jobs.values()) {
        if (job.represented && job.state === 'DONE') continue;
        out.push(Object.assign({ label: label(job) }, job));
      }
      return out;
    }

    function dismiss(id) {
      const removed = jobs.delete(String(id || ''));
      if (removed) announce('dismissed');
      return removed;
    }

    // The turn is over. Finished work that has been represented is gone; a failure the owner
    // has not dismissed stays, and so does anything still running — invariant 5 says a job
    // outlives the question that started it.
    function endTurn() {
      let changed = false;
      for (const [key, job] of [...jobs.entries()]) {
        if (job.state === 'DONE') { jobs.delete(key); changed = true; }
      }
      if (changed) announce('turn over');
      return changed;
    }

    function reset() {
      if (!jobs.size) return false;
      jobs.clear();
      announce('reset');
      return true;
    }

    return {
      note, queue, start, done, fail, represent, dismiss, endTurn, reset,
      visible,
      all: () => [...jobs.values()].map((job) => Object.assign({ label: label(job) }, job)),
      get(id) { const job = jobs.get(String(id || '')); return job ? Object.assign({ label: label(job) }, job) : null; },
      get size() { return jobs.size; },
      running: () => [...jobs.values()].filter((job) => FINISHED.indexOf(job.state) < 0).length,
    };
  }

  /* ------------------------------------------------------------------ the strip */

  // One line per job: the words, the state, and — on a failure that is safe to re-run — a
  // retry. Built node by node; nothing here is ever handed a string of markup.
  function renderJob(doc, job, handlers) {
    const row = doc.createElement('li');
    row.className = 'job';
    row.dataset.state = STATE_WORDS[job.state] || 'queued';
    row.dataset.job = job.id;

    const dot = doc.createElement('span');
    dot.className = 'job-dot';
    dot.setAttribute('aria-hidden', 'true');
    row.appendChild(dot);

    const what = doc.createElement('span');
    what.className = 'job-what';
    what.textContent = job.label;
    row.appendChild(what);

    // The result, where there is one worth a few words. A done job with nothing to say says
    // "done" and no more; a fabricated summary would be worse than silence.
    const tail = doc.createElement('span');
    tail.className = 'job-tail';
    tail.textContent = job.state === 'FAILED'
      ? (job.reason || STATE_WORDS.FAILED)
      : (job.summary || STATE_WORDS[job.state] || '');
    row.appendChild(tail);

    if (job.state === 'FAILED' && job.retryable && handlers && handlers.onRetry) {
      const retry = doc.createElement('button');
      retry.className = 'job-retry';
      retry.setAttribute('type', 'button');
      retry.textContent = 'Try again';
      retry.setAttribute('aria-label', `Try again: ${job.label}`);
      retry.addEventListener('click', () => handlers.onRetry(job.id));
      row.appendChild(retry);
    }
    return row;
  }

  // Draw the strip into `container`, and hide it when there is nothing worth a surface. The
  // container is emptied and rebuilt: a strip is at most a dozen short lines, and a diff
  // here would buy nothing but a way for the list to go wrong.
  function render(container, list, handlers) {
    if (!container) return 0;
    const doc = (container.ownerDocument) || (typeof document !== 'undefined' ? document : null);
    if (!doc) return 0;
    const jobs = Array.isArray(list) ? list : [];
    while (container.firstChild) container.removeChild(container.firstChild);
    container.hidden = jobs.length === 0;
    if (!jobs.length) return 0;
    const ul = doc.createElement('ul');
    ul.className = 'job-list';
    for (const job of jobs) ul.appendChild(renderJob(doc, job, handlers));
    container.appendChild(ul);
    return jobs.length;
  }

  return { STATES, FINISHED, STATE_WORDS, MAX_JOBS, MAX_LABEL, create, render, label };
});
