"""The people CLIVE knows and works with: the team who use it, and the people it can ask.

The owner tells CLIVE who someone is in his own words ("Mia works for crooksldn in the office:
daily packing, emails, Instagram and general warehouse work"; "Henry does our graphic design,
posters and post designs, not product design; his email is ..."), and CLIVE keeps a card for
them (store.py), written through one tool, person_note, which only the owner may call.

Two kinds:
  staff     someone who uses CLIVE themselves, from their own phone, signed in with their own
            Tailscale login. Their access is a grant the owner approves with his passkey on the
            Today screen (access.py); until then it is "pending" and the door does not open.
  contact   someone CLIVE knows and can suggest for a job (a "human API"): a designer, a
            photographer, a supplier. No login and no access; CLIVE can draft a brief to them
            for the owner to send.

What staff may see and do is decided in one place (app/people/staff.py): every read but the
owner's own records, and the five writes the owner allowed without his OK (1 October 2026).
"""
