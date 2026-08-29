#!/usr/bin/env python3
"""A leg that CAN now be written is not a dry leg.

Leg 13, 2026-08-29: two authoring failures for "Clear Route 4 of trainers"
were recorded as runs that yielded nothing (deliberately — the ladder must
get its turn on a leg nobody can write). Then the author finally produced
a valid plan, on EVENT_BEAT_ROUTE_4_TRAINER_0 — and the dry-tail gate
refused to run it: "its last 2 runs yielded nothing new". The rows said
something that had stopped being true. Same rule as a blocker that opens:
the record of the obstacle goes when the obstacle does. Rows from legs
that actually RAN and changed nothing are untouched.
"""
import subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sh = (ROOT / "fresh_discovery.sh").read_text()
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
ck("the chain drops a leg's could-not-be-written rows once a plan exists",
   'grep -Fq "no plan could even be written" run/attempt_yield' in sh
   and "'!($1 == L && $4 ~ /no plan could even be written/)'" in sh)
ck("...only when this pass actually produced one",
   '[ "${_no_plan:-0}" != 1 ]' in sh)
ck("...and says so", 'runs no longer count against it' in sh)
# the awk filter itself, on a real file
with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as f:
    f.write("Clear Route 4 of trainers\t12\t0\tNOTHING new while this leg ran: no plan could even be written for it (the author failed)\n")
    f.write("Clear Route 4 of trainers\t13\t0\tNOTHING new while this leg ran: no plan could even be written for it (the author failed)\n")
    f.write("Clear Route 4 of trainers\t13\t1\tNOTHING new while this leg ran: no event fired\n")
    f.write("Defeat Misty\t11\t3\tWHAT CHANGED WHILE THIS LEG RAN — badges earned: CASCADEBADGE\n")
    src = f.name
out = subprocess.run(["awk", "-F", "\t", "-v", "L=Clear Route 4 of trainers",
                      '!($1 == L && $4 ~ /no plan could even be written/)', src],
                     capture_output=True, text=True).stdout.splitlines()
ck("the two unwritable rows go", not any("could even be written" in l for l in out), out)
ck("...the leg's REAL dry run stays", any("no event fired" in l for l in out), out)
ck("...and other legs are untouched", any("CASCADEBADGE" in l for l in out), out)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
