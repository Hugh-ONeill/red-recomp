#!/usr/bin/env python3
"""A leg that is still moving is not stuck (2026-09-04).

Every ladder rung stood on "every party member is at least level 35" with Gloom
and Dugtrio at 34 — the campaign just spent had raised them from 27 and 20 —
and, with nothing left for a rung to change, the chain stopped one level from
done. The yield ledger already said the leg was moving. Now the chain reads it:
when the last real campaign gained levels, events, items or new ground, the leg
is run again, up to three replays, without counting it done.

Synthetic: a yield ledger in a temp file, plus the chain script's shape."""
import subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
LEG = "every party member is at least level 35"
OTHER = "Defeat the Team Rocket grunts in Silph Co. to reach the President"
def moved(rows):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "attempt_yield"; p.write_text("".join("\t".join(r) + "\n" for r in rows))
        r = subprocess.run([sys.executable, str(ROOT / "planner" / "leg_delta.py"), "moved", str(p), LEG], capture_output=True)
        return r.returncode
ck("a last campaign with levels gained means moved",
   moved([[LEG, "32", "3", "WHAT CHANGED WHILE THIS LEG RAN — levels gained: GLOOM 26->34, HITMONLEE 31->35; joined the party: DUGTRIO"]]) == 0)
ck("...events and new ground count too",
   moved([[LEG, "32", "1", "WHAT CHANGED WHILE THIS LEG RAN — events that fired: EVENT_X; 3 place(s) entered for the first time"]]) == 0)
ck("a last campaign that gained nothing means stuck",
   moved([[LEG, "32", "3", "WHAT CHANGED WHILE THIS LEG RAN — levels gained: GLOOM 20->30"], [LEG, "32", "3", "NOTHING new while this leg ran"]]) == 1)
ck("a DISPOSED row is not a campaign",
   moved([[LEG, "32", "3", "WHAT CHANGED WHILE THIS LEG RAN — levels gained: GLOOM 20->30"], [LEG, "32", "0", "DISPOSED: moved later"]]) == 0)
ck("...nor is a zero-attempt row", moved([[LEG, "32", "0", "NOTHING new while this leg ran: no plan could even be written"]]) == 1)
ck("another leg's gains do not count", moved([[OTHER, "31", "2", "WHAT CHANGED — levels gained: X 1->2"]]) == 1)
ck("no ledger at all means stuck", subprocess.run([sys.executable, str(ROOT / "planner" / "leg_delta.py"), "moved", "/nonexistent/yield", LEG], capture_output=True).returncode == 1)
sh = (ROOT / "fresh_discovery.sh").read_text()
ck("the chain replays a moving leg before its last word and its stop",
   'python planner/leg_delta.py moved run/attempt_yield "$leg"; then' in sh
   and sh.index('leg_delta.py moved run/attempt_yield') < sh.index('if wording_rung "" last-word; then continue; fi'))
ck("...at most three times, without advancing the progress index",
   '[ "${_rep:-0}" -lt 3 ]' in sh and "printf '%s\\n' \"$leg\" >> run/outline_replays" in sh)
ck("...and a fresh chain forgets the replay count", "run/outline_replays \\" in sh)
bad = [c for c in checks if not c[1]]
for n, ok, d in checks:
    print(("ok   " if ok else "FAIL ") + n + ("" if ok else f"\n      {str(d)[:300]}"))
print(f"{len(checks) - len(bad)}/{len(checks)} checks pass")
sys.exit(1 if bad else 0)
