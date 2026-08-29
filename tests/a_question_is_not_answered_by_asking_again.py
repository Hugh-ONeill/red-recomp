#!/usr/bin/env python3
"""A thing waiting on a yes/no is not offered again as "never pressed".

Pewter, 2026-08-29 (user: "explore sends it back to the already explored
pewter to talk to the same guy over and over"): PEWTERCITY_SUPER_NERD1 was
pressed EIGHTEEN times. Each press came from explore, which sends interact
with no answer; the harness holds the box open on purpose (the Dome Fossil
rule) and the touch is then retracted — correctly, since an unanswered
question is not a press — so he read "never spoken to" for ever and
explore, ranking untouched things first, picked him again every visit.
Pressing again only re-asks. The answer is the model's to give, so the row
says what it is waiting for and explore offers something else.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "planner")); sys.path.insert(0, str(ROOT / "tests"))
import candidates as C, untried as U, ledger as L   # noqa: E402
checks = []
def ck(n, ok, d=""): checks.append((n, bool(ok), d))
ex = C.make(frontier={U.HERE: []})
o = C.obs(ex, [], objects=[{"name": "NERD", "kind": "npc", "x": 3, "y": 3, "reachable": True},
                           {"name": "SIGN", "kind": "sign", "x": 4, "y": 4, "reachable": True}])
ASK = 'ok (moved, NERD is ASKING something and the box is STILL OPEN — "Did you check out the MUSEUM?")'
cands = L.build(ex, o, target="map:X", outcomes={"NERD": {"n": 18, "last": ASK}},
                want_explore=False)
w = L.plan_explore(ex, o, cands, target="map:X")
ck("explore offers the other thing, not the one waiting on an answer",
   "press SIGN here" in w and "press NERD" not in w, w[:160])
page = L.render(cands, ex, o, target="map:X")
ck("...and the row says what it is waiting for, and how to give it",
   "WAITING ON YOUR ANSWER" in page and '{"op":"menu","index":1}' in page
   and "pressing it again only asks" in page)
ck("...while still quoting what it asked", "Did you check out the MUSEUM?" in page)
# with no question outstanding it is offered as usual
c2 = L.build(ex, o, target="map:X", outcomes={}, want_explore=False)
ck("a thing with no question outstanding is still offered",
   "press NERD here" in L.plan_explore(ex, o, c2, target="map:X"))
src = (ROOT / "planner" / "executor.py").read_text()
ck("explore's deed skips it too, at home and on arrival",
   src.count("and ASKING not in") == 2)
ck("the retract rule is untouched (an unanswered question is still not a press)",
   "if (ASKING in str(r.get(\"detail\") or \"\")\n                    and op == \"interact\" and step.get(\"name\")):" in src)
bad = [n for n, ok, _ in checks if not ok]
for n, ok, d in checks:
    print(("ok  " if ok else "FAIL"), n)
    if not ok and d: print("      ", str(d)[:200])
sys.exit(1 if bad else 0)
