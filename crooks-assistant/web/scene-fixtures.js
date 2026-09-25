/* Fixture scenes for web/scenes-gallery.html, and the few lines that draw them there.
 *
 * Every payload here has the shape app/scenes/payload.py produces for a validated scene, and
 * every value in it is invented: no customer, order or campaign here is real. The page is not
 * linked from the app and the app never loads this file; the gallery exists so the new look
 * can be seen on a phone before it is wired in. tests/web/scenes.test.js renders each case.
 */
(function (root, factory) {
  const api = factory();
  root.CliveSceneFixtures = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined' && typeof document !== 'undefined') api.whenReady(() => api.drawGallery(document));
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  const CHECKED_AT = '2026-09-24T17:00:00+00:00';

  function source(evidence, label, summary, found, checked) {
    return {
      evidence, label, summary, found,
      found_text: found ? `${found.toLocaleString('en-GB')} found` : 'nothing found',
      checked: checked || 'just now', checked_at: CHECKED_AT,
    };
  }

  function value(evidence, record, field, kind, label, text) {
    return { evidence, record, field, kind, label, text, pii: false };
  }

  const WAITING = [
    ['Amara Okafor', '1 hour ago', '2', 'Yes'],
    ['Tom Reid', '3 hours ago', '1', 'Yes'],
    ['Priya Shah', '5 hours ago', '3', 'Yes'],
    ['Jonah Wells', 'today at 11am', '1', 'No'],
    ['Elsie Moran', 'today at 9:15am', '1', 'No'],
    ['Callum Fry', 'yesterday at 4:30pm', '2', 'No'],
    ['Ruth Adeyemi', 'yesterday at 10:05am', '1', 'No'],
    ['Leo Marsh', 'Monday at 2pm', '1', 'No'],
  ];

  const CASES = [
    {
      id: 'customers-reply-2026-09-24',
      title: 'Any customers who need a reply? — 24 September',
      note: 'One Answer and its drill-down, where five cards and forty rows were drawn before. Tap the answer to see what was checked.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: 'Nobody is waiting on a reply: all 7 customers who emailed have been answered.',
          justification: 'The owner asked whether any customer needs a reply.',
        },
        elements: [],
        drilldown: {
          id: 'drilldown',
          sources: [
            source('ev-orders', 'Recent orders', 'Recent orders by days, limit', 8),
            source('ev-threads', 'Inbox', 'Inbox by days', 7),
            source('ev-customers', 'Who has emailed', 'Who has emailed by set_id, days', 25),
          ],
        },
      },
    },
    {
      id: 'nothing-needs-you',
      title: 'Anything need me?',
      note: 'Nothing needs you: one line. What was checked opens only on request.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: 'Nothing needs you right now.',
          justification: 'No customer is waiting and no order is overdue.',
        },
        elements: [],
        drilldown: {
          id: 'drilldown',
          sources: [
            source('ev-mail', 'Who has emailed', 'Who has emailed', 5),
            source('ev-overdue', 'Matching records', 'Matching records', 0),
          ],
        },
      },
    },
    {
      id: 'ads-connector',
      title: 'How did the ads do this week?',
      note: 'A connector with no screen of its own: its fields describe themselves, so the scene is an Answer, a Finding and a Trend.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: 'Advertising cost £840.50 this week at a return on spend of 2.5×.',
          justification: 'The owner asked how the advertising did.',
        },
        elements: [
          {
            id: 'e1', type: 'finding', justification: 'The weakest is barely paying for itself.',
            significance: 'RISK', text: 'Autumn denim returned only 1.4× on its spend.',
            values: [
              value('ads-1', 'r1', 'name', 'text', 'Campaign', 'Autumn denim'),
              value('ads-1', 'r1', 'roas', 'ratio', 'Return on ad spend', '1.4×'),
            ],
            sources: [source('ads-1', 'Ad campaigns', 'Ad campaigns by period', 2)],
          },
          {
            id: 'e2', type: 'trend', justification: "Where the week's spend went.",
            label: 'Daily spend', values: [90, 110, 150, 130, 120, 115, 125.5],
            latest: '£125.50', from: 'Friday', to: 'today',
          },
        ],
        drilldown: null,
      },
    },
    {
      id: 'collection-over-limit',
      title: 'Who is waiting on us?',
      note: 'A Collection over its row limit: eight rows of twenty-five, and "show all" for the rest.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: '3 customers are waiting on a reply.',
          justification: 'The owner asked who is waiting.',
        },
        elements: [
          {
            id: 'e1', type: 'finding', justification: 'They need a reply.',
            significance: 'ACTION_REQUIRED', text: '3 customers have been waiting since this morning.',
            values: [value('ev-mail', null, 'needs_reply', 'count', 'Waiting on a reply', '3')],
            sources: [source('ev-mail', 'Who has emailed', 'Who has emailed by set_id, days', 25)],
          },
          {
            id: 'e2', type: 'collection', justification: 'Who is waiting.',
            caption: 'Who has emailed', evidence: 'ev-mail',
            columns: [
              { field: 'customer_name', label: 'Customer', numeric: false },
              { field: 'latest_inbound_at', label: 'Their last email', numeric: false },
              { field: 'threads', label: 'Threads', numeric: true },
              { field: 'needs_reply', label: 'Waiting on us', numeric: false },
            ],
            rows: WAITING.map((cells, n) => ({ record: `r${n + 1}`, cells })),
            limit: 8, total: 25,
          },
        ],
        drilldown: null,
      },
    },
    {
      id: 'proposal',
      title: 'Has order 1042 gone out?',
      note: 'A Proposal: the button asks for the action to be reviewed and does nothing else.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: '#1042 has not shipped after 4 days.',
          justification: 'The owner asked whether the order has gone out.',
        },
        elements: [
          {
            id: 'e1', type: 'entity', justification: 'The order asked about.',
            caption: 'Order', record: 'r1',
            fields: [
              value('ev-order', 'r1', 'order_number', 'text', 'Order', '#1042'),
              value('ev-order', 'r1', 'placed_at', 'datetime', 'Placed', 'Monday at 10:12am'),
              value('ev-order', 'r1', 'fulfillment', 'status', 'Fulfilment', 'Unfulfilled'),
              value('ev-order', 'r1', 'total', 'money', 'Total', '£86.00'),
              value('ev-order', 'r1', 'customer_name', 'person', 'Customer', 'Amara Okafor'),
            ],
          },
          {
            id: 'e2', type: 'proposal', justification: 'Tell the customer when it ships.',
            action: 'act-2107', text: 'An action is ready for you to review.',
          },
        ],
        drilldown: null,
      },
    },
    {
      id: 'question',
      title: 'Anything from Hannah?',
      note: 'A Question CLIVE needs answered before it goes on; each option only says which was chosen.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: 'Hannah Price has written 3 times about a return.',
          justification: 'The owner asked about this customer.',
        },
        elements: [
          {
            id: 'e1', type: 'timeline', justification: 'When she wrote.',
            caption: 'Email thread',
            rows: [
              { record: 'r1', at: 'Monday at 9:40am', at_iso: '2026-09-21T08:40:00+00:00', label: 'Return request' },
              { record: 'r2', at: 'yesterday at 4:05pm', at_iso: '2026-09-23T15:05:00+00:00', label: 'Following up on my return' },
              { record: 'r3', at: 'today at 8:30am', at_iso: '2026-09-24T07:30:00+00:00', label: 'Still waiting on my refund' },
            ],
          },
          {
            id: 'e2', type: 'question', justification: 'Needs the owner.',
            text: 'Shall I draft a reply?', options: ['Yes, draft it', 'Not now'],
          },
        ],
        drilldown: null,
      },
    },
    {
      id: 'sales-week',
      title: 'How is the week going?',
      note: 'A Measure with its period, and a Comparison that states the difference.',
      payload: {
        answer: {
          id: 'answer', type: 'answer',
          text: 'Sales are ahead of last week.',
          justification: 'The owner asked how the week is going.',
        },
        elements: [
          {
            id: 'e1', type: 'measure', justification: 'Orders this week.',
            label: 'Orders', value: '40', unit: null, period: 'last 7 days', pii: false,
          },
          {
            id: 'e2', type: 'comparison', justification: 'This week against last.',
            label: 'Sales',
            current: value('ev-sales', null, 'revenue', 'money', 'Sales', '£3,100.00'),
            previous: value('ev-sales', null, 'previous_revenue', 'money', 'Sales before', '£2,800.00'),
            direction: 'up', difference: 'Up £300.00 (11%)',
          },
        ],
        drilldown: null,
      },
    },
  ];

  // ------------------------------------------------------------------ the gallery page

  function whenReady(fn) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fn);
    else fn();
  }

  function drawGallery(page) {
    const host = page.getElementById('gallery');
    const scenes = typeof window !== 'undefined' ? window.CliveScenes : null;
    if (!host || !scenes) return;
    for (const item of CASES) {
      const section = page.createElement('section');
      section.className = 'gallery-case';
      section.id = item.id;
      const title = page.createElement('h2');
      title.className = 'gallery-title';
      title.textContent = item.title;
      const note = page.createElement('p');
      note.className = 'gallery-note';
      note.textContent = item.note;
      const stage = page.createElement('div');
      stage.className = 'gallery-stage';
      // What a control asked for, said on the page, since nothing here acts on it.
      const heard = page.createElement('p');
      heard.className = 'gallery-event';
      heard.setAttribute('aria-live', 'polite');
      for (const type of ['scene-proposal', 'scene-answer', 'scene-drilldown']) {
        stage.addEventListener(type, (event) => {
          heard.textContent = `${type} dispatched: ${JSON.stringify(event.detail)}`;
        });
      }
      section.appendChild(title);
      section.appendChild(note);
      section.appendChild(stage);
      section.appendChild(heard);
      host.appendChild(section);
      scenes.renderScene(item.payload, stage);
    }
  }

  return { CASES, whenReady, drawGallery };
});
