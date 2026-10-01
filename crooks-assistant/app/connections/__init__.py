"""Connections: the owner adds, tests and removes CLIVE's keys and sign-ins from the app.

The owner's decision of 1 October 2026: keys may be stored from the app rather than only typed at
a server prompt, and every change asks for a passkey (Face ID, a fingerprint or the device PIN)
at that moment. The pieces:

  catalog.py     what can be connected, the fields each needs, and what CLIVE does with it
  passkeys.py    the passkey check: registration, and a fresh approval for every change
  testers.py     a live test of a key before it replaces the one in use
  instagram.py   "Sign in with Instagram", the first sign-in button
  service.py     store, test, disconnect and record, with the caches each change must drop
  ledger.py      the record of every change (never a value), shown on the screen

The route is app/routes/connections.py and the screen web/connections.html. A key goes into a
form, never into the conversation: the model has no tool that reads or writes one, and nothing
here returns a value once stored.
"""
