#!/usr/bin/env python3
"""A leg inserted as a prerequisite may not be pushed past its dependent.

Leg 19, 2026-08-29 (user: "its not clearing rock tunnel, its just doing
the same verm to rt12 pingponging"): the blocker rung correctly inserted
"Clear Rock Tunnel" before "Reach Lavender Town" (Route 12 is shut by the
Snorlax, and the Flute is in Lavender). Authoring the tunnel leg then
failed, and the authoring-failure push moved it two places on — PAST
Lavender — so the run went straight back to the loop the insert existed
to break. The inserts ledger records what each insert was for; a push
that would cross that leg may not simply happen.

REFUSING IT OUTRIGHT WAS THE WRONG HALF OF THE ANSWER (2026-08-30). It threw
the model's judgement away and, exiting non-zero under `set -e`, killed the
whole chain mid-ladder rather than falling through as its comment claimed.
Leg 19 is the case: the model said "'Obtain Fresh Water' moves to after leg
25 — Fresh Water is only sold at the Celadon Department Store, which requires
reaching Celadon City first", which is right, and the leg it unblocks
("Retrieve the Gold Teeth from Celadon City") is in Celadon too. The insert
records that A comes BEFORE B; it says nothing about where B sits. So the
dependent travels with it and the order is kept — which is also what the
Rock Tunnel bug needed, since the damage there was Lavender ending up FIRST.
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
    ck("the push happens rather than killing the caller", r.returncode == 0,
       r.stdout + r.stderr)
    ck("...and says the dependent came along",
       "move together and stay in that order" in r.stdout
       and "Reach Lavender Town" in r.stdout, r.stdout)
    _o = Path("plans/outline.txt").read_text().splitlines()
    ck("...the prerequisite still comes FIRST, which was the whole bug",
       _o.index("Clear Rock Tunnel") < _o.index("Reach Lavender Town"), _o)
    ck("...both are deferred, neither is left behind",
       _o.index("Clear Rock Tunnel") > _o.index("E"), _o)
    ck("...and both are recorded as pushed",
       Path("run/outline_pushes").read_text().count("Rock Tunnel") == 1
       and Path("run/outline_pushes").read_text().count("Lavender") == 1)
    # the caller must survive a push that does NOT happen, whatever the reason
    r2 = push(1, 1)
    ck("a push that cannot happen still exits non-zero", r2.returncode != 0)
    sh = (ROOT / "fresh_discovery.sh").read_text()
    ck("...and the ladder goes on instead of the chain dying",
       'if python planner/push_leg.py "$i" "$at"; then' in sh
       and "the push did not happen; the ladder goes on" in sh)
    r = push(1, 2)          # an ordinary leg, nothing to do with the insert
    ck("an ordinary push still works", r.returncode == 0, r.stdout + r.stderr)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, dd in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and dd: print("      ", str(dd)[:200])
sys.exit(1 if bad else 0)
