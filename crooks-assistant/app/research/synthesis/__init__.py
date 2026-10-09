"""CLIVE learns from research instead of piling it up (DEC-078).

George's words (9 Oct 2026): "CLIVE should not accumulate research. CLIVE should learn from research."
Every recommendation from every document becomes evidence for an idea; each idea gets four separate
answers (is the direction right, is it in CLIVE already, when, is the work approved), and George sees
the ideas, not 115 separate recommendations. His decisions, ideas, features and rules are never
edited by any of it; his answers stay in the owner judgment ledger; filing a build stays the existing
card and his hold; research stays on the server (DEC-070).

    words.py        every enum and the words George is shown for it
    store.py        <research dir>/synthesis/: generations, ideas, the append-only history
    quotes.py       find_quote: where a quote sits in the research, in the research's own words
    ask.py          how each step asks the model: research only as data, a time limit, counted
    extract.py      1-2. every recommendation in a document, no cap, each pinned to its words
    match.py        3. which idea each recommendation belongs to
    consolidate.py  4. ideas that are the same proposition become one
    judge.py        5. the four answers, enforced in code
    summary.py      6. what the research says CLIVE should become, and the counts
    ideas.py        the idea record: made, hashed, fingerprinted
    answers.py      his answers to ideas, in the owner judgment ledger
    migrate.py      the old screen's proposals, linked to their ideas
    run.py          a full run (resumable), one new document into the live generation, apply, export

How to give CLIVE research, and how a synthesis is run and applied: docs/RESEARCH.md.
"""
