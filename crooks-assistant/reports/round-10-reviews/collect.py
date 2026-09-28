#!/usr/bin/env python3
"""Collect every part's review, split new findings from round-9 rulings, and read each label."""
import json,glob,pathlib,re,collections,sys
SP='/tmp/claude-0/-root/06067772-65be-458f-a3da-55db70f93db7/scratchpad/rev54'
NEW='81c78948cdb518dba344990617fb77b8a00bc228'
plan=json.load(open('parts/plan.json')); want=[p['name'] for p in plan]
res={}
for n in want:
    g=sorted(glob.glob(f'{SP}/{n}/attempt-1/dispatch.1/results/*.json'))
    if g: res[n]=json.load(open(g[-1]))
def label(t):
    t=(t or '').lstrip()
    for k in ('BLOCKS','FOLLOW-UP','REPAIRED','STILL PRESENT','CANNOT TELL'):
        if t.upper().startswith(k): return k
    return 'UNLABELLED'
newf=[]; rulings=[]
for n in want:
    d=res.get(n)
    if not d: continue
    assert d['candidate_sha']==NEW, (n,d['candidate_sha'])
    for f in d.get('findings',[]):
        rec=dict(part=n,fid=f['finding_id'],material=f.get('material'),
                 label=label(f['finding']),text=f['finding'],
                 evid=f.get('evidence_ref',''),repair=f.get('required_repair',''))
        (rulings if f['finding_id'].startswith('R9-') else newf).append(rec)
print(f"parts with a review : {len(res)} of {len(want)}")
miss=[n for n in want if n not in res]
if miss: print("MISSING           :",' '.join(miss))
print(f"verdicts           : {dict(collections.Counter(d['verdict'] for d in res.values()))}")
print()
mn=[f for f in newf if f['material']]
print(f"NEW findings: {len(newf)} total, {len(mn)} material")
print(f"  labels: {dict(collections.Counter(f['label'] for f in mn))}")
print(f"ROUND-9 rulings returned: {len(rulings)}")
print(f"  labels: {dict(collections.Counter(f['label'] for f in rulings))}")
pathlib.Path('collected.json').write_text(json.dumps(dict(new=newf,rulings=rulings),indent=1))
print()
print("=== MATERIAL NEW FINDINGS, by part ===")
for n in want:
    fs=[f for f in mn if f['part']==n]
    if not fs: continue
    b=sum(1 for f in fs if f['label']=='BLOCKS')
    print(f"\n-- {n}  ({len(fs)} material, {b} BLOCKS)  verdict={res[n]['verdict']}")
    for f in fs:
        print(f"   [{f['label']:12s}] {f['fid']}")
        print("      "+re.sub(r'\s+',' ',f['text'])[:260])
