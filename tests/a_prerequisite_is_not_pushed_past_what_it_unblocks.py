#!/usr/bin/env python3
"""A leg inserted as a prerequisite may not be pushed past its dependent.

Leg 19, 2026-08-29 (user: "its not clearing rock tunnel, its just doing
the same verm to rt12 pingponging"): the blocker rung correctly inserted
"Clear Rock Tunnel" before "Reach Lavender Town" (Route 12 is shut by the
Snorlax, and the Flute is in Lavender). Authoring the tunnel leg then
failed, and the authoring-failure push moved it two places on — PAST
Lavender — so the run went straight back to the loop the insert existed
to break. The inserts ledger records what each insert was for; a push
that would cross that leg is refused, and the caller falls through to the
ladder instead of silently undoing the insert.
"""
import subprocess, sys, tempfile, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
with tempfile.TemporaryDirectory() as d:
    os.chdir(d)
    Path("plans").mkdir(); Path("run").mkdir()
    Path("plans/outline.txt").write_text(
        "A\nB\nClear Rock Tunnel\nReach Lavender Town\nE\nF\n")
    Path("run/outline_inserts").write_text(
        "LEG=Reach Lavender Town|Clear Rock Tunnel\n")
    def push(frm, after):
        return subprocess.run([sys.executable, str(ROOT / "planner/push_leg.py"),
                               str(frm), str(after)], capture_output=True, text=True)
    r = push(3, 5)          # past Lavender (4)
    ck("a push across the dependent is refused", r.returncode != 0
       and "was inserted as what" in (r.stdout + r.stderr), r.stdout + r.stderr)
    ck("...and the outline is untouched",
       Path("plans/outline.txt").read_text().splitlines()[2] == "Clear Rock Tunnel")
    r = push(1, 2)          # an ordinary leg, nothing to do with the insert
    ck("an ordinary push still works", r.returncode == 0, r.stdout + r.stderr)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
