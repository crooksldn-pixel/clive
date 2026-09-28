==============================================================================================
YOUR PART: C — live voice
==============================================================================================

You are part C of 24. Your scope is EXACTLY these 12 files, at c6c640d7017a0411c13d39cecc6ce2223a79c724:
    crooks-assistant/app/routes/voice.py
    crooks-assistant/app/clients/elevenlabs.py
    crooks-assistant/config/settings.py
    crooks-assistant/web/live-voice.js
    crooks-assistant/web/audio-viz.js
    crooks-assistant/web/alpha.js
    crooks-assistant/web/alpha.css
    crooks-assistant/web/telemetry.js
    crooks-assistant/tests/test_live_voice.py
    crooks-assistant/tests/web/live-voice.test.js
    crooks-assistant/tests/test_voice_credits.py
    crooks-assistant/tests/test_scribe.py

This part owns the new live-voice path. There is a NEW owner-only route POST /voice/live which
mints an ElevenLabs SINGLE-USE REALTIME TOKEN, and the page then streams to ElevenLabs DIRECTLY from
the browser. CROOKS_LIVE_TRANSCRIPT is new, defaults to true, and is left unset in production, so
this is ON from the moment this deploys.

The ElevenLabs API key is a live production credential
(/etc/crooks-os/credentials/elevenlabs_api_key.cred, loaded by systemd). This is the highest-risk
question in the whole round:

  - Can the LONG-LIVED ElevenLabs API key ever reach the browser, a log, a timeline, a report, an
    error body or a telemetry payload? Trace app/clients/elevenlabs.py and app/routes/voice.py line
    by line. If the minted token is not genuinely single-use and short-lived, say so.
  - Who may call POST /voice/live? Prove it is owner-only from the code, not from a decorator's
    name. Is it rate-limited? An unlimited mint endpoint is a billing drain and a credential oracle
    even if each token is short-lived.
  - What does the browser send to ElevenLabs, and what comes back? Live words are the owner's speech
    — the shop's orders, customers' names. Where do they go besides the screen: telemetry, the
    timeline, a report, the model's context?
  - config/settings.py: confirm live_transcript's default and that Settings still carries
    extra="ignore" (standing fact 3 — the live .env has a now-unknown CROOKS_SCRIBE_KEYTERMS line
    and the app must still construct).
  - web/telemetry.js: does anything about live voice leave the tailnet?

Remember: label EVERY material finding BLOCKS or FOLLOW-UP, as the first word of the
`finding` field, with one sentence on why. If you cannot tell whether a defect is reachable
on production as configured tonight, say so and label it BLOCKS.
