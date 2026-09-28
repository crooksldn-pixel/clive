#!/usr/bin/env python3
"""One scope.<PART> per part: its remit, its files, the contract of the sibling files it calls
but cannot see, and the round-9 findings it must rule on."""
import ast, json, pathlib, subprocess, textwrap
REPO='/root/clive-activation/round-10/review'; NEW='81c78948'; P='crooks-assistant/'
plan=json.load(open('parts/plan.json'))
fbp=json.load(open('parts/findings-by-part.json'))
N=len(plan)

def show(rel):
    r=subprocess.run(['git','-C','/opt/crooks-os','show',f'{NEW}:{P}{rel}'],capture_output=True)
    return r.stdout.decode('utf-8','replace') if r.returncode==0 else ''

def signatures(rel):
    """Public signatures + docstring first lines — the contract, not the body."""
    src=show(rel)
    if not src: return ''
    if rel.endswith('.py'):
        try: tree=ast.parse(src)
        except SyntaxError: return ''
        out=[]
        def emit(node,ind=''):
            for n in node.body:
                if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
                    a='async ' if isinstance(n,ast.AsyncFunctionDef) else ''
                    try: sig=ast.unparse(n.args)
                    except Exception: sig='...'
                    ret=''
                    if n.returns:
                        try: ret=' -> '+ast.unparse(n.returns)
                        except Exception: pass
                    out.append(f"{ind}{a}def {n.name}({sig}){ret}:")
                    d=ast.get_docstring(n)
                    if d: out.append(f"{ind}    \"\"\"{d.strip().splitlines()[0]}\"\"\"")
                elif isinstance(n,ast.ClassDef):
                    out.append(f"{ind}class {n.name}:")
                    d=ast.get_docstring(n)
                    if d: out.append(f"{ind}    \"\"\"{d.strip().splitlines()[0]}\"\"\"")
                    emit(n,ind+'    ')
                elif isinstance(n,ast.Assign) and ind=='':
                    for t in n.targets:
                        if isinstance(t,ast.Name) and t.id.isupper():
                            try: out.append(f"{t.id} = {ast.unparse(n.value)[:120]}")
                            except Exception: pass
        emit(tree)
        return '\n'.join(out)
    # JS: exported / top-level function and const shapes
    keep=[l.rstrip() for l in src.splitlines()
          if l.startswith(('function ','async function ','export ','const ','class ','let '))
          or l.strip().startswith(('async function','function '))]
    return '\n'.join(keep[:400])

# which sibling contracts each part needs, because the prompt requires a split half to carry
# the signatures and docstrings of what it calls in the other half
CONTRACT={
 'S1T':['app/identity.py','app/main.py','app/routes/health.py','app/local_cli.py','app/tools/gate.py',
        'app/tools/dispatch.py','app/tools/authority.py'],
 'S2T':['app/routes/turn.py','app/routes/command.py','app/recipes.py','app/tools/gmail_writes.py',
        'app/families/compose.py'],
 'S2' :['app/tools/authority.py','app/tools/dispatch.py','app/tools/gate.py','app/identity.py'],
 'S3P':['app/routes/displays.py','app/displays/store.py'],
 'S3T1':['app/routes/displays.py','app/displays/store.py','app/tools/display_tools.py'],
 'S3T2':['web/display.js','web/remote.js','app/routes/displays.py'],
 'S3' :['app/identity.py','app/tools/gate.py'],
 'S4' :['app/identity.py','app/routes/turn.py','web/app.js'],
 'S4A':['web/live-voice.js','app/routes/voice.py','app/routes/observe.py'],
 'S5' :['app/observability/report.py','scripts/launch_common.py'],
 'F'  :['app/routes/turn.py','app/tools/gmail_writes.py','app/families/compose.py'],
 'O1' :['app/routes/turn.py','app/identity.py'],
 'O2' :['app/observability/visible.py','app/observability/report.py'],
 'W1' :['web/app.js'],'W2':['web/app.js'],
}
FACTS={'S1':"""PACKET FACTS — measured on the production host tonight, at THIS candidate, by the
deploy owner, with the production venv interpreter and the real kernel tables:
  - /proc/net/tcp  parsed: 16 of 16 data rows accepted by identity._TCP_ADDRESS['net/tcp']
  - /proc/net/tcp6 parsed: 42 of 42 data rows accepted by identity._TCP_ADDRESS['net/tcp6']
  - identity.this_hosts_addresses() returned BOTH tailnet addresses (100.72.82.24 and
    fd7a:115c:a1e0::352b:5219) with an EMPTY reason string.
  - tailscaled runs from /usr/sbin/tailscaled in cgroup /system.slice/tailscaled.service; that
    binary, the cgroup and its cgroup.procs are all uid 0 with no group- or other-write.
  - The rendered production unit at this candidate still carries --no-proxy-headers, and its only
    difference from the installed 6a29e310 unit is one comment line.
These are facts about the host, not about the code. They do not settle whether the code is right.
"""}

for i,p in enumerate(plan,1):
    nm=p['name']; L=[]
    L.append(f"==============================================================================================")
    L.append(f"YOUR PART: {nm} — {p['title']}")
    L.append(f"You are part {i} of {N}. You hold only the files listed here.")
    L.append(f"==============================================================================================")
    L.append("")
    L.append("THE FILES IN YOUR PART (all paths under crooks-assistant/):")
    for path in p['paths']: L.append(f"  {path[len(P):]}")
    L.append("")
    L.append("Nothing outside this list is yours to clear. If a judgement needs a file that is not")
    L.append("listed above, say CANNOT TELL and name the file.")
    L.append("")
    if nm in FACTS: L.append(FACTS[nm]); L.append("")
    if nm in CONTRACT:
        L.append("==============================================================================================")
        L.append("THE CONTRACT OF THE SIBLING FILES YOU CALL BUT CANNOT SEE")
        L.append("Signatures and docstring first lines only, at this candidate, as unchanged context. Use them")
        L.append("to reason about calls across the split. They are NOT the bodies: you still cannot clear")
        L.append("behaviour that lives inside them.")
        L.append("==============================================================================================")
        for rel in CONTRACT[nm]:
            s=signatures(rel)
            if not s: continue
            L.append(f"\n--- {P}{rel} at {NEW} — CONTRACT ONLY ---")
            L.append(s[:14000])
        L.append("")
    fs=fbp.get(nm,[])
    if fs:
        L.append("==============================================================================================")
        L.append(f"ROUND-9 FINDINGS THIS PART MUST RULE ON — {len(fs)} of them "
                 f"({sum(1 for f in fs if f['label']=='BLOCKS')} were BLOCKS)")
        L.append("Return one REPAIRED / STILL PRESENT / CANNOT TELL ruling for each, with finding_id")
        L.append("R9-<part>-<id> exactly as given below.")
        L.append("==============================================================================================")
        for f in fs:
            L.append("")
            L.append(f"### R9-{f['part']}-{f['fid']}   round 9 called this: {f['label']}")
            L.append("FINDING: "+textwrap.fill(f['finding'],100,subsequent_indent='  '))
            L.append("EVIDENCE: "+textwrap.fill(f['evid'],100,subsequent_indent='  '))
            L.append("REPAIR ROUND 9 DEMANDED: "+textwrap.fill(f['repair'],100,subsequent_indent='  '))
        L.append("")
    pathlib.Path(f"parts/scope.{nm}").write_text("\n".join(L)+"\n")
    print(f"  scope.{nm:5s} {len(chr(10).join(L)):7d} bytes   round-9 findings: {len(fs)}")
