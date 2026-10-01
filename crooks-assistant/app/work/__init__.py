"""The work list: what the team should be doing today, who has it, and who did what.

Three kinds of work, in one list (store.py, found.py):
  found     what CLIVE sees needs doing, read live: orders not yet fulfilled, emails and Instagram
            messages waiting for a reply. Nobody has to write these down; once someone claims one
            it is kept, with their name on it.
  assigned  a job the owner hands out: "restock the shelves", "stock count the hoodies", "upload
            today's Vinted sales", to someone or to whoever is free.
  routine   a job that comes back: "tidy the desks" every day, "stock count" every Monday. Each
            day's copy is made the first time that day's list is read.

Every job is claimed, then done (packed, counted, replied, or finished with a note), and every
step is kept in the record (record.jsonl) with who and when, never a message or a key. So the
owner can ask "who packed 1234?", "who counted the tees?", "what did Mia do today?". Changes to the
shop or the inbox are made through CLIVE's cards as always; the actions ledger records who
confirmed each one, and a claimed job is closed by the change it was for.

CLIVE's own records only: nothing here sends a message or touches the shop.
"""
