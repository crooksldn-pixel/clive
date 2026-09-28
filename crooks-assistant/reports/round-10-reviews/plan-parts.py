#!/usr/bin/env python3
"""Round 10 packet plan. Pins the security surfaces the round-9 lesson requires to travel
together, then packs everything else in the range into further parts under the 300 KB
full-file budget, so that EVERY changed path in 6a29e310..81c78948 is in at least one part."""
import subprocess, json, sys, pathlib

REPO='/opt/crooks-os'; OLD='6a29e310'; NEW='81c78948'; BUDGET=300_000
P='crooks-assistant/'
changed=set(subprocess.run(['git','-C',REPO,'diff','--name-only',OLD,NEW],
            capture_output=True,text=True).stdout.split())
size={}
for p in changed:
    r=subprocess.run(['git','-C',REPO,'show',f'{NEW}:{p}'],capture_output=True)
    size[p]=len(r.stdout) if r.returncode==0 else 0   # deleted at NEW -> 0

# ---- pinned parts: the security surfaces, together, per the prompt's grouping ----
PINNED=[
 ("S1", "the door and authority — identity, admission, the local CLI, health, and the whole tool-authority chain", [
   'app/identity.py','app/main.py','app/routes/actions.py','app/routes/health.py','app/local_cli.py',
   'app/tools/authority.py','app/tools/dispatch.py','app/tools/gate.py','app/providers/max_agent_sdk.py',
   'app/tools/registry.py']),
 ("S1T","the door's tests", [
   'tests/test_turn_authority_path.py','tests/test_health_key.py','tests/test_host_addresses.py',
   'tests/test_proxy_identity.py','tests/test_local_cli.py','tests/test_tool_boundary.py',
   'tests/test_gate.py','tests/test_registry.py','tests/test_engineering_bridge.py',
   'tests/test_engineering_bridge_bounds.py','tests/test_routes.py']),
 ("S2", "the turn and the write boundary", [
   'app/routes/turn.py','app/routes/command.py','app/recipes.py','app/tools/gmail_writes.py',
   'app/families/compose.py','app/families/order_edit.py','app/families/store_credit.py']),
 ("S2T","the turn's and the write boundary's tests", [
   'tests/test_turn_boundary.py','tests/test_tap_reads_only.py','tests/test_reply_order_binding.py',
   'tests/test_compose_provenance.py','tests/test_store_credit.py','tests/test_actions_routes.py',
   'tests/test_recipes.py','tests/test_every_turn_is_the_model.py',
   'tests/test_order_edit_picker_binding.py','tests/test_gmail_writes.py']),
 ("S3", "the screens, server side", [
   'app/routes/displays.py','app/displays/store.py','app/tools/display_tools.py','app/displays/views.py',
   'app/clients/youtube.py','app/observability/screens.py']),
 ("S3P","the screens, the pages", [
   'web/display.js','web/remote.js','web/sw.js','web/display.html','web/display.css','web/remote.css']),
 ("S3T1","the screens' server tests", [
   'tests/test_displays.py','tests/test_screens_r10.py','tests/test_screen_cookie.py',
   'tests/test_screen_paths.py','tests/test_screen_video.py']),
 ("S3T2","the screens' page tests and screen privacy", [
   'tests/test_screen_privacy.py','tests/web/display.test.js','tests/web/remote.test.js','tests/web/sw.test.js']),
 ("S4", "live voice and the words on the page", [
   'app/routes/voice.py','app/routes/observe.py','web/live-voice.js','web/telemetry.js',
   'tests/test_live_voice.py','tests/test_live_voice_owner.py','tests/test_live_transcript_telemetry.py',
   'tests/web/live-voice.test.js','tests/web/live-words-page.test.js']),
 ("S4A","the app page itself", ['web/app.js']),
 ("S5", "records, observability and shutdown", [
   'app/objectives/gaps.py','scripts/gap_clean_check.py','scripts/launch_common.py',
   'scripts/install_systemd.py','scripts/status.py','app/reads/scheduler.py','app/anticipation/engine.py',
   'tests/test_gaps.py','tests/test_gap_clean_property.py','tests/test_housekeeping_round9.py',
   'tests/test_standdown_branch.py']),
]

parts=[]; assigned=set()
for name,title,rel in PINNED:
    paths=[P+r for r in rel]
    used=sum(size.get(p,0) for p in paths if p in changed)
    parts.append(dict(name=name,title=title,paths=paths,budget=used))
    assigned |= {p for p in paths if p in changed}

# ---- everything else, packed by AREA so each part is coherent, then by budget ----
def area(r):
    if r.startswith('app/families/'):      return ('F','the families')
    if r.startswith('app/observability/'): return ('O','observability')
    if r.startswith('experience/'):        return ('X','the experience harness')
    if r.startswith('web/'):               return ('W','the remaining pages')
    if r.startswith('tests/web/'):         return ('TW','the remaining page tests')
    if r.startswith('tests/'):             return ('T','the remaining tests')
    if r.startswith('scripts/') or r.startswith('bench/'): return ('SC','the remaining scripts')
    if r.startswith('docs/') or r.endswith('.md') or r.startswith('kb/'): return ('DOC','the documents')
    if r.startswith('config/') or r.startswith('deploy/') or r.endswith('Makefile') or r.endswith('.example'):
        return ('CFG','settings, the unit template and the deploy documents')
    return ('AC','the rest of the application')
groups={}
for p in sorted(changed-assigned):
    k,t=area(p[len(P):]); groups.setdefault((k,t),[]).append(p)
for (k,t),members in sorted(groups.items()):
    members.sort(key=lambda p:-size[p])
    chunks=[]; cur=[]; used=0
    for p in members:
        if cur and used+size[p]>BUDGET: chunks.append((cur,used)); cur=[]; used=0
        cur.append(p); used+=size[p]
    if cur: chunks.append((cur,used))
    for i,(b,u) in enumerate(chunks,1):
        nm=k if len(chunks)==1 else f"{k}{i}"
        ttl=t if len(chunks)==1 else f"{t}, part {i} of {len(chunks)}"
        parts.append(dict(name=nm,title=ttl,paths=sorted(b),budget=u))
        assigned|=set(b)

# ---- zero-omission proof ----
missing=sorted(changed-assigned)
print(f"changed paths in range : {len(changed)}")
print(f"paths covered by parts : {len(assigned & changed)}")
print(f"OMITTED                : {len(missing)}")
for m in missing: print("   ***",m)
over=[p for p in parts if p['budget']>BUDGET]
print(f"parts                  : {len(parts)}")
print(f"parts over {BUDGET} budget: {len(over)}")
for p in over: print("   ***",p['name'],p['budget'])
print()
for p in parts:
    inr=sum(1 for x in p['paths'] if x in changed)
    print(f"  {p['name']:5s} {len(p['paths']):3d} paths ({inr} in range)  full-file budget {p['budget']:7d}  {p['title']}")
pathlib.Path('parts/plan.json').write_text(json.dumps(parts,indent=1))
for p in parts:
    pathlib.Path(f"parts/paths.{p['name']}").write_text("".join(x[len(P):]+"\n" for x in p['paths']))
sys.exit(1 if (missing or over) else 0)
