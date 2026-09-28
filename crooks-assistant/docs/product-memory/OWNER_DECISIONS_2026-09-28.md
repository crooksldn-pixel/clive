# Owner Decisions - 2026-09-28

Recorded from the owner's explicit instructions in the Opus 5.5 engineering session.

## The fast lane and the speech term base are removed

The owner, verbatim:

> get rid of the fast path actions and inbuilt voice term base because sometimes even just mentioning a word means nothing gets done but look up order xyz, and the terms block means certain words such as Clive - is registered as Plaid. and many other instances, overall, they are holding it back a for lot more than helping it and this is not good.

Why: the fast lane matched words, numbers and intents in front of the model and answered some sentences with a canned recipe. A number mentioned in passing was looked up (and sometimes answered) before the model had seen what was asked, so the request itself was not done. The speech term base biased the recogniser towards the shop's catalogue words, so ordinary words were heard as product words.

Decided:

- **Every typed or spoken request is a model turn**, with the words exactly as they were said and the tools the model already has. No phrase, order number or intent match answers a sentence, and nothing is looked up before the model is asked. The word-matching router, its recipes and lanes, the order prefetch and the self-correction layer are gone (`app/fastpath/` and the families that registered with it).
- **Nothing tells the recogniser which words to expect, and nothing rewrites what it heard.** ElevenLabs Scribe is sent the audio and nothing else, the Whisper fallback is given no prompt, and the post-transcription normaliser that mapped heard words onto catalogue terms is gone. The transcript is only trimmed. `CROOKS_SCRIBE_KEYTERMS` and `CROOKS_SCRIBE_MAX_KEYTERMS` are no longer settings.

What turned "Clive" into "Plaid": the keyterm list sent to Scribe. It was built from the live catalogue (product titles, set names, colour and option values, spoken aliases), up to 99 terms per request; "Plaid" was on it and "Clive" was not, so Scribe was biased to hear the catalogue word. The Whisper fallback carried the same list in its initial prompt. The normaliser was removed too, but it was not what changed this word.

What was kept, and why:

- **Taps.** A button names what it does, so it is not the fast lane: the semantic commands and the reads a button names (the dock's landings, the order and discount forms' reads) still answer without the model. `app/recipes.py` holds those reads.
- **The spoken "yes" over a waiting card** is still recognised before the model. That is the write boundary's interlock — a spoken yes never applies a change — not a lookup.
- **Plain trimming** of the transcript.

What it costs: a simple lookup is now a model round trip, seconds rather than the tens to hundreds of milliseconds a recipe took. And "next", "go back" or "open the inbox" said out loud reach the model, which has no tool that moves the screen; the buttons do that. The owner judged that the fast lane was holding CLIVE back far more than it helped. This supersedes, for anything said or typed, the "deterministic fast paths remain" line of [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md) §2.6; taps stay deterministic.

## The app's accent is iOS blue

The accent colour moves from lilac to iOS blue, and the start-up's dots go steel (`0bdfe58c`).

## TV screens get a remote mode

The owner's TV screens get a remote mode. It is being built separately.
