/* What a member of the team said or typed, read against their own list (web/today.js).
 *
 * George, 2 October: "any way they intend to act can be accepted as input: a click, speech,
 * typing". A tap is a step; so is a short sentence about one job: "I've packed 2106", "done with
 * the hoodies", "I'll take the next one", "give it back", "undo". Those are read here, on the
 * phone, against the jobs the screen is showing, and done at once with the same routes a tap uses
 * (app/routes/today.py), so nobody waits for an assistant to answer "packed".
 *
 * The rules that keep it honest:
 *   - Only the steps a tap can take: take a job, mark an order packed, finish, give it back,
 *     undo. Nothing here reaches the shop or the inbox.
 *   - Only a sentence that is about one step and nothing more. Any word it cannot place ("done,
 *     left it by the door"), a "not" or a "didn't", a question, two jobs at once: CLIVE reads it
 *     instead (`ask`), with the person's own assistant and its own rules.
 *   - Something only George may do (a refund, a discount, cancelling an order, a price, the
 *     settings) is never tried: it comes back as `george`, and the page notes it for him.
 *   - Two jobs that fit equally: `pick`, and the person chooses. Never a guess.
 *
 * No dependency on the page, so it runs under Node (tests/web/today-say.test.js).
 */
(function (root, factory) {
  const api = factory();
  root.CliveSay = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  // Words that carry nothing about which step or which job.
  const FILLER = new Set(('i ive im id ill have has had just it its this that thats the a an one order orders job jobs '
    + 'with all now please pls mate bro ok okay yeah yep yes so and is me my for on to been already cheers thanks ta '
    + 'thank you right then there we our up off as well can could will would go gonna going need be am are was of '
    + 'in at it\'s about lets let').split(' '));
  const QUESTION = /^(how|what|why|when|where|who|which|is|are|do|does|did|has|have|should|shall|whats|whos|wheres)\b/;

  // A step, by the words that mean it. Longer phrases first: "give it back" before "give".
  const STEPS = [
    ['undo', ['undo that', 'undo', 'take that back', 'go back', 'oops', 'my mistake', 'mistake', 'wrong one', 'cancel that', 'cancel it']],
    ['release', ['give it back', 'give back', 'giving it back', 'hand it back', 'put it back', 'cant do', 'cannot do', 'drop it', 'release', 'someone else', 'not mine', 'leave it']],
    ['next', ['next one', 'next job', 'the next', 'next']],
    ['packed', ['packed up', 'packed', 'boxed up', 'boxed', 'bagged up', 'bagged']],
    ['done', ['all done', 'did it', 'done', 'finished', 'finish', 'completed', 'complete', 'sorted', 'replied', 'answered', 'counted']],
    ['claim', ['ill take', 'ill do', 'im doing', 'im on', 'on it', 'got it', 'take', 'taking', 'claim', 'grab', 'start', 'starting', 'doing', 'do', 'mine', 'pack']],
  ];
  // What only George does (app/people/staff.py keeps them from the team): asked for, never tried.
  const GEORGE = /\b(refund\w*|money back|discount\w*|promo code|voucher\w*|gift card\w*|store credit|price\w*|reprice|compensat\w*|settings?|password\w*|cancel+(?:led|ing)? (?:the |this |that |an |his |her |their )?order|cancel+(?:led|ing)? #?\d{3,6}|change (?:the |their |his |her )?address|edit (?:the |this )?order)\b/;
  const NEGATION = /\b(not|never|didnt|havent|hasnt|wasnt|isnt|wont|dont|nothing)\b/;
  // Steps that may be said together: "packed and done", "I'll take the next one".
  const TOGETHER = new Set(['packed+done', 'done+packed', 'next+claim', 'claim+next']);
  const SHOW_NEXT = /^(whats next|what is next|what now|whats now|what do i do( now| next)?|what next)$/;

  function words(text) {
    return String(text || '').toLowerCase().replace(/[’']/g, '').replace(/[^a-z0-9#\s]/g, ' ').replace(/\s+/g, ' ').trim();
  }

  // A word's plain form, so "hoodies" finds "hoodie", "tees" finds "tee" and "boxes" finds "box".
  function stem(word) {
    let w = String(word || '');
    if (w.length > 3 && w.endsWith('s') && !w.endsWith('ss')) w = w.slice(0, -1);
    if (w.length > 3 && w.endsWith('e')) w = w.slice(0, -1);
    if (w.length > 3 && w.endsWith('y')) w = w.slice(0, -1) + 'i';
    return w;
  }

  /* `board`: { mine: [card], grabs: [card] }, each card { key, kind, mine, order ('#2106' or ''),
   * claimed, title, words: [its title's and its lines' words] } as web/today.js makes them, the first of `mine` being the job on
   * screen now and the first of `grabs` the one shown next. Returns one of:
   *   { do: 'claim'|'packed'|'done'|'release', job }   { do: 'undo' }   { do: 'next', job }
   *   { do: 'pick', step, jobs }   { do: 'show' } (what is next)   { do: 'george' }   { do: 'ask' }
   *   { do: 'none' } */
  function read(text, board) {
    const said = words(text);
    if (!said) return { do: 'none' };
    const raw = String(text || '');
    const mine = (board && board.mine) || [];
    const grabs = (board && board.grabs) || [];
    if (GEORGE.test(said)) return QUESTION.test(said) || raw.includes('?') ? { do: 'ask' } : { do: 'george' };
    if (SHOW_NEXT.test(said.replace(/\s*#?$/, ''))) return { do: 'show' };
    if (raw.includes('?') || QUESTION.test(said)) return { do: 'ask' };
    let rest = ` ${said} `;
    let step = '';
    for (const [name, phrases] of STEPS) {
      for (const phrase of phrases) {
        const at = rest.indexOf(` ${phrase} `);
        if (at === -1) continue;
        if (!step) step = name;
        else if (step !== name && !TOGETHER.has(`${step}+${name}`)) return { do: 'ask' };
        rest = rest.slice(0, at) + ' ' + rest.slice(at + phrase.length + 1);
      }
    }
    if (!step) return { do: 'ask' };
    if (step !== 'release' && step !== 'undo' && NEGATION.test(said)) return { do: 'ask' };
    const left = rest.split(' ').filter((w) => w && !FILLER.has(w));
    if (step === 'undo') return left.length ? { do: 'ask' } : { do: 'undo' };
    if (step === 'next') {
      if (left.length) return { do: 'ask' };
      return grabs.length ? { do: 'claim', job: grabs[0] } : { do: 'ask' };
    }
    let found = target(left, mine.concat(grabs));
    if (found === null) return { do: 'ask' };                          // a word it could not place
    if (step === 'packed' && found.length) {
      found = found.filter((j) => j.kind === 'pack_order');            // only an order is packed
      if (!found.length) return { do: 'ask' };
    }
    if (found.length > 1) {
      // Several fit: the one already in their hands is the one they mean when they say it is done.
      const held = found.filter((j) => j.mine && j.claimed);
      if (step !== 'claim' && held.length === 1) return { do: step, job: held[0] };
      return { do: 'pick', step, jobs: found.slice(0, 3) };
    }
    let job = found[0];
    if (!job) {
      // No job named: the one on screen. "Done" and "packed" are about the job in hand; "I'll take
      // it" is about the one shown next.
      job = step === 'claim' ? (mine.find((j) => !j.claimed) || grabs[0]) : mine.find((j) => j.claimed);
      if (!job) return { do: 'ask' };
    }
    if (step === 'packed' && job.kind !== 'pack_order') return { do: 'ask' };
    if (step === 'release' && !(job.mine && job.claimed)) return { do: 'ask' };
    return { do: step, job };
  }

  // The job the words left over name: [] for none named, [job] for one, several when they fit
  // equally, and null when a word names nothing on the list.
  function target(left, pool) {
    if (!left.length) return [];
    const numbers = left.filter((w) => /^#?\d{3,6}$/.test(w)).map((w) => '#' + w.replace('#', ''));
    const others = left.filter((w) => !/^#?\d{3,6}$/.test(w));
    let hits = pool;
    if (numbers.length) {
      if (new Set(numbers).size > 1) return null;
      hits = pool.filter((j) => j.order === numbers[0] || (j.words || []).includes(numbers[0]));
      if (!hits.length) return null;
    }
    if (!others.length) return unique(hits);
    let best = 0;
    let scored = [];
    for (const job of hits) {
      const theirs = new Set((job.words || []).map(stem));
      const score = others.filter((w) => theirs.has(stem(w))).length;
      if (score > best) { best = score; scored = [job]; } else if (score === best && score > 0) scored.push(job);
    }
    if (best < others.length) return null;                             // a word that names nothing here
    return unique(scored);
  }

  function unique(jobs) {
    const seen = new Set();
    return jobs.filter((j) => (seen.has(j.key) ? false : seen.add(j.key)));
  }

  // A title's words, for `target`: "Pack #2106: 2 items for Jane Okafor" -> ['pack', '#2106', ...].
  function titleWords(text) {
    return words(text).split(' ').filter((w) => w && !FILLER.has(w));
  }

  return { read, words, stem, titleWords, STEPS, GEORGE };
});
