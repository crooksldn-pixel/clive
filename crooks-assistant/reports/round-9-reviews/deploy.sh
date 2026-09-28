#!/bin/bash
# Round 9 deploy: 6a29e310 -> c6c640d7, code and unit in ONE operation.
# Adapted from round-8/deploy.sh. NEVER run unless no review part returned a BLOCKS finding.
#
# Any failure at any step runs the ERR trap, which restores the 6a29e310 checkout and the saved
# unit, reloads systemd and restarts the service, then exits 1.
set -euo pipefail

REPO=/opt/crooks-os
APP=$REPO/crooks-assistant
PY=$APP/.venv/bin/python
R=/root/clive-activation/round-9
NEW=c6c640d7017a0411c13d39cecc6ce2223a79c724
OLD=6a29e31013b0b9e543d90434e14ed65deea1ce30
UNIT=/etc/systemd/system/crooks-assistant.service
PORT=8000
TSHOST=crooks-os-prod-1.taildfb357.ts.net
PHONE_WAIT=${PHONE_WAIT:-600}          # 4.5: up to 10 minutes for George's phone

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

rollback() {
  local rc=$? line=${1:-?}
  set +e
  echo
  echo "################################################################"
  echo "### FAILED (exit $rc at line $line) -> ROLLING BACK to $OLD"
  echo "################################################################"
  systemctl stop crooks-assistant.service 2>&1 | tail -2
  log "restoring checkout $OLD"
  git -C "$REPO" checkout --detach "$OLD" 2>&1 | tail -2
  log "restoring unit from $R/installed.service"
  cp "$R/installed.service" "$UNIT"
  systemctl daemon-reload
  log "starting service"
  systemctl start crooks-assistant.service 2>&1 | tail -2
  for i in $(seq 1 45); do
    curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
    sleep 2
  done
  echo "--- after rollback ---"
  echo "HEAD     : $(git -C "$REPO" rev-parse HEAD)"
  echo "service  : $(systemctl is-active crooks-assistant.service)"
  echo "ExecStart: $(systemctl show crooks-assistant.service -p ExecStart --value)"
  echo "args     : $(ps -o args= -p "$(systemctl show -p MainPID --value crooks-assistant.service)" 2>/dev/null)"
  echo "/health  : $(curl -fsS --max-time 15 "http://127.0.0.1:$PORT/health" 2>&1 | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("status"))' 2>&1)"
  echo "unit sha : $(sha256sum "$UNIT" | cut -d" " -f1)   (saved: $(sha256sum "$R/installed.service" | cut -d" " -f1))"
  echo "env sha  : $(sha256sum "$APP/.env" | cut -d" " -f1)"
  echo "RESULT: ROLLED_BACK"
  exit 1
}
trap 'rollback $LINENO' ERR

echo "### round 9 deploy  $OLD -> $NEW  $(date -u +%FT%TZ)"

log "STEP 0: identity of the pieces this script will install"
test -f "$R/rendered-c6c640d7.service" || { echo "rendered unit missing"; false; }
test -f "$R/installed.service"         || { echo "saved rollback unit missing"; false; }
grep -q -- '--no-proxy-headers$' "$R/rendered-c6c640d7.service" || { echo "rendered unit lacks --no-proxy-headers"; false; }
ENV_BEFORE=$(sha256sum "$APP/.env" | cut -d' ' -f1)
ENV_BASE=$(cut -d' ' -f1 < "$R/env-sha256-before.txt")
[ "$ENV_BEFORE" = "$ENV_BASE" ] || { echo ".env changed since preflight ($ENV_BEFORE != $ENV_BASE)"; false; }
INSTALLED_NOW=$(sha256sum "$UNIT" | cut -d' ' -f1)
INSTALLED_SAVED=$(cut -d' ' -f1 < "$R/installed-service-sha256.txt")
[ "$INSTALLED_NOW" = "$INSTALLED_SAVED" ] || { echo "the installed unit changed since preflight"; false; }
PARKED_BEFORE=$(stat -c '%u %a %s %Y' /etc/crooks-os/credentials-parked/github_engineering_inbox_token.cred)
GAPS_BEFORE=$(sha256sum /var/lib/crooks-assistant/objectives/gaps.json | cut -d' ' -f1)
BACKUPS_BEFORE=$(ls /var/lib/crooks-assistant/objectives/gaps.json.* 2>/dev/null | wc -l)
echo "  .env sha256 matches preflight; installed unit matches preflight"
echo "  parked credential fingerprint recorded (never opened)"
echo "  gap record sha256 $GAPS_BEFORE with $BACKUPS_BEFORE backup(s) before the deploy"
log "fetching candidate into $REPO"
git -C "$REPO" fetch origin --quiet
git -C "$REPO" cat-file -e "${NEW}^{commit}"
echo "  candidate object present"

# The journal marker every later assertion reads from. Set BEFORE the restart.
MARK=$(date -u '+%Y-%m-%d %H:%M:%S')
sleep 1
echo "  journal marker: $MARK"

log "STEP 4.1a: stop the service"
systemctl stop crooks-assistant.service
sleep 1
echo "  service now: $(systemctl is-active crooks-assistant.service || true)"

log "STEP 4.1b: checkout $NEW"
git -C "$REPO" checkout --detach "$NEW" --quiet
HEAD_NOW=$(git -C "$REPO" rev-parse HEAD)
[ "$HEAD_NOW" = "$NEW" ] || { echo "HEAD is $HEAD_NOW, not $NEW"; false; }
echo "  HEAD: $HEAD_NOW"

log "STEP 4.1c: dependencies, only if the lock changed"
if git -C "$REPO" diff --name-only "$OLD" "$NEW" -- '*pyproject.toml' '*uv.lock' '*requirements*.txt' | grep -q .; then
  echo "  lock changed -> installing"
  ( cd "$APP" && "$PY" -m pip install -q -e . )
else
  echo "  no dependency file changed between $OLD and $NEW -> nothing to install"
fi

log "STEP 4.1d: install the re-rendered unit and daemon-reload"
cp "$R/rendered-c6c640d7.service" "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
echo "  installed ExecStart: $(systemctl show crooks-assistant.service -p ExecStart --value)"

log "STEP 4.1e: restart"
systemctl start crooks-assistant.service
echo "  service now: $(systemctl is-active crooks-assistant.service)"

log "STEP 4.1f: wait for /health to answer"
UP=0
for i in $(seq 1 60); do
  if curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then UP=1; echo "  /health answered after ~$((i*2))s"; break; fi
  sleep 2
done
[ "$UP" = 1 ] || { echo "/health never answered"; false; }

log "STEP 4.2: the running uvicorn's args carry --no-proxy-headers"
MAINPID=$(systemctl show -p MainPID --value crooks-assistant.service)
ARGS=$(ps -o args= -p "$MAINPID")
echo "  pid $MAINPID args: $ARGS"
case "$ARGS" in *--no-proxy-headers*) echo "  OK";; *) echo "  MISSING --no-proxy-headers in the running process"; false;; esac

log "STEP 4.3: active, and stayed up for 30 seconds"
for i in $(seq 1 30); do
  STATE=$(systemctl is-active crooks-assistant.service || true)
  [ "$STATE" = "active" ] || { echo "  service went $STATE after ${i}s"; false; }
  sleep 1
done
PID_AFTER=$(systemctl show -p MainPID --value crooks-assistant.service)
[ "$PID_AFTER" = "$MAINPID" ] || { echo "  MainPID changed $MAINPID -> $PID_AFTER: it restarted inside the 30s window"; false; }
NRESTARTS=$(systemctl show -p NRestarts --value crooks-assistant.service)
echo "  active for 30s, same MainPID $PID_AFTER, NRestarts=$NRESTARTS"

log "STEP 4.4: /health LIMITED LIVENESS — the server's own curl is a caller the owner rule refuses"
curl -fsS --max-time 20 "http://127.0.0.1:$PORT/health" > "$R/health-after-raw.json"
"$PY" - "$R/health-after-raw.json" <<'HPY'
import json, sys
d = json.load(open(sys.argv[1]))
bad = 0
print(f"  status={d.get('status')!r} limited={d.get('limited')!r} "
      f"build={str(d.get('build'))[:32]!r} uptime_s={d.get('uptime_s')!r}")
if d.get("limited") is not True:
    print("  limited is not true — this curl is not the owner and should get liveness only"); bad = 1
for f in ("status", "build", "uptime_s"):
    if d.get(f) is None:
        print(f"  the limited document is missing {f}"); bad = 1
checks = d.get("checks") or {}
pi = checks.get("proxy_identity")
if pi is None:
    print("  checks.proxy_identity ABSENT"); bad = 1
else:
    ok, detail = pi.get("ok"), str(pi.get("detail") or "")
    print(f"  proxy_identity ok={ok!r} detail={detail!r}")
    want = "uvicorn started with --no-proxy-headers"
    if ok is not True: print("  proxy_identity.ok is not true"); bad = 1
    elif want not in detail: print(f"  detail does not contain {want!r}"); bad = 1
hk = checks.get("housekeeping")
if hk is None:
    print("  checks.housekeeping ABSENT"); bad = 1
else:
    print(f"  housekeeping   ok={hk.get('ok')!r}")
    if hk.get("ok") is not True: print("  housekeeping.ok is not true"); bad = 1
extra = sorted(set(checks) - {"proxy_identity", "housekeeping"})
if extra:
    print(f"  the limited document also carries checks {extra} — more than liveness")
sys.exit(bad)
HPY
echo "  OK"

log "STEP 4.5: GEORGE, PHONE CHECK 2 — https://$TSHOST/whoami on his phone"
echo "  He reads out the \"check\" value. Waiting up to ${PHONE_WAIT}s for a journal line"
echo "  'whoami: id=<that check> through=tailscale owner=true refusal=none'."
CHECK_ID=""
FOUND=0
for i in $(seq 1 "$PHONE_WAIT"); do
  if [ -z "$CHECK_ID" ] && [ -f "$R/phone2-check-id.txt" ]; then
    CHECK_ID=$(tr -dc 'a-f0-9' < "$R/phone2-check-id.txt" | head -c 8)
    [ -n "$CHECK_ID" ] && echo "  George's check id: $CHECK_ID"
  fi
  if [ -n "$CHECK_ID" ]; then
    if journalctl -u crooks-assistant.service --since "$MARK" --no-pager 2>/dev/null \
         | grep -F "whoami: id=$CHECK_ID " | grep -qF 'through=tailscale owner=true refusal=none'; then
      FOUND=1; echo "  FOUND after ~${i}s"; break
    fi
  fi
  sleep 1
done
[ "$FOUND" = 1 ] || { echo "  no 'whoami: id=$CHECK_ID through=tailscale owner=true refusal=none' line in ${PHONE_WAIT}s"; false; }
journalctl -u crooks-assistant.service --since "$MARK" --no-pager | grep -F 'whoami:' | tail -5 | sed 's/^/    /'

log "STEP 4.6: the host's own request through serve is this_host, not the owner"
curl -s --max-time 20 "https://$TSHOST/whoami" -o /dev/null || true
sleep 2
if journalctl -u crooks-assistant.service --since "$MARK" --no-pager | grep -qF 'through=this_host owner=false'; then
  echo "  OK: 'through=this_host owner=false' present"
else
  echo "  host's own request did NOT log through=this_host owner=false"
  journalctl -u crooks-assistant.service --since "$MARK" --no-pager | grep -F 'whoami:' | tail -5 | sed 's/^/    /'
  false
fi

log "STEP 4.7: the switches, the .env and the parked credential are exactly as found"
ENV_AFTER=$(sha256sum "$APP/.env" | cut -d' ' -f1)
[ "$ENV_AFTER" = "$ENV_BASE" ] || { echo "  .env CHANGED: $ENV_AFTER != $ENV_BASE"; false; }
echo "  .env sha256 unchanged: $ENV_AFTER"
"$PY" - <<'EPY'
import pathlib, sys
vals = {}
for raw in pathlib.Path('/opt/crooks-os/crooks-assistant/.env').read_text().splitlines():
    s = raw.strip()
    if not s or s.startswith('#') or '=' not in s: continue
    k, v = s.split('=', 1); vals[k.strip()] = v.strip().strip('"').strip("'")
want = {'CROOKS_SCREEN_SNAPSHOTS': 'false', 'CROOKS_LOCAL_OWNER': None,
        'CROOKS_WRITES_LOCAL_OWNER': 'false', 'CROOKS_ENGINEERING_HOST': None,
        'CROOKS_TAILSCALE_VERIFY': None, 'CROOKS_LIVE_TRANSCRIPT': None}
bad = 0
for k, w in want.items():
    got = vals.get(k)
    ok = (got is None) if w is None else (got == w)
    print(f"  {k:28s} = {'<unset>' if got is None else repr(got):10s} {'OK' if ok else '*** WRONG ***'}")
    bad |= 0 if ok else 1
al = vals.get('CROOKS_ALLOWED_LOGINS')
ok = bool(al and al.strip())
print(f"  {'CROOKS_ALLOWED_LOGINS':28s} = non-empty:{ok} (value not printed) {'OK' if ok else '*** EMPTY ***'}")
bad |= 0 if ok else 1
sys.exit(bad)
EPY
PARKED_AFTER=$(stat -c '%u %a %s %Y' /etc/crooks-os/credentials-parked/github_engineering_inbox_token.cred)
[ "$PARKED_AFTER" = "$PARKED_BEFORE" ] || { echo "  PARKED CREDENTIAL CHANGED: '$PARKED_AFTER' != '$PARKED_BEFORE'"; false; }
echo "  parked credential unchanged (uid mode size mtime identical; never opened or decrypted)"
NCRED=$(ls /etc/crooks-os/credentials/*.cred 2>/dev/null | wc -l)
[ "$NCRED" = 3 ] || { echo "  /etc/crooks-os/credentials/ holds $NCRED .cred files, expected 3"; false; }
echo "  /etc/crooks-os/credentials/ still holds exactly 3 .cred files"
diff <(grep 'LoadCredential' "$UNIT") <(grep 'LoadCredential' "$R/installed.service") >/dev/null \
  && echo "  installed unit's LoadCredentialEncrypted lines identical to the saved ones" \
  || { echo "  LoadCredentialEncrypted lines CHANGED"; false; }

log "STEP 4.8: the gap record kept exactly one backup"
BACKUPS_AFTER=$(ls /var/lib/crooks-assistant/objectives/gaps.json.* 2>/dev/null | wc -l)
echo "  backups before: $BACKUPS_BEFORE   after: $BACKUPS_AFTER"
[ "$BACKUPS_AFTER" -le 1 ] || { echo "  the start-up clean left $BACKUPS_AFTER backups, more than one"; false; }
echo "  gap record sha256 before: $GAPS_BEFORE"
echo "  gap record sha256 after : $(sha256sum /var/lib/crooks-assistant/objectives/gaps.json | cut -d' ' -f1)"

echo
echo "RESULT: DEPLOYED_OK  HEAD=$(git -C "$REPO" rev-parse HEAD)  unit=$(sha256sum "$UNIT" | cut -d' ' -f1)"
