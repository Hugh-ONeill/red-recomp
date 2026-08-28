#!/usr/bin/env python3
"""A leg whose plan fails to author is a run that yielded nothing, and the
second failure sends it to the ladder instead of two legs down the list.

"Navigate the Safari Zone" was pushed 34->36, 34->36, 35->37, 36->38 by
the authoring-failed branch alone — four failed author passes, each
costing minutes of model time, and no rung ever asked whether the leg
was done, misplaced, or wrong (2026-08-28).
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(name, ok): checks.append((name, bool(ok)))
sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the script parses", subprocess.run(["bash", "-n", str(ROOT / "fresh_discovery.sh")]).returncode == 0)
i = sh.index('if ! python planner/author.py "${aargs[@]}"; then')
blk = sh[i:i + 1600]
ck("an authoring failure writes a NOTHING row into the yield ledger",
   "no plan could even be written" in blk and ">> run/attempt_yield" in blk)
ck("...counts the earlier authoring-failed dispositions of this leg", "DISPOSED: authoring failed" in blk)
ck("...and the second failure sets the no-plan flag instead of pushing", "_no_plan=1" in blk and "not pushed again" in blk)
ck("the first failure still pushes and marks it", 'disposed "authoring failed; moved to after leg $_after"' in blk)
ck("the could-not-push fallback stays inside the push branch",
   blk.index("could not push leg") < blk.index("_no_plan=1") or
   sh.index("could not push leg") < sh.index("# WHAT THIS LEG GAINS IS THE EVIDENCE"))
ck("the flag is reset for every leg", '_no_plan=0' in sh and sh.index("_no_plan=0") < i)
ck("the dry gate honours it", '[ "${_dry:-0}" -ge 2 ] || [ "${_no_plan:-0}" = 1 ]' in sh)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
