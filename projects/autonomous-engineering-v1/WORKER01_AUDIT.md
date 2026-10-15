# clive-worker-01 read-only audit (step A1)

**Why this exists:** the planning session runs on the production host and has no route to
clive-worker-01. Several facts the plan depends on are UNKNOWN until someone looks on worker-01
itself (CURRENT_ENGINEERING_REALITY):

- the pin, the Claude CLI version and the configured concurrency;
- the reviewer selection, private-channel settings, Chromium and disk use;
- lease cancellations.

**Who runs it:** George, or a session George explicitly authorises, on clive-worker-01, as the loop's
user. It is read-only. It installs, restarts, launches and edits nothing, never prints a credential,
and sets `GIT_OPTIONAL_LOCKS=0` before its first git call (the lesson in
[audit/HOST_AUDIT_RESULTS.md](audit/HOST_AUDIT_RESULTS.md) §8).

**What it is not:** `probe-launch` and `probe-review` start real Claude sessions on the plan. They
belong to the RP1 re-pin, not to this audit.

```bash
#!/usr/bin/env bash
# clive-worker-01 read-only audit. Prints a report to stdout. Writes nothing.
set -u
export GIT_OPTIONAL_LOCKS=0 LC_ALL=C
UNIT=${UNIT:-clive-remote-engineering.service}
redact() { sed -E 's/(--[a-z-]*(file|token|key)[a-z-]*)[= ]+[^ ]+/\1 <redacted>/g; s/(Environment=[A-Za-z_]+)=.*/\1=<redacted>/'; }
echo "== when";      date -u +%FT%TZ
echo "== host";      hostname; uptime; nproc; free -h | head -2; df -h / /opt /srv /tmp 2>/dev/null | sort -u
echo "== units";     systemctl --no-pager list-units --type=service --all | grep -Ei 'clive|crooks|engineer|runner' || true
systemctl --no-pager list-timers --all | grep -Ei 'clive|crooks|engineer' || true
echo "== unit";      systemctl cat "$UNIT" 2>/dev/null | redact
systemctl show "$UNIT" -p ActiveState -p SubState -p ExecMainStartTimestamp -p NRestarts -p MemoryPeak 2>/dev/null
EXEC=$(systemctl show "$UNIT" -p ExecStart --value 2>/dev/null | redact)
echo "== flags";     echo "$EXEC" | sed -E 's/ --/\n--/g' | grep -E '^--' || true   # one flag per line, credential paths redacted
PIN_DIR=$(echo "$EXEC" | grep -oE '/[^ ]*/remote-control/[0-9a-f]{40}' | head -1)
echo "== pin";       echo "${PIN_DIR:-not found in ExecStart}"; [ -n "$PIN_DIR" ] && git -C "$PIN_DIR" log -1 --format='%H %ci %s' 2>/dev/null
WCLI=$(echo "$EXEC" | grep -oE -- '--worker-cli [^ ]+' | cut -d' ' -f2)
echo "== cli";       for c in ${WCLI:-} $(command -v claude); do echo "$c: $("$c" --version 2>/dev/null)"; done
echo "== browser";   command -v chromium chromium-browser google-chrome 2>/dev/null; ls -d /root/.cache/ms-playwright/* /home/*/.cache/ms-playwright/* 2>/dev/null
echo "== tools";     node --version 2>/dev/null; python3 --version; git --version; command -v unshare bwrap 2>/dev/null
for flag in store runtime-root workspace-root; do
  d=$(echo "$EXEC" | grep -oE -- "--$flag [^ ]+" | cut -d' ' -f2); [ -z "$d" ] && continue
  echo "== $flag $d"; du -sh "$d" 2>/dev/null; find "$d" -maxdepth 1 -mindepth 1 | wc -l
done
RT=$(echo "$EXEC" | grep -oE -- '--runtime-root [^ ]+' | cut -d' ' -f2)
if [ -n "$RT" ]; then
  echo "== lease cancellations"; grep -l 'lease expired' "$RT"/attempts/*.json 2>/dev/null | wc -l
  echo "== stop reports";        ls "$RT"/stops 2>/dev/null | wc -l
fi
echo "== rate limits (count of journal lines, last 14 days)"
journalctl -u "$UNIT" --since '-14 days' --no-pager 2>/dev/null | grep -ciE 'rate.?limit|hit your (session|weekly) limit' || true
echo "== re-pin script (checksum only)"; for f in /root/root-repin.sh /usr/local/sbin/root-repin.sh; do [ -f "$f" ] && sha256sum "$f"; done
echo "== tailnet self"; tailscale status --self=true --peers=false 2>/dev/null | awk '{print $2, $3, $4}'
```

## What to record afterwards (in CURRENT_ENGINEERING_REALITY.md)

**Each value with its source line from the output:**

| Fact | Effect on the plan |
|---|---|
| Pin SHA and date | Decides whether DEC-068 and DEC-076 are in force |
| `--max-concurrent` | Today's value. RP1 sets 2, an engineering setting under DEC-079 ruling 4 |
| `--reviewer` | — |
| `--default-repair-rounds` | — |
| `--no-land` | — |
| `--no-builder-skills` | — |
| `--sandbox-browsers` | — |
| `--private-listen` | Present or absent only (needed for the private URL at D2) |
| Worker CLI version | Skills work only on 2.1.285 or 2.1.293 |
| Chromium present | — |
| Disk used by workspaces and runtime | Decides whether the cleanup verb (NEXT) is needed |
| Count of lease-expiry cancellations | Decides whether the lease-ordering fix (NEXT) is needed |
| Count of rate-limit lines | Sizes PR 5b's plan-limit pause, and the RP1 residual risk |
| Peak memory | — |

**Public-repository rule:** this repository is public, so some values are recorded as present or
absent only, never their value:

- `--private-listen`;
- `--private-allow-node`;
- the tailnet line;
- any path that names a credential.

**Then re-classify** the UNKNOWN rows for worker-01 as ACTIVE, GAP or PROVEN, citing this output.
