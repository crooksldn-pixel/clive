#!/usr/bin/env python3
"""Prove a keep-both merge actually kept both — and tell the three cases apart.

Phase 5's lesson in one file: resolving web/ui.js by "keeping both sides" left a function
unclosed, because git had kept the shared closing brace OUTSIDE the conflict region. The file
looked right and the SyntaxError surfaced two thousand lines later. Reading a resolution is
not checking it.

Phase 6 added the second half of the lesson: **git reporting NO CONFLICT is not the same as
git having done the right thing.** Merging four workstreams here produced no conflict at all
and silently dropped three test functions. All three turned out to be fine — two renames and
one deliberate inversion — but finding that out took a base check per function, and a tool
that cannot do that check hands you a list you have to litigate by hand every time.

So this classifies rather than just flags:

  LOST          in one side, not in the base, not in the merge.   <- a real loss. Fail.
  DELETED       in the base, kept by one side, removed by the other. Git honoured the
                deletion, which is correct three-way semantics — but whether it is right for
                the PRODUCT is a judgement, so it is reported and must be justified. Fail
                unless --accept-deletions names it.
  ADDED/KEPT    present in the merge. Fine.

Usage:
  check_union.py <merged file> --base <sha> [--accept <name> ...] <sha>:<path> ...
"""
import argparse, ast, subprocess, sys
from pathlib import Path


def defs(source: str) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
    return out


def at(spec: str) -> str:
    return subprocess.run(["git", "show", spec], capture_output=True, text=True, check=True).stdout


p = argparse.ArgumentParser()
p.add_argument("merged")
p.add_argument("--base", required=True, help="merge-base sha (path taken from the first side)")
p.add_argument("--accept", action="append", default=[], help="a deletion you have justified")
p.add_argument("sides", nargs="+", help="sha:path for each merged side")
args = p.parse_args()

merged_src = Path(args.merged).read_text(encoding="utf-8")
if "<<<<<<<" in merged_src or ">>>>>>>" in merged_src:
    sys.exit("FAIL: conflict markers still in the merged file")
try:
    merged = defs(merged_src)
except SyntaxError as exc:
    sys.exit(f"FAIL: merged file does not parse: {exc}")
print(f"merged {args.merged}: {len(merged)} definitions")

path = args.sides[0].split(":", 1)[1]
try:
    base = defs(at(f"{args.base}:{path}"))
except subprocess.CalledProcessError:
    base = set()
print(f"base {args.base[:10]}: {len(base)} definitions")

sides = {}
for spec in args.sides:
    sides[spec] = defs(at(spec))
    print(f"  {spec.split(':')[0][:10]}: {len(sides[spec])} definitions")

lost, deleted = [], []
for spec, names in sides.items():
    for name in sorted(names - merged):
        (deleted if name in base else lost).append((spec.split(":")[0][:10], name))

bad = False
if lost:
    bad = True
    print(f"\nFAIL — {len(lost)} definition(s) LOST (new on one side, gone from the merge):")
    for who, name in lost:
        print(f"    {name}   (added by {who})")

unjustified = [(w, n) for w, n in deleted if n not in args.accept]
if unjustified:
    bad = True
    print(f"\nFAIL — {len(unjustified)} definition(s) DELETED by the other side. Git was right to")
    print("       honour the deletion; whether it is right for the product is YOUR call.")
    print("       Check each: is there a rename that replaces it, or a deliberate inversion?")
    print("       Then pass --accept <name> to record that you looked.")
    for who, name in unjustified:
        print(f"    {name}   (kept by {who}, removed by the other side)")

for who, name in deleted:
    if name in args.accept:
        print(f"\n  accepted deletion: {name}")

if not bad:
    print("\nOK: nothing lost, every deletion justified, and the merged file parses.")
sys.exit(1 if bad else 0)
