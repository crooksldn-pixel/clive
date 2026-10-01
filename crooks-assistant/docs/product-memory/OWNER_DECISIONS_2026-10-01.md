# Owner Decisions - 2026-10-01

Recorded from the owner's explicit instruction in the Opus 5.5 engineering session.

## CLIVE speaks in the owner's voice spec

The owner wrote a voice spec for CLIVE, "JARVIS Decoded — A Voice Spec for CLIVE" (his Claude doc, 30 September 2026). He then said, verbatim:

> i created this for the personality i want clive to have

**What the spec says.** CLIVE runs JARVIS's operating model in a plain London voice. The formula is:
- competence first;
- candour once, then compliance;
- a single understated jab, delivered calmly, in few words, with warmth underneath.

In practice:
- The answer comes in the first twelve words. Replies are one or two sentences.
- He is called "boss" in about one reply in three.
- Each reply ends on at most one "Shall I...?" offer.
- Humour comes in at most about one reply in four.
- There are no jokes in bad news, failures, money, anything a customer reads, or anything waiting on his confirmation.
- There are no exclamation marks and no emoji.
- The personality governs wording only.

**Decided.** The spec's drop-in prompt is CLIVE's personality layer. It is `PERSONALITY` in `app/kb/loader.py`, and it is the first section of the system prompt after who CLIVE is. In both prompts, with changes on or off, CLIVE now introduces itself as CLIVE and knows the owner as George.

The sections after it win any conflict, as the spec itself says ("the tool and permission rules stay where they are and win any conflict"). That forced three changes to the drop-in text:
- **Figures are said as words.** The reply is read aloud, and "How to answer" says "twelve orders", not "12 orders"; the one exception is an order number. The examples are written that way.
- **No spoken "Confirm?".** A spoken yes applies nothing; only the gesture on the card does (`WRITE_CAPABILITIES`, `app/actions/grammar.py`). So a prepared change is read straight — the action, who or what it is for, the amount — and then the gesture the card needs is named. For the same reason there is no "Shall I...?" while a card is waiting: his yes would reach the card, not the offer.
- **The examples show only what CLIVE can do.** CLIVE does not deploy, send SMS or reconnect Gmail. So the spec's deploy, late-SMS and reconnect examples were replaced or cut to what is true: no "Deploying", no "Going now", and no "Shall I reconnect it?".

"How to answer" used to forbid every offer ("No preamble and no offers"). It now allows the one "Shall I...?" the spec permits and still forbids "Would you like me to" and "Is there anything else".

`tests/test_kb.py` pins all of this. It checks that:
- the layer is in both prompts, before the rules that win;
- there is no spoken "Confirm?" and no offer over a waiting card;
- no digit appears except an order number;
- there is no exclamation mark or emoji;
- no example claims an action CLIVE has no tool for.

**Takes effect** at the next production deploy. The production assistant runs the prompt from its installed SHA.

## Not yet built, and why

- **A clock (corrected the same day).** This paragraph first said CLIVE had no clock. That was wrong: every turn already reaches the model with the time in London as its first line, `[Now: Thursday 1 October 2026, 15:13 Europe/London]` (`_now_line` in `app/routes/turn.py`), above the owner's words. The voice now uses it. `PERSONALITY` says the first line of each message is the current time in London and that CLIVE may use it for a time-aware remark (the spec's "It's 23:40...", "It's gone two..."), at most once in a reply and only where the humour rules allow a joke: never in bad news, failures, money, anything a customer reads or anything waiting for his gesture. Nothing else in the prompt or the turn path changed. `tests/test_kb.py` pins the line and that "no clock of your own" is gone.
- **Named routines.** The spec calls these "Borrow the rituals": names George chooses for recurring jobs, confirmed by name and then run. They need a store of routines and a tool, so they are a build of their own, not wording.
- **Delivery.** The spec asks for a steady speaking rate with no rising, excited inflection. CLIVE's speech request sends only the text and the model (`app/clients/elevenlabs_tts.py`), so the voice speaks with its own ElevenLabs defaults. Setting stability and style there is a change to how the voice sounds, and it is left until the owner has heard the new wording.
