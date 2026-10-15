"""Read-only baseline analysis over status snapshot transitions, inbox history and trunk.

python3 -I -B analyse.py <repo> <scratchpad>
"""
import json
import re
import statistics as st
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime

repo, S = sys.argv[1], sys.argv[2]


def g(*a):
    return subprocess.check_output(["git", "-C", repo, *a], text=True)


def T(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def mins(a, b):
    return (b - a).total_seconds() / 60


def q(vals):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return "n=0"
    n = len(vals)
    p = lambda f: vals[min(n - 1, int(round(f * (n - 1))))]
    return f"n={n} median={st.median(vals):.1f} p25={p(.25):.1f} p75={p(.75):.1f} p90={p(.9):.1f} max={vals[-1]:.1f} sum={sum(vals):.1f}"


# ---- filing times from inbox histories
filed = {}
filer = {}
for ref in ("origin/clive/control/worker-01-inbox", "origin/clive/control/owner-inbox"):
    out = g("log", "--reverse", "--diff-filter=A", "--format=@@%H|%cI|%an", "--name-only", ref, "--", "requests/")
    cur = None
    for line in out.splitlines():
        if line.startswith("@@"):
            cur = line[2:].split("|")
        elif line.startswith("requests/") and line.endswith(".json"):
            rid = line[len("requests/"):-5]
            filed.setdefault(rid, T(cur[1]))
            filer.setdefault(rid, cur[2])

# ---- final status
final = {}
for ref in ("origin/clive/control/status", "origin/clive/control/worker-01-status"):
    doc = json.loads(g("show", f"{ref}:status.json"))
    for r in doc["requests"]:
        final[r["request_id"]] = dict(r, _loop=ref.split("/")[-1])

ev = {}
for f in ("st.json", "w01.json"):
    ev.update(json.load(open(f"{S}/{f}"))["events"])

# ---- trunk first-parent landing times
fp = g("log", "--first-parent", "--format=%H|%cI|%an|%cn|%s", "origin/clive/trunk").splitlines()
fp = [l.split("|", 4) for l in fp][::-1]
graph = {}
for l in g("log", "--format=%H %P", "origin/clive/trunk").splitlines():
    p = l.split()
    graph[p[0]] = p[1:]
landed = {}
for sha, at, an, cn, subj in fp:
    info = (sha, T(at), an, cn, subj)
    landed.setdefault(sha, info)
    pend = list(graph.get(sha, [])[1:])
    while pend:
        s = pend.pop()
        if s in landed:
            continue
        landed[s] = info
        pend.extend(graph.get(s, []))


def kind(info):
    sha, at, an, cn, subj = info
    if cn in ("CLIVE dispatcher", "CLIVE loop") or an.startswith("CLIVE worker") or an == "CLIVE loop":
        return "loop-pushed"
    if cn == "GitHub" and re.search(r"\(PR #\d+", subj):
        return "PR-merge"
    return "direct"


def chain(rid):
    return re.sub(r"-\d+$", "", rid)


rows = []
for rid, r in final.items():
    e = ev.get(rid, [])
    first_assigned = next((T(x["commit_at"]) for x in e if x["changed"].get("stage") == "ASSIGNED"), None)
    first_seen = T(e[0]["commit_at"]) if e else None
    terminal = None
    for x in e:
        if x["changed"].get("stage") in ("COMPLETE", "BLOCKED", "OWNER_GATE", "REFUSED"):
            terminal = (x["changed"]["stage"], T(x["commit_at"]))
            break
    # cycles
    builds, ci, reviews = [], [], []
    a = ev_ready = gh_pending = rev = None
    for x in e:
        c, t = x["changed"], T(x["commit_at"])
        stg = c.get("stage")
        if stg == "ASSIGNED":
            a = t
        if stg == "EVIDENCE_READY" or (stg == "REVIEWING" and ev_ready is None and a is not None and c.get("candidate")):
            if a:
                builds.append(mins(a, t))
            ev_ready, a = t, None
        if c.get("gh_state") == "pending":
            gh_pending = t
        if c.get("gh_state") in ("green", "red") and ev_ready:
            ci.append(mins(ev_ready, t))
            ev_ready = None
        if stg == "REVIEWING":
            rev = t
            ev_ready = None
        elif rev and (stg in ("ASSIGNED", "COMPLETE", "BLOCKED", "OWNER_GATE") or c.get("verdicts")):
            reviews.append(mins(rev, t))
            rev = None
        if stg in ("BLOCKED", "OWNER_GATE") and a:
            builds.append(mins(a, t))
            a = None
    cand = r.get("candidate_sha")
    li = landed.get(cand) if cand else None
    land_obj = r.get("landing") or {}
    rows.append(dict(
        rid=rid, chain=chain(rid), loop=r["_loop"], stage=r.get("stage") or "REFUSED",
        filed=filed.get(rid), filer=filer.get(rid), first_seen=first_seen, assigned=first_assigned,
        terminal=terminal, builds=builds, ci=ci, reviews=reviews,
        repairs=r.get("repairs") or {}, bh=r.get("build_history") or {},
        blocker=r.get("blocker") or r.get("reason") or "", blocker_class=r.get("blocker_class"),
        cand=cand, trunk=li, trunk_kind=kind(li) if li else None, loop_landing=land_obj.get("state"),
        landing_by=land_obj.get("by"), attempts=r.get("attempts") or [],
    ))

json.dump([{k: (str(v) if isinstance(v, datetime) else v) for k, v in row.items() if k not in ("trunk",)}
           | {"trunk": [row["trunk"][0][:10], str(row["trunk"][1]), row["trunk"][4][:80]] if row["trunk"] else None}
           for row in rows], open(f"{S}/rows.json", "w"), indent=1, default=str)

print("requests", len(rows), Counter(r["loop"] for r in rows))
print("stage", Counter(r["stage"] for r in rows))
print("stage by loop", Counter((r["loop"], r["stage"]) for r in rows))
print("filer", Counter(r["filer"] for r in rows))
# queue
print("\nQUEUE filed->first ASSIGNED (min):", q([mins(r["filed"], r["assigned"]) for r in rows if r["filed"] and r["assigned"]]))
print("filed->first_seen (intake) (min):", q([mins(r["filed"], r["first_seen"]) for r in rows if r["filed"] and r["first_seen"]]))
print("BUILD per attempt (ASSIGNED->candidate/blocked) (min):", q([b for r in rows for b in r["builds"]]))
print("CI per candidate (candidate->GitHub green/red) (min):", q([b for r in rows for b in r["ci"]]))
print("REVIEW per dispatch (dispatch->verdict/next) (min):", q([b for r in rows for b in r["reviews"]]))
print("REQUEST filed->terminal (min) COMPLETE:", q([mins(r["filed"], r["terminal"][1]) for r in rows if r["filed"] and r["terminal"] and r["terminal"][0] == "COMPLETE"]))
print("REQUEST filed->terminal (min) BLOCKED:", q([mins(r["filed"], r["terminal"][1]) for r in rows if r["filed"] and r["terminal"] and r["terminal"][0] == "BLOCKED"]))
print("COMPLETE filed->trunk (h):", q([mins(r["filed"], r["trunk"][1]) / 60 for r in rows if r["stage"] == "COMPLETE" and r["filed"] and r["trunk"]]))
print("COMPLETE trunk kind:", Counter(r["trunk_kind"] for r in rows if r["stage"] == "COMPLETE"))
print("COMPLETE loop landing:", Counter((r["loop_landing"], r["landing_by"]) for r in rows if r["stage"] == "COMPLETE"))
print("COMPLETE never on trunk:", [r["rid"] for r in rows if r["stage"] == "COMPLETE" and not r["trunk"]])
print("non-COMPLETE but candidate on trunk:", [(r["rid"], r["trunk"][0][:8], r["trunk_kind"]) for r in rows if r["stage"] != "COMPLETE" and r["trunk"]])
for k in ("loop-pushed", "PR-merge", "direct"):
    print(f"  COMPLETE filed->trunk via {k} (h):", q([mins(r['filed'], r['trunk'][1]) / 60 for r in rows if r['stage'] == 'COMPLETE' and r['filed'] and r['trunk'] and r['trunk_kind'] == k]))

# repair distribution
print("\nREPAIRS (review, ci) for COMPLETE:", Counter((r["repairs"].get("review"), r["repairs"].get("ci")) for r in rows if r["stage"] == "COMPLETE"))
print("REPAIRS review for all with build history:", Counter(r["repairs"].get("review") for r in rows if r["repairs"]))
print("attempts per request COMPLETE:", q([len(r["attempts"]) for r in rows if r["stage"] == "COMPLETE"]))
print("revision kinds (all):", Counter(rv["kind"] for r in rows for rv in r["bh"].get("revisions", [])))
print("refused (sandbox check failed) attempts total:", sum(rv.get("refused", 0) for r in rows for rv in r["bh"].get("revisions", [])),
      "transient:", sum(rv.get("transient", 0) for r in rows for rv in r["bh"].get("revisions", [])))

# chains
ch = defaultdict(list)
for r in rows:
    ch[r["chain"]].append(r)
print("\nCHAINS", len(ch))
done = {c: rs for c, rs in ch.items() if any(x["stage"] == "COMPLETE" for x in rs)}
print("chains with a COMPLETE:", len(done), "| chains never COMPLETE:", len(ch) - len(done))
print("requests per chain:", Counter(len(rs) for rs in ch.values()))
et = []
for c, rs in sorted(ch.items()):
    rs.sort(key=lambda x: x["filed"] or x["first_seen"])
    first = rs[0]["filed"]
    comp = [x for x in rs if x["stage"] == "COMPLETE"]
    tr = [x for x in rs if x["trunk"]]
    end = min((x["trunk"][1] for x in tr), default=None)
    et.append((c, len(rs), first, comp[0]["rid"] if comp else None, end, tr[0]["trunk_kind"] if tr else None))
    print(f"  {c[:42]:42} n={len(rs)} first={first:%m-%d %H:%M} complete={'Y' if comp else '-'} trunk={(end.strftime('%m-%d %H:%M') if end else '-'):11} h={((end-first).total_seconds()/3600 if end else float('nan')):7.2f} via={tr[0]['trunk_kind'] if tr else '-'}"
          f" {(tr[0]['trunk'][4][:60] if tr else '')}")
print("CHAIN ETAB first filing -> first trunk landing (h), chains landed:", q([(e[4] - e[2]).total_seconds() / 3600 for e in et if e[4]]))
