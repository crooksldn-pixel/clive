#!/bin/bash
# Round 9, step 3: a staging copy of c6c640d7 for George's phone check 1.
# Nothing here touches production: no production data path, no credential, a separate port, a
# transient unit, and a serve handler that is added and then removed to a byte-identical status.
set -euo pipefail
R9=/root/clive-activation/round-9
NEW=c6c640d7017a0411c13d39cecc6ce2223a79c724
STAGE=$R9/stage
STATE=$R9/stage-state
PY=/opt/crooks-os/crooks-assistant/.venv/bin/python
UNIT=crooks-stage-r9
PORT=8799
TSHOST=crooks-os-prod-1.taildfb357.ts.net

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

log "3.1 staging clone at $NEW, from the REVIEW checkout (never a worktree of /opt/crooks-os)"
rm -rf "$STAGE" "$STATE"
git clone --quiet --no-hardlinks "$R9/review" "$STAGE"
git -C "$STAGE" checkout --quiet --detach "$NEW"
echo "  HEAD      : $(git -C "$STAGE" rev-parse HEAD)"
echo "  tree      : $(git -C "$STAGE" rev-parse HEAD^{tree})"
echo "  candidate : $(git -C "$R9/review" rev-parse $NEW^{tree})"
echo "  dirty     : $(git -C "$STAGE" status --porcelain | wc -l) entries"
echo "  production worktrees (must be one, /opt/crooks-os):"
git -C /opt/crooks-os worktree list | sed 's/^/    /'

log "3.2 isolated state, 0700 and empty"
mkdir -p "$STATE"/{home,secrets,objectives,logs,reports}
chmod 700 "$STATE" "$STATE"/{home,secrets,objectives,logs,reports}
ls -la "$STATE" | sed 's/^/    /'

log "3.3 stage.env — the allow-list copied across without being printed, writes OFF"
umask 077
"$PY" - "$STATE" > "$R9/stage.env" <<'EPY'
import pathlib, sys
state = sys.argv[1]
allowed = ""
for raw in pathlib.Path('/opt/crooks-os/crooks-assistant/.env').read_text().splitlines():
    s = raw.strip()
    if s.startswith('CROOKS_ALLOWED_LOGINS='):
        allowed = s.split('=', 1)[1]
print(f"CROOKS_ALLOWED_LOGINS={allowed}")          # value copied, never echoed to a terminal
print("CROOKS_WRITES_ENABLED=false")
print("CROOKS_WRITES_LOCAL_OWNER=false")
print("CROOKS_SCREEN_SNAPSHOTS=false")
print("CROOKS_TEST_SESSION_ALWAYS=false")
print(f"CROOKS_LOG_DIR={state}/logs")
print(f"CROOKS_OBJECTIVES_DIR={state}/objectives")
print(f"CROOKS_REPORTS_DIR={state}/reports")
print(f"CROOKS_PORT=8799")
EPY
chmod 600 "$R9/stage.env"
echo "  stage.env keys (values withheld):"
cut -d= -f1 "$R9/stage.env" | sed 's/^/    /'
echo "  any production data path in it? $(grep -c -E '/opt/crooks-os|/var/lib/crooks-assistant|/etc/crooks-os' "$R9/stage.env" || true) (must be 0)"
grep -q -E '/opt/crooks-os|/var/lib/crooks-assistant|/etc/crooks-os' "$R9/stage.env" && { echo "  *** a production path leaked into stage.env"; exit 1; }

log "3.4 save the serve status before anything is added"
tailscale serve status --json > "$R9/serve-before.json"
sha256sum "$R9/serve-before.json" | sed 's/^/    /'

log "3.5 transient unit $UNIT on 127.0.0.1:$PORT, --no-proxy-headers, NO credentials"
systemd-run --unit="$UNIT" --collect \
  --property=Type=exec \
  --property=WorkingDirectory="$STAGE/crooks-assistant" \
  --property=Environment=HOME="$STATE/home" \
  --property=Environment=PYTHONUNBUFFERED=1 \
  --property=Environment=PYTHONPATH="$STAGE/crooks-assistant" \
  --property=Environment=CROOKS_SECRET_DIR="$STATE/secrets" \
  --property=EnvironmentFile="$R9/stage.env" \
  "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --no-proxy-headers
sleep 2
echo "  unit state: $(systemctl is-active $UNIT.service || true)"
for i in $(seq 1 45); do
  curl -fsS --max-time 5 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && { echo "  /health answered after ~$((i*2))s"; break; }
  sleep 2
done

log "3.6 prove it is the CANDIDATE's code, and that no credential reached it"
SPID=$(systemctl show -p MainPID --value $UNIT.service)
echo "  pid        : $SPID"
echo "  cwd        : $(readlink /proc/$SPID/cwd)"
echo "  args       : $(ps -o args= -p $SPID)"
( cd "$STAGE/crooks-assistant" && PYTHONPATH="$STAGE/crooks-assistant" "$PY" -c 'import app; print("  import app ->", app.__file__)' )
echo "  CREDENTIALS_DIRECTORY in its environment? $(tr '\0' '\n' < /proc/$SPID/environ | grep -c '^CREDENTIALS_DIRECTORY=' || true) (must be 0)"
echo "  /run/credentials/$UNIT.service exists?    $([ -e /run/credentials/$UNIT.service ] && echo YES || echo no)"
echo "  files in the staging secret dir:          $(find "$STATE/secrets" -type f | wc -l) (must be 0)"
echo "  production claude credential mtime:       $(stat -c %y /root/.claude/.credentials.json 2>/dev/null || echo '(absent)')"

log "3.7 staging /health (the server's own curl — the owner rule refuses it)"
curl -fsS --max-time 20 "http://127.0.0.1:$PORT/health" > "$R9/stage-health.json"
"$PY" - "$R9/stage-health.json" <<'HPY'
import json, sys
d = json.load(open(sys.argv[1]))
print(f"    status        : {d.get('status')!r}")
print(f"    limited       : {d.get('limited')!r}")
print(f"    build         : {str(d.get('build'))[:40]!r}")
print(f"    uptime_s      : {d.get('uptime_s')!r}")
print(f"    top-level keys: {sorted(d)}")
c = d.get('checks') or {}
print(f"    checks        : {sorted(c)}")
for k in ('proxy_identity', 'housekeeping'):
    if k in c:
        print(f"    checks.{k}: {c[k]}")
HPY

log "3.8 add the serve handler for George's phone: https :8443 -> 127.0.0.1:$PORT"
tailscale serve --bg --https=8443 "http://127.0.0.1:$PORT"
tailscale serve status --json > "$R9/serve-after-add.json"
echo "  the existing :443 handler must be untouched:"
"$PY" - "$R9/serve-before.json" "$R9/serve-after-add.json" <<'SPY'
import json, sys
b = json.load(open(sys.argv[1])); a = json.load(open(sys.argv[2]))
def h443(d):
    for k, v in (d.get("Web") or {}).items():
        if k.endswith(":443"): return k, v
    return None, None
kb, vb = h443(b); ka, va = h443(a)
print(f"    :443 before {kb}: {json.dumps(vb, sort_keys=True)}")
print(f"    :443 after  {ka}: {json.dumps(va, sort_keys=True)}")
print(f"    byte-identical: {json.dumps(vb, sort_keys=True) == json.dumps(va, sort_keys=True)}")
print(f"    :8443 added   : {[k for k in (a.get('Web') or {}) if k.endswith(':8443')]}")
SPY
echo
echo "STAGING IS UP:  https://$TSHOST:8443/whoami"
echo "MARK=$(date -u '+%Y-%m-%d %H:%M:%S')" | tee "$R9/phone1-mark.txt"
