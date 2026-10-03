/* George's side of Today (web/today-owner.js): what "Hand it out" sends, under Node.
 *
 * The review of 3 October found the rebuilt hand-out had lost two things the old form could do:
 * a routine on one day of the week (Mondays to Sundays) and a job for a day further off than
 * tomorrow. What is held: today, tomorrow and a picked day become a job with that due date; every
 * day, weekdays and one weekday become a routine with that cadence (app/work/store.py CADENCES);
 * a stock count is a stock count; and a day missing or gone is refused in words, sending nothing.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

globalThis.window = globalThis;
require(path.join(__dirname, '..', '..', 'web', 'today-owner.js'));
const { handOutBody } = globalThis.CliveTodayOwner;

const NOW = new Date(2026, 9, 3, 9, 30);   // Sat 3 October 2026, the phone's own clock
const draft = (extra) => Object.assign({ who: '', when: 'now', count: false, day: '', weekday: 'mon' }, extra);

test('a job for today, tomorrow or a day he picks carries that day', () => {
  assert.deepEqual(handOutBody(draft(), 'Restock the tee shelf', '', NOW),
    { path: '/today/assign', body: { title: 'Restock the tee shelf', details: '', to: '', kind: 'job' }, said: 'for today' });
  assert.equal(handOutBody(draft({ when: 'tomorrow' }), 'x', '', NOW).body.due, '2026-10-04');
  const picked = handOutBody(draft({ when: 'date', day: '2026-10-16', who: 'kit' }), 'Order mailer bags', 'the big ones', NOW);
  assert.equal(picked.path, '/today/assign');
  assert.deepEqual(picked.body, { title: 'Order mailer bags', details: 'the big ones', to: 'kit', kind: 'job', due: '2026-10-16' });
  assert.equal(picked.said, 'for Fri 16 Oct');
});

test('a routine is every day, weekdays, or one day a week, Monday to Sunday', () => {
  assert.equal(handOutBody(draft({ when: 'daily' }), 'Tidy', '', NOW).body.cadence, 'daily');
  assert.equal(handOutBody(draft({ when: 'weekdays' }), 'Tidy', '', NOW).body.cadence, 'weekdays');
  for (const day of ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']) {
    const plan = handOutBody(draft({ when: 'weekly', weekday: day }), 'Wipe the packing table', '', NOW);
    assert.equal(plan.path, '/today/routine', day);
    assert.equal(plan.body.cadence, day);
  }
  assert.equal(handOutBody(draft({ when: 'weekly', weekday: 'wed' }), 'x', '', NOW).said, 'every Wed');
  assert.equal(handOutBody(draft({ when: 'weekly', weekday: 'wed', count: true }), 'Count the caps', '', NOW).body.kind, 'stock_count');
});

test('nothing is sent without what needs doing, or with a day missing or gone', () => {
  assert.deepEqual(handOutBody(draft(), '', '', NOW), { error: 'Say what needs doing first.' });
  assert.deepEqual(handOutBody(draft({ when: 'date' }), 'x', '', NOW), { error: 'Pick the day it is for.' });
  assert.deepEqual(handOutBody(draft({ when: 'date', day: '2026-10-01' }), 'x', '', NOW), { error: 'That day has gone. Pick today or later.' });
  assert.deepEqual(handOutBody(draft({ when: 'weekly', weekday: 'someday' }), 'x', '', NOW), { error: 'Pick the day of the week.' });
});
