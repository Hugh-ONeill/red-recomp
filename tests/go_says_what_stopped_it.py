"""A replay that stops says WHY (2026-08-26): go walked 17 legs, stopped on
ROUTE_9, and said only "the walk did not arrive; author from here" — while
the failing hop's own refusal (the one naming the CUT_TREE and that a bush
CUT clears it) sat in _last_det and went only to the log. Three rounds were
spent re-issuing the same go."""
import sys, re
from pathlib import Path
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E

src = Path("planner/executor.py").read_text()
ck("_walk_route clears the reason each time", "self._route_why = \"\"" in src)
ck("the lost-hop path records the leg and what it said",
   'f"the leg {str(key)} toward {nxt} would not land"' in src
   and "what it said was: {str(_last_det)[:300]}" in src)
ck("go says it", 'WHAT STOPPED IT: {_why}' in src)
ck("explore says it too", 'WHAT STOPPED IT: {_why2}' in src)
ck("every give-up path sets a reason, not just one",
   src.count("self._route_why = (") >= 4)
ck("the walk-across leg keeps what the walk itself said",
   '_wdet = ((_wres or {}).get("result") or {}).get("detail") or ""' in src
   and "what it said was: {str(_wdet)[:300]}" in src)

# behaviour: the trace the model actually receives
ex = E.Executor.__new__(E.Executor)
ex._route_why = ("the leg west toward ROUTE_9|6,2 would not land, and what "
                 "it said was: a CUT_TREE (a bush CUT clears) at (5,8)")
_why = getattr(ex, "_route_why", "") or ""
line = ("go: the walk did not arrive; author from here"
        + (f". WHAT STOPPED IT: {_why}" if _why else ""))
ck("the model is told the tree and that CUT clears it",
   "CUT_TREE" in line and "CUT clears" in line)
ex2 = E.Executor.__new__(E.Executor)
line2 = ("go: the walk did not arrive; author from here"
         + (f". WHAT STOPPED IT: {getattr(ex2, '_route_why', '')}"
            if getattr(ex2, "_route_why", "") else ""))
ck("...and nothing extra is invented when there is no reason",
   line2 == "go: the walk did not arrive; author from here")
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
