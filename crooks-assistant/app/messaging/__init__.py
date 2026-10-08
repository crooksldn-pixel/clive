"""Messaging: how CLIVE talks to the people CROOKS works with, whatever app they are on.

Why it exists: the owner's "human API" — CLIVE knows who does what (the manufacturer, the freight
forwarder, the team) and messages them to get evidence and work done. Messaging is how that
starts. The core here is channel-neutral; each channel is an adapter (adapter.py) and WeCom is
the first (wecom.py). WhatsApp and Instagram plug in the same way.

What it promises:
- One private store of threads and messages (store.py: 0700 folder, 0600 files, 90 days kept).
- Inbound arrives only at one public, signature-checked address per channel (app/routes/hooks.py).
- Chinese is shown in English, labelled machine translation, with the original kept beside it;
  a translation that failed says so and keeps the original (translate.py).
- Nothing leaves without the owner's hold on its card, and nothing is called sent unless the
  channel's API confirmed it with a message id (app/tools/messaging_tools.py).
- No message text, name or contact id in a log line or in telemetry.
"""
