"""The test bench: CLIVE asked by people who are not George, at scale, and the answers judged.

George, 7 October 2026 (docs/BENCH.md): bulk-test CLIVE with sentences generated for different
personas, see what it decides and which tools it uses, and rate the outcomes, so it is ready for
people who will ask things it may not know or cannot do.

How it hangs together, one module each:

    personas   who asks: files in app/bench/personas/, one per person (George can add more)
    models     the model the generator and the judge ask: his Max plan through the Agent SDK, or
               a scripted stand-in for tests and dry runs. Never an API key.
    generate   N realistic sentences per persona, of five kinds, saved as a fixed, versioned set
    isolation  the seal around a run: no network, no secrets but the Max plan's own, the read-only
               latch, and a refusal the moment anything builds a real outward client
    runner     each sentence through the real turn (POST /turn and everything after it) against the
               fake shop, the team's sentences through the team's door
    record     one JSONL line per question: the answer, the tools, the cards, what was staged
    judge      a model's scores against a versioned rubric, one line of reason per score
    report     scores by persona and criterion, the worst ten, tools never used, and what CLIVE could
               not do grouped into candidate capability gaps
    store      where all of that lives: the data directory's bench/, never the repository

What it promises:
- A run cannot reach the shop, the inbox, Instagram, Ship24, ElevenLabs, CROOKS Returns, GitHub or
  anything else outside this machine, and cannot commit a change: writes stay staged proposals.
- Every model call is billed to George's Max plan through the claude CLI, as CLIVE's own are. The
  process refuses to start with an Anthropic API key in its environment (MAP rule 5).
- Caps are explicit: questions per run, questions in flight, minutes per run, seconds per question.
- Nothing the bench writes goes into the repository.
"""

VERSION = "bench-1"
