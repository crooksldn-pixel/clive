"""Read-only: walk every snapshot of a status branch and print per-request transitions.

Usage: python3 -B walk_status.py <repo> <ref> [out_json_in_scratchpad]
Reads blobs with git cat-file --batch; writes only the optional JSON into the scratchpad.
"""
import json
import subprocess
import sys

repo, ref = sys.argv[1], sys.argv[2]
out = sys.argv[3] if len(sys.argv) > 3 else None

log = subprocess.check_output(
    ["git", "-C", repo, "log", "--reverse", "--format=%H %cI", ref], text=True
).split("\n")
commits = [l.split() for l in log if l.strip()]

cat = subprocess.Popen(
    ["git", "-C", repo, "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
)


def blob(sha):
    cat.stdin.write(f"{sha}:status.json\n".encode())
    cat.stdin.flush()
    header = cat.stdout.readline().split()
    if len(header) < 3 or header[1] == b"missing":
        return None
    size = int(header[2])
    data = cat.stdout.read(size)
    cat.stdout.read(1)
    return data


def key(r):
    ga = r.get("github_acceptance") or {}
    rv = r.get("review") or {}
    land = r.get("landing") or {}
    return {
        "stage": r.get("stage") or ("REFUSED" if r.get("outcome") == "refused" else None),
        "stage_reason": (r.get("stage_reason") or r.get("reason") or "")[:90],
        "attempts": len(r.get("attempts") or ()),
        "revision": r.get("revision"),
        "gh_state": ga.get("state"),
        "gh_sha": (ga.get("sha") or "")[:10],
        "review_dispatched": rv.get("dispatched_at"),
        "verdicts": tuple((v.get("at"), v.get("verdict")) for v in rv.get("verdicts") or ()),
        "landing": land.get("state"),
        "candidate": (r.get("candidate_sha") or "")[:10],
    }


prev = {}
events = {}
waiting_seen = {}
for sha, at in commits:
    data = blob(sha)
    if data is None:
        continue
    try:
        doc = json.loads(data)
    except json.JSONDecodeError:
        continue
    for w in doc.get("waiting_requests") or ():
        rid = w.get("request_id") if isinstance(w, dict) else str(w)
        waiting_seen.setdefault(rid, at)
    for r in doc.get("requests") or ():
        rid = r.get("request_id")
        k = key(r)
        if prev.get(rid) != k:
            old = prev.get(rid) or {}
            changed = {f: v for f, v in k.items() if old.get(f) != v}
            events.setdefault(rid, []).append({"commit_at": at, "changed": changed})
            prev[rid] = k

cat.stdin.close()
cat.wait()
result = {"ref": ref, "snapshots": len(commits), "events": events, "waiting_first_seen": waiting_seen}
if out:
    with open(out, "w") as fh:
        json.dump(result, fh, indent=1, default=list)
print(ref, "snapshots", len(commits), "requests", len(events), "waiting", len(waiting_seen))
