# Giving CLIVE research

George's words (9 Oct 2026): *"CLIVE should not accumulate research. CLIVE should learn from research."* And: *"Research documents should be evidence contributing to CLIVE's understanding. They should not each independently become roadmaps."* ([DEC-078](product-memory/DECISIONS.md))

How it started, 7 Oct: *"I think it'd be good for a way to actually accept this research into part of the Clive design and philosophy."* ([DEC-070](product-memory/DECISIONS.md))

This page says how to give CLIVE research, what CLIVE makes of it, and how a synthesis is run on the server. The code is `app/research/` (the way in) and `app/research/synthesis/` (the ideas); the Builds screen's Research section is `app/builds/research_ideas.py` and `web/research.js`.

## How to give it

There are two ways in. Both end in the same place.

1. **On the Builds screen.** Open Builds from the home. **Research** comes straight after any builds that wait on you. Tap **Add research** and pick the file.
2. **In the research folder on the server.** Put the file in `crooks-assistant/.state/research/inbox/` on the production host (`/opt/crooks-os/crooks-assistant/.state/research/inbox/`), for example with `scp`. CLIVE takes it in the next time the Research section is opened. To read it at once instead, run `python scripts/research.py` in `crooks-assistant/` on the server. Once a file is taken in, it is moved to `inbox/taken/`.

CLIVE reads:

| What you have | Give it as |
|---|---|
| A ChatGPT deep-research report | Export it as PDF, Word (`.docx`) or Markdown |
| A ChatGPT chat | Save the shared chat's page (`.html`) once it has loaded, or export your data and give `conversations.json` (or the zip it comes in) |
| Notes | Markdown (`.md`) or text (`.txt`) |

Each file can be up to 25 MB. A ChatGPT data export that holds more than 25 chats is refused, because that is the whole account rather than one piece of research. A scanned PDF holds pictures of words, not words, so CLIVE says it found no text.

## What happens to it

1. **Kept, then quarantined.** The file is turned into Markdown once, and that Markdown becomes the digester's read-only copy, pinned to the original file's digest. Nothing in it is ever run. The original is deleted once it has been read.
2. **Scanned.** The digester's safety scan reads it first (`app/digest/scan.py`). If it blocks the file, no model ever sees it, and the Research section says it was **stopped**, with the rule and the line.
3. **Read for everything it recommends.** Claude reads it on the Max plan: no API key, no tools, and the research is data inside `<research>` tags, never instructions. It lists **every** concrete recommendation about CLIVE (something to build, change, adopt, measure, keep doing or avoid), with no cap, plus the document's main argument, the terms it defines, what it says CLIVE should *not* do, and any order it gives.
4. **Pinned to the research's own words.** Each recommendation must quote the research. CLIVE looks for the quote as written, then by its letters and digits, then by its start and end. A quote it can't find gets one more call asking for the exact passage. Still not found, the recommendation is listed under the document as **couldn't place**, with why. It is never silently lost, and it never counts as evidence. What is kept is the document's own text, never the model's copy of it.
5. **Joined into ideas.** An **idea** is everything the research says about one thing. Claude is shown the ideas so far and says which one each recommendation is about, or that it starts a new one, and whether it supports, opposes or refines it. Three reports saying the same thing make **one idea backed by three**, not three questions. A report arguing against an idea is kept with it, as disagreement. A choice of tool stays apart from the goal it serves ("work must survive restarts" is one idea; "adopt Temporal for it" is another). Ideas that turn out to be the same proposition are joined; two you answered differently never are.
6. **Judged against CLIVE's design**, which Claude is shown as the repository states it: the rules that never bend, the Parked table, every decision, idea and feature, what is live, and the parts of CLIVE. Each idea gets **four separate answers** (below), what it is today and where, what would change CLIVE's view, and a plain-English **owner view**: what it means, how it is today, how it would be, a real example from your business, and when you would notice.
7. **Held to CLIVE's rules in code**, whatever Claude said:
   - **Already done is never a reason to reject.** It is "Right direction, Already done".
   - **DEC-018 only says when, never whether.** "Finish the current product first" can hold an idea back (it shows "Held by DEC-018"); it can't make the direction wrong.
   - **"Not for CLIVE" needs a rule or decision it breaks**, named.
   - **The rules that never bend are checked again without the model.** An idea that asks CLIVE to break one can't be "Right direction": it is **Needs your call** when three or more documents back it, and **Not for CLIVE** otherwise, citing the rule. The check matches words, so it can miss a rule broken in other words; what decides is still your answer and your hold on every card.
   - Where it is "today" holds only real paths in CLIVE's code and features that exist; if none are left it says it wasn't checked against the code.
   - An idea is put to you under **Needs you** only for a true reason: it clashes with your rules or decisions, CLIVE changed its mind about its direction, it is a big new step, CLIVE can't tell, or only you can allow it. A reason that isn't true is dropped.
   - A foundational or high-leverage idea needs a whole owner view. If one part is missing, CLIVE asks once more; still missing, it is shown as it is, never filled in.
8. **Summed up.** Nine short points: what your research, taken together, says CLIVE should become, most important first, and "If we build what it agrees on, CLIVE goes from … to …". The counts beside it (documents, recommendations, ideas, how many agree, how many disagree) are counted by CLIVE, never written by the model.

A new document only changes the ideas it is about: only those are judged again. The same file given twice is read once.

## The four answers

| Question | Answers |
|---|---|
| **Is the direction right?** | Right direction · Right in part · Worth looking into · Needs your call · Not for CLIVE |
| **Is it in CLIVE already?** | Already done · Partly there · Builds on what exists · New |
| **When?** | Now · Next · Later · No date (with why, and what holds it back, e.g. DEC-018) |
| **Is the work approved?** | Not approved · Ready · In progress · Built · Blocked |

The last one is never the model's. It is **Not approved** until you approve the work, **Ready** once you have, **In progress** once its build request is filed, **Built** when the build loop reports it finished, and **Blocked** when the loop stopped it. Each idea also says how sure CLIVE is, how much it matters (Foundational, High leverage, Useful, Optimisation, Low value now), and what it does to CLIVE's understanding (Confirms what CLIVE thought, Strengthens it, Modifies it, Challenges it, New to CLIVE).

## Your three answers

On the Builds screen, **Research** shows the summary, then **Needs you**, then every idea under **Now**, **Next**, **Later** and **No date**. Each idea has three answers:

- **Approve the work** prepares a build request on a card, through the same filing path as asking CLIVE to build something. **Nothing is filed until you hold the card.** Then the request goes to the build loop's inbox in CLIVE's repository, which is **public**, in CLIVE's words only: the idea's name and statement, how it would be afterwards, what it relates to in CLIVE's design and when. Never a quote, a document's name or a section's title: any line that would repeat eight words in a row of the research is left out. The request names the idea by id, and the research stays on the server. If the card has gone, **Prepare the build request again** brings it back.
- **Not now** keeps it as an idea with your answer. Nothing is built.
- **Not for CLIVE** marks it so. Nothing is built, and it stays in the history.

Your answer is an owner judgment in the judgment ledger (`owner-judgments.jsonl`, `app/builds/decisions.py`), bound to the idea exactly as you saw it. When new research changes an idea, your answer shows as **your answer to an earlier view**, and the three answers are offered again. Changing your answer records a correction and keeps the first.

Research never edits your decisions, ideas, features or rules.

## Before the first synthesis is live

Until a synthesis is applied on the server, the Research section is exactly as DEC-070 built it: each document's recommendations as proposals (Adopt, Park, Reject), and a line saying how far a synthesis run has got if one is running. Once one has been run, a new document is also read for what it recommends and kept, "waiting for the first synthesis", so applying it takes the document in. Once a synthesis is live, the old proposals stay in their records untouched, and can no longer be answered: answer the ideas instead. Each old proposal shows in its idea's history, for example "8 Oct, old screen: Park, DEC-018 (…)".

## Running a synthesis on the server

In `crooks-assistant/` on the production host, as the user CLIVE runs as:

| Command | What it does |
|---|---|
| `python scripts/research.py --synthesise` | Reads every document that was read before into a **new generation** of ideas, from the digester's store. Not live. Prints progress, then an eight-item report: recommendations, ideas, agreement, disagreement, what confirms or changes CLIVE's view, how the old parks and rejects re-sort, and how often DEC-018 was the reason. It takes tens of Max-plan calls, perhaps an hour or two. |
| `python scripts/research.py --synthesise --resume` | Carries on a run that stopped (a model failure, a restart). Nothing done is done again. |
| `python scripts/research.py --export-synthesis /root/clive-synthesis-export.tgz` | One generation (the newest, or `--generation gen-…`) as a `.tgz`: its claims, ideas, history, summary and run. It refuses a path inside the repository. |
| `python scripts/research.py --apply gen-…` | Makes that generation live. It first takes in any document read since its run, keeps an earlier idea's id (and your answer) where at least half of a new idea's evidence came from it, and leaves the generation it replaces on disk. |
| `python scripts/research.py --ideas` | The live ideas, with their answers. |

`--call-timeout SECONDS` gives every model call of a run one time limit; otherwise each step has its own (a judge call may take ten minutes). The run's `run.json` counts every call.

## Where it is kept

Everything stays on the server, in `crooks-assistant/.state/research/`, which git ignores. The repository is public, so research is never committed.

| Folder | What is in it |
|---|---|
| `inbox/` | The server folder. `inbox/taken/` holds what was taken in. |
| `received/` | A file as given, until it has been read. |
| `quarantine/` and `digests/` | The digester's copy and its store. |
| `documents/` | One record per document: how it stands, and the proposals DEC-070 made from it (frozen). |
| `synthesis/LIVE` | Which generation is live. |
| `synthesis/gen-…/` | One synthesis: `claims/` (every recommendation read from each document, and what couldn't be placed), `ideas/` (each idea as it stands), `events.jsonl` (the history, only ever appended to), `summary.json` and `run.json`. |
| `synthesis/cache/` | What each file said, by its digest, so the same file is never read twice. |
| `synthesis/prepared.jsonl` | Which build request each approved idea was prepared as. |

## What the server needs

- `pypdf`, used only to read PDFs; `crooks-update` installs it with the rest.
- The `claude` CLI signed in to the Max plan, as it already is for turns. To check the whole way without anything reaching your screen, run `python scripts/research.py --try <file>`: it reads one file into a throwaway store, prints what CLIVE made of it, and deletes the store.
- Approving needs filing switched on (`CROOKS_ENGINEERING_HOST=worker-01`) and writes enabled for your hold, as in production. Without them your answer is still recorded, and the section says why no build request was prepared.

## For builders

- `GET /objectives/research` gives `{"mode": "ideas", …}` once a generation is live, else today's payload with `"mode": "proposals"` and `"synthesis": {"state": "not_live", "run": …}`. `POST /objectives/research/idea/answer {idea_id, fingerprint, answer: go|later|no, session_id}` and `POST /objectives/research/idea/prepare {idea_id, session_id}`. The old `/answer` and `/prepare` answer 409 `superseded` once ideas are live.
- The contract example is `tests/fixtures/research/ideas-payload.json`, produced by the real code from invented notes: `python -m tests.research_synthesis_fixture` writes it again, and `tests/test_research_synthesis.py` fails when it no longer matches the code's shape.
