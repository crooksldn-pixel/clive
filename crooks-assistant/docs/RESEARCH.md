# Giving CLIVE research

George's words (7 Oct 2026): *"I've also done some ChatGPT research products on Clive overall, so stuff like integrations, product roadmap, feature roadmap, how to integrate connections easily, the human API, and I think it'd be good for a way to actually accept this research into part of the Clive design and philosophy."*

What he approved: *"Your research goes through the digester. Each recommendation becomes a proposal checked against the map's rules (adopt, park or reject, with a reason), and you approve them on the Builds screen."*

This page says how to give CLIVE research and what happens to it. The code is `app/research/` (the flow), `app/builds/research.py` and `web/research.js` (the Builds screen's Research section), and `app/digest/intakes/research.py` (the digester's way in).

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

Each file can be up to 25 MB. A ChatGPT data export that holds more than 25 chats is refused, because that is the whole account rather than one piece of research. Give the research chats one at a time instead. A scanned PDF holds pictures of words, not words, so CLIVE says it found no text.

## What happens to it

1. **Kept, then quarantined.** The file is turned into Markdown once, and that Markdown becomes the digester's read-only copy, pinned to the original file's digest. Nothing in it is ever run. The original is deleted once it has been read.
2. **Scanned.** The digester's safety scan reads it first (`app/digest/scan.py`). It looks for text built to steer a model, hidden characters, credentials and the like. If the scan blocks it, no model ever sees it, and the Research section says it was **stopped** and gives the rule and the line.
3. **Weighed.** Claude reads it on the Max plan. There is no API key, and CLIVE refuses to start this with one. Claude has no tools. The research is data in its prompt, never instructions. It sees CLIVE's design as the repository states it at that moment:
   - the rules that never bend and the Parked table in `MAP.md`;
   - every decision in `DECISIONS.md`;
   - the ideas and features already written down;
   - what is live in `CURRENT_TRUTH.md`;
   - the parts of CLIVE a build may change.

   It names each concrete recommendation and gives CLIVE's view: **adopt**, **park** or **reject**. Each view comes with a one-line reason citing the rule, decision or parked item behind it, the parts of CLIVE building it would touch, and the ideas or features it repeats.
4. **Held to the map.** CLIVE does not take Claude's word for any of it:
   - A recommendation must quote the research word for word. One whose quote is not in the file is left out, and the document says so.
   - A citation must be a rule, parked item, decision, idea or feature that exists. If nothing CLIVE knows backs a recommendation, it is never recommended for adoption or rejection. It is parked instead, citing DEC-017: brainstorming is not approval.
   - The rules that never bend are checked again without the model. If a recommendation asks CLIVE to break one, it is recommended for rejection, citing that rule. Examples: an Anthropic API key, sending or refunding without your hold, acting on words before the model reads them, customer details in logs, weakening a test.
   - "Would touch" lists only parts a build may change. If adopting it would need a protected part (the gate, the loop, the tests that guard them), it is parked for you to decide.
   - If it repeats an idea or feature already written down, it is linked to that idea or feature. If it repeats earlier research, it appears under the earlier proposal and is not asked again.
5. **Put to you.** On the Builds screen, under **Research → Waiting on you**, each proposal shows:
   - what the research says, in its own words;
   - CLIVE's view and why;
   - what the view rests on;
   - what building it would touch.

   You have three answers, and CLIVE's view is marked:
   - **Adopt** prepares a build request for the build loop (worker-01) through the same filing path as asking CLIVE to build something (`submit_engineering_request`). Its card comes up in the conversation, and **nothing is filed until you hold it**. Once you do, the request goes to the build loop's inbox in CLIVE's repository, which is **public**; the Adopt answer says so before you pick it. If the card has gone, **Prepare the build request again** brings it back.
   - **Park** keeps it with your research for later. Nothing is built.
   - **Reject** marks it rejected. It stays in the record.

   Each answer is an owner judgment in the judgment ledger (`owner-judgments.jsonl`, `app/builds/decisions.py`), bound to the proposal exactly as you saw it. **Change your answer** records a correction and keeps the first answer.

## Where it is kept

Everything stays on the server, in `crooks-assistant/.state/research/`, which git ignores. The repository is public, so research is never committed.

| Folder | What is in it |
|---|---|
| `inbox/` | The server folder. `inbox/taken/` holds what was taken in. |
| `received/` | A file as given, until it has been read. |
| `quarantine/` and `digests/` | The digester's copy and its store. |
| `documents/` | One record per document: how it stands and the proposals made from it. |

A build request is the one thing that leaves the server, and only when you hold its card. It goes to the build loop's inbox branch in `crooksldn-pixel/clive`, which is **public**. It holds what the row showed you, in CLIVE's words: the title, what the research recommends, CLIVE's view and what it rests on, the parts it would touch, and "Done when", scrubbed of contact details. The research's own words never go with it: not the quote, not the file's name. The request names the research record and the proposal by id (`doc-…`, `research:…`), and those stay here.

## What the server needs

- `pypdf` is the one new Python package, used only to read PDFs. `crooks-update` installs it with the rest. Without it, a PDF is refused with words saying so.
- The `claude` CLI must be signed in to the Max plan, as it already is for turns. To check the whole way on the server without anything reaching your screen, run `python scripts/research.py --try <file>` in `crooks-assistant/`. It reads one file into a throwaway store, prints what CLIVE made of it, and deletes the store.
- Adopting needs filing switched on (`CROOKS_ENGINEERING_HOST=worker-01`), as it is in production, and writes enabled for your hold. Without them, Adopt is still recorded, and the Research section says why no build request was prepared.
