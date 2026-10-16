"""The shape of a synthesis run, in counts only, so the next run can be judged without the research.

Why this exists: [16 Oct] the first full run on the server made 403 ideas where about 40 were expected,
and finding out where they came from needed the research itself. run.json's `shape` block says it in
numbers: how the recommendations were placed, how many ideas there are, how they are backed, and how
many ideas each document started. `--status`, the eight-item report and `--export-synthesis` show it.

What it promises:
- Counts only: every value is a whole number or a document's id (doc-…, never its name), and every
  key is a fixed word. No research text and no idea's name, ever.
- Worked out from the generation's ideas and claims as they stand; run.py keeps it up to date at the
  end of each stage (and whenever it saves run.json).
- Every idea is counted once: placed claims and the counts by how central they are come from the
  active ideas only (each claim is in exactly one); "started" counts every idea a document started,
  merged ones too, by the document of its first source, as a list in the order the documents were
  read (run.json is written with its keys sorted, so a list is what keeps that order).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.research.synthesis.ideas import documents_backing
from app.research.synthesis.words import CENTRALITIES, CLAIM_KINDS, KINDS


def _bucket(n: int, edges: tuple[tuple[str, int, int | None], ...]) -> str:
    return next(key for key, low, high in edges if n >= low and (high is None or n <= high))


BACKING = (("0", 0, 0), ("1", 1, 1), ("2", 2, 2), ("3+", 3, None))
CLAIMS = (("1", 1, 1), ("2-3", 2, 3), ("4+", 4, None))


def of(ideas: dict[str, dict[str, Any]], claims: dict[str, dict[str, Any]], order: Iterable[str] = ()) -> dict[str, Any]:
    """The shape of a generation: `order` is the documents' ids in the order they were read."""
    active = [i for i in ideas.values() if i.get("status") == "active"]
    quoted = [c for doc in claims.values() for c in doc.get("claims") or []]
    unplaced = sum(len(doc.get("unplaced") or []) for doc in claims.values())
    sources = {s.get("claim_id"): s for i in active for s in i.get("sources") or []}
    centrality = {k: 0 for k in CENTRALITIES}
    for source in sources.values():
        if source.get("centrality") in centrality:
            centrality[source["centrality"]] += 1
    kinds = {k: 0 for k in CLAIM_KINDS}
    for claim in quoted:
        if claim.get("kind") in kinds:
            kinds[claim["kind"]] += 1
    by_kind = {k: 0 for k in KINDS}
    backing = {key: 0 for key, _low, _high in BACKING}
    by_claims = {key: 0 for key, _low, _high in CLAIMS}
    for idea in active:
        if idea.get("kind") in by_kind:
            by_kind[idea["kind"]] += 1
        backing[_bucket(len(documents_backing(idea)), BACKING)] += 1
        if idea.get("sources"):
            by_claims[_bucket(len(idea["sources"]), CLAIMS)] += 1
    passing = sum(1 for i in active if i.get("sources") and all(s.get("centrality") == "passing" for s in i["sources"]))
    return {
        "claims": {"total": len(quoted) + unplaced, "placed": sum(1 for c in quoted if c.get("id") in sources),
                   "unplaced": unplaced, "by_centrality": centrality, "by_kind": kinds},
        "ideas": {"active": len(active), "merged": sum(1 for i in ideas.values() if i.get("status") == "merged"),
                  "by_kind": by_kind, "by_documents": backing, "by_claims": by_claims, "only_passing": passing},
        "started": _started(ideas, list(order), claims),
    }


def _started(ideas: dict[str, dict[str, Any]], order: list[str], claims: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """How many ideas each document started: [{"doc_id", "ideas"}], in the order the documents were read."""
    counts: dict[str, int] = {d: 0 for d in [*(d for d in order if d in claims), *sorted(d for d in claims if d not in order)]}
    for idea in ideas.values():
        first = (idea.get("sources") or [{}])[0].get("doc_id")
        if first:
            counts[first] = counts.get(first, 0) + 1
    return [{"doc_id": doc_id, "ideas": n} for doc_id, n in counts.items()]


def _listed(counts: dict[str, int], order: tuple[str, ...]) -> str:
    """The counts that aren't 0, in the vocabulary's own order (run.json sorts its keys)."""
    return ", ".join(f"{k} {counts[k]}" for k in order if counts.get(k)) or "none"


def lines(shape: dict[str, Any] | None) -> list[str]:
    """The shape in a few plain lines, for --status, the report and the export."""
    if not shape:
        return []
    claims, ideas = shape["claims"], shape["ideas"]
    waiting = claims["total"] - claims["placed"] - claims["unplaced"]
    docs = ideas["by_documents"]
    by = ideas["by_claims"]
    return [
        f"Shape: {claims['total']} recommendations, {claims['placed']} placed in ideas, {claims['unplaced']} couldn't be placed"
        + (f", {waiting} not placed yet" if waiting else "")
        + f"; by how central: {_listed(claims['by_centrality'], CENTRALITIES)}; by kind: {_listed(claims['by_kind'], CLAIM_KINDS)}.",
        f"Ideas: {ideas['active']} active, {ideas['merged']} merged; by kind: {_listed(ideas['by_kind'], KINDS)}; "
        f"backed by one document {docs['1']}, two {docs['2']}, three or more {docs['3+']}"
        + (f", none {docs['0']}" if docs.get("0") else "")
        + f"; with one recommendation {by['1']}, two or three {by['2-3']}, four or more {by['4+']}; "
        f"{ideas['only_passing']} only from passing mentions.",
        "Ideas started in each document, in the order read: " + (", ".join(str(d["ideas"]) for d in shape["started"]) or "none")
        + ".",
    ]
