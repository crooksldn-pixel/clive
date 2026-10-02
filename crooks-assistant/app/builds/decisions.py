"""George's decisions on builds: the question a stopped build puts to him, and his answer kept.

George's words (2 Oct 2026): "my decision on them could be laid out a lot easier, such as the
judgement ledger the reviewer keeps saying is the best piece of work in the entire repo". Two
stops are his to decide, by the loop's own words: a build the review still finds problems with
after every repair round ("the owner decides how to proceed"), and a build at the owner gate ("an
owner decision is required"). Each is put to him as one question with two or three answers, each
saying what happens next, and one marked as recommended with why, by a fixed rule from the build's
own record (`card`).

His answer is an owner judgment in the Judgment Ledger (app/actions/judgment.py,
judgment_ledger.py; the contract in docs/product-memory/JUDGMENT_LEDGER_CONTRACT.md), not a new
store: a `JudgmentRecord` validated at construction, appended through `JudgmentLedger.append`
(one effective judgment per proposal, a change of mind a correction that keeps the first answer
byte for byte), and written as one JSON line in exactly the form the kernel's own reader takes
(app/orchestrator/lifecycle.py `judgment_to_dict`, `load_judgment_ledger`). The file is read whole
and re-validated before every append, so a ledger that would not have been accepted line by line is
never appended to. It sits beside the objectives, 0600 in their 0700 folder.

The proposal judged is the stop exactly as the loop published it and as the card put it to him:
the request, its digest, revision and attempt, the loop's words, the candidate, and the answers
offered with the one recommended. Its fingerprint is that payload's canonical digest, so an answer
binds to what he saw; when the build moves on, the question is a new proposal. Nothing here lifts
the loop's gate or files anything: the answer is recorded and read back (`read_back`, and on each
request in engineering_status) for the Director and the loop. Binding it to the kernel's own gate
proposal needs the loop to publish that proposal; see the build report of 3 Oct 2026.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.actions.judgment import (
    JudgmentRecord,
    JudgmentValidationError,
    OwnerDecision,
    OwnerProvenance,
    ReasonCode,
    proposal_fingerprint,
)
from app.actions.judgment_chain import chain_anchor, chain_ledger
from app.actions.judgment_ledger import JudgmentLedger, JudgmentLedgerError
from app.builds import plain

LEDGER_NAME = "owner-judgments.jsonl"
SOURCE = "clive:builds-screen"
ACTION_PREFIX = "build-decision:"
REVIEW_LIMIT, OWNER_GATE = "review_limit", "owner_gate"


@dataclass(frozen=True, slots=True)
class Answer:
    key: str
    label: str
    then: str                     # what happens next, in his words
    decision: OwnerDecision
    reason: ReasonCode


ANSWERS: dict[str, tuple[Answer, ...]] = {
    REVIEW_LIMIT: (
        Answer("retry", "Try again", "The Director files a fresh try that starts from the reviewer's open findings.",
               OwnerDecision.APPROVED, ReasonCode.ACCEPTED_AS_PROPOSED),
        Answer("later", "Leave it for now", "Nothing changes. It stays stopped and off your list until you pick it up.",
               OwnerDecision.DEFERRED, ReasonCode.NOT_NOW),
        Answer("drop", "Drop it", "The Director stops trying. It stays in the history.",
               OwnerDecision.DECLINED, ReasonCode.OTHER_BOUNDED),
    ),
    OWNER_GATE: (
        Answer("allow", "Allow the change", "The Director files it again with that change allowed, and the builder goes on.",
               OwnerDecision.APPROVED, ReasonCode.ACCEPTED_AS_PROPOSED),
        Answer("keep", "Keep things as they are", "It stays stopped, and the Director looks for a way that leaves them as they are.",
               OwnerDecision.DECLINED, ReasonCode.RISK_TOO_HIGH),
        Answer("later", "Decide later", "Nothing changes. It stays stopped and off your list until you pick it up.",
               OwnerDecision.DEFERRED, ReasonCode.NOT_NOW),
    ),
}

# What his answer leaves the build saying on the screen.
AFTER = {"retry": "Waiting for the Director to try again", "drop": "Dropped by you", "later": "Left for now",
         "allow": "Waiting for the Director to file it again", "keep": "Kept as it is"}


class DecisionError(Exception):
    """An answer that cannot be recorded, said in words for the owner."""


class StaleQuestion(DecisionError):
    """The build moved on since the question was drawn: nothing was recorded."""


# ------------------------------------------------------------------ the question


def _ids(ids: list[str]) -> str:
    return ids[0] if len(ids) == 1 else f"{', '.join(ids[:-1])} and {ids[-1]}"


def _attempt_id(item: dict[str, Any]) -> str | None:
    attempts = item.get("attempts")
    last = attempts[-1] if isinstance(attempts, list) and attempts and isinstance(attempts[-1], dict) else {}
    value = last.get("attempt_id")
    return value if isinstance(value, str) and value.strip() else None


def _revision(item: dict[str, Any]) -> int | None:
    value = item.get("revision")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


def _green(item: dict[str, Any]) -> bool:
    gate = item.get("github_acceptance")
    return isinstance(gate, dict) and gate.get("state") == "green"


def _question(kind: str, why: dict[str, Any], item: dict[str, Any]) -> tuple[str, str]:
    """(question, the builder's own words when they are the context)."""
    if kind == REVIEW_LIMIT:
        ids = why.get("findings") or ["its findings"]
        return f"The reviewer still has {_ids(ids)} open after every repair round. What should happen to it?", ""
    report = str(item.get("blocker") or item.get("stage_reason") or "")
    asks_test = bool(plain._ASKS_TEST_CHANGE.search(report))
    if asks_test:
        return "To do what you asked, the builder must change an existing test. Do you allow it?", ""
    return "The builder can't go on without your say. Do you allow what it asks?", \
        plain.first_sentence(report.split("required: ", 1)[-1])


# The loop's own owner-gate reports name what the owner asked for when the conflict is with it.
_OWNER_ASKED = re.compile(r"owner asked for|owner's .{0,40}design|O\d-\d+ requires", re.I)


def _recommend(kind: str, why: dict[str, Any], item: dict[str, Any], tries: int, stops: int) -> tuple[str, str]:
    """(the recommended answer, why in a line), by a fixed rule from the build's own record."""
    if kind == REVIEW_LIMIT:
        ids = why.get("findings") or []
        if _green(item):
            one = len(ids) == 1
            return "retry", (f"GitHub's tests pass on it; only {_ids(ids) if ids else 'the review'} "
                             f"stand{'s' if one else ''} between it and the trunk.")
        if stops >= 3:
            return "later", (f"It has stopped {plain.number_word(stops)} times this way, and filing it again "
                             "unchanged fails the same way.")
        return "retry", "A fresh try starts from the reviewer's findings, so it has something new to go on."
    report = str(item.get("blocker") or item.get("stage_reason") or "")
    if _OWNER_ASKED.search(report):
        return "allow", "The test holds the old behaviour you asked to change, and changing exactly that is yours to allow."
    return "keep", "Nothing in the builder's report says the change is one you asked for."


def card(item: dict[str, Any], why: dict[str, Any], *, tries: int = 1, stops: int = 1) -> dict[str, Any] | None:
    """The decision a stopped request puts to George, or None when it is not his to decide."""
    kind = why.get("kind")
    if kind not in ANSWERS or why.get("who") != plain.YOU:
        return None
    rid = str(item.get("request_id") or "")
    question, context = _question(kind, why, item)
    recommended, because = _recommend(kind, why, item, tries, stops)
    answers = ANSWERS[kind]
    revision, attempt = _revision(item), _attempt_id(item)
    payload = {
        "kind": kind,
        "request_id": rid,
        "request_sha256": str(item.get("request_sha256") or ""),
        "task_id": str(item.get("task_id") or rid),
        "revision": revision,
        "attempt_id": attempt,
        "stage": str(item.get("stage") or ""),
        "loop_words": str(item.get("blocker") or item.get("stage_reason") or ""),
        "candidate_sha": str(item.get("candidate_sha") or ""),
        "question": question,
        "answers": [a.key for a in answers],
        "recommended": recommended,
    }
    fingerprint = proposal_fingerprint(payload)
    return {
        "kind": kind,
        "request_id": rid,
        "question": question,
        "context": context,
        "answers": [{"key": a.key, "label": a.label, "then": a.then, "recommended": a.key == recommended}
                    for a in answers],
        "recommended": recommended,
        "because": because,
        # The digest is in the id too: a question put again in other words is another proposal, never
        # a second fingerprint under one id (which the ledger refuses as a mutated proposal).
        "proposal_id": f"build:{rid}:r{revision or 0}:{kind}:{fingerprint[:16]}",
        "fingerprint": fingerprint,
        "task_id": payload["task_id"],
        "revision": revision,
        "attempt_id": attempt,
    }


def answer_of(record: JudgmentRecord) -> Answer | None:
    """Which answer a judgment on a build is, from its decision and reason code."""
    parts = record.proposal_id.split(":")
    kind = parts[3] if len(parts) > 3 and parts[0] == "build" else ""
    return next((a for a in ANSWERS.get(kind, ()) if a.decision == record.decision and a.reason == record.reason_code), None)


def request_of(record: JudgmentRecord) -> str:
    return record.action_id[len(ACTION_PREFIX):] if record.action_id.startswith(ACTION_PREFIX) else ""


def chosen(record: JudgmentRecord | None) -> dict[str, Any] | None:
    """What the screen says of a recorded answer."""
    answer = answer_of(record) if record is not None else None
    if record is None or answer is None:
        return None
    return {"key": answer.key, "label": answer.label, "then": answer.then, "after": AFTER.get(answer.key, ""),
            "decision": record.decision.value, "decided_at": record.decided_at.astimezone(UTC).isoformat(timespec="seconds"),
            "judgment_id": record.judgment_id}


# ------------------------------------------------------------------ the ledger


class OwnerLedger:
    """The owner's judgments on builds: one JSON line each, append-only, read whole and re-validated
    by the kernel's own reader before anything is added."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def ledger(self) -> JudgmentLedger:
        """Every judgment recorded, validated as the kernel validates them. A ledger that cannot be
        read, or would not be accepted whole, raises DecisionError: nothing is ever appended to it."""
        from app.orchestrator.lifecycle import LifecycleError, load_judgment_ledger

        if not self.path.exists():
            return JudgmentLedger()
        try:
            ledger, _digest = load_judgment_ledger(self.path)
        except LifecycleError as exc:
            raise DecisionError(f"The decisions record could not be read, so nothing was recorded: {exc}") from None
        return ledger

    def record(self, judgment: JudgmentRecord) -> None:
        """Append one judgment: accepted by the ledger as it stands, then written and flushed."""
        from app.orchestrator.lifecycle import judgment_to_dict

        with self._lock:
            try:
                self.ledger().append(judgment)
            except (JudgmentLedgerError, JudgmentValidationError) as exc:
                raise DecisionError(f"That answer could not be recorded: {exc}") from None
            line = json.dumps(judgment_to_dict(judgment), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            folder = self.path.parent
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            try:
                dfd = os.open(folder, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
            except OSError:
                pass   # the line itself is flushed; the folder's own flush is best effort here

    def effective(self) -> dict[str, JudgmentRecord]:
        """The effective judgment for each proposal judged, by proposal id."""
        return {r.proposal_id: r for r in self.ledger().effective_judgments()}

    def read_back(self) -> dict[str, Any]:
        """Every judgment in the kernel's own line form, with the request it is about, the answer
        in words, whether it is the effective one, and the chain's head for tamper evidence."""
        from app.orchestrator.lifecycle import judgment_to_dict

        ledger = self.ledger()
        effective = {r.judgment_id for r in ledger.effective_judgments()}
        anchor = chain_anchor(chain_ledger(ledger))
        rows = []
        for record in ledger.records:
            answer = answer_of(record)
            rows.append({**judgment_to_dict(record), "request_id": request_of(record),
                         "answer": answer.key if answer else None, "answer_words": answer.label if answer else None,
                         "effective": record.judgment_id in effective})
        return {"ledger": LEDGER_NAME, "entries": anchor.entry_count, "head_hash": anchor.head_hash, "judgments": rows}


def decide(owner_ledger: OwnerLedger, question: dict[str, Any], answer_key: str, *, principal: str, session_id: str,
           now: datetime | None = None) -> tuple[JudgmentRecord, bool]:
    """Record George's answer to a question as drawn now. (record, True) when it was added; the
    effective record and False when it is already his answer. A different answer to a question he
    already answered is a correction of that answer, which stays in the ledger as it was."""
    answer = next((a for a in ANSWERS.get(question["kind"], ()) if a.key == answer_key), None)
    if answer is None:
        raise DecisionError("That is not one of the answers to this question.")
    current = owner_ledger.effective().get(question["proposal_id"])
    if current is not None and current.proposal_fingerprint == question["fingerprint"]:
        was = answer_of(current)
        if was is not None and was.key == answer.key:
            return current, False
    try:
        record = JudgmentRecord(
            judgment_id=f"jdg_{uuid.uuid4().hex[:20]}",
            task_id=question["task_id"],
            action_id=f"{ACTION_PREFIX}{question['request_id']}",
            proposal_id=question["proposal_id"],
            proposal_fingerprint=question["fingerprint"],
            decision=answer.decision,
            reason_code=answer.reason,
            provenance=OwnerProvenance(principal_id=principal, session_id=session_id, source=SOURCE),
            decided_at=now or datetime.now(UTC),
            task_revision=question.get("revision"),
            attempt_id=question.get("attempt_id"),
            redacted_explanation=f"{answer.label}. {answer.then}",
            corrects_judgment_id=current.judgment_id if current is not None else None,
        )
    except JudgmentValidationError as exc:
        raise DecisionError(f"That answer could not be recorded: {exc}") from None
    owner_ledger.record(record)
    return record, True


_LEDGER: OwnerLedger | None = None


def ledger(root: Path | None = None) -> OwnerLedger:
    """The owner's ledger beside the objectives (or under `root`)."""
    global _LEDGER
    if root is not None:
        return OwnerLedger(Path(root) / LEDGER_NAME)
    from app.objectives.store import store

    path = store().root / LEDGER_NAME
    if _LEDGER is None or _LEDGER.path != path:
        _LEDGER = OwnerLedger(path)
    return _LEDGER
