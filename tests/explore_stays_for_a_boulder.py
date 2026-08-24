"""explore must not walk off a floor whose unfinished business is a boulder.

`pushable` is in UNWORKED, so a floor holding one is correctly NOT "fully
worked" — but explore's `things` list is untouched/unspoken/cuttable only,
so a boulder gives it nothing to do and it falls through to "walk to the
nearest area with something untried". Victory Road 1F, switch unpressed and
its one workable boulder standing there, was left for PEWTER CITY (user,
2026-08-24: "explore took it to pewter instead of going to the ladder").

A push needs a DESTINATION and choosing one is not explore's to make. So it
says that and stops, which leaves the decision where it belongs.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
src = (ROOT / "planner" / "executor.py").read_text()
from planner import ledger

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


# the two lists that disagreed
ck("a boulder counts as unfinished business",
   "pushable" in ledger.UNWORKED)
ck("...and a floor holding one is not fully worked",
   not ledger.fully_worked([ledger.Candidate(key="B", kind="boulder",
                                             status="pushable")]))
ck("...but explore's things list still excludes it",
   '"untouched", "unspoken", "cuttable"' in src)

i = src.find("A BOULDER IS UNFINISHED BUSINESS THIS OP CANNOT FINISH")
block = src[i:i + 1800] if i > 0 else ""
ck("explore now stops instead of walking away", i > 0)
ck("...only for a boulder it can actually reach",
   'c.status == "pushable" and c.reachable' in block)
ck("...naming which boulder and where", "_names" in block)
ck("...and the op that takes a destination", "to_x" in block)
ck("...saying the choice is not its to make",
   "cannot make for you" in block)
ck("...and that leaving changes nothing",
   "leaves it exactly as it is" in block)
ck("it does not push anything itself",
   '"op": "push"' not in block)

# the walk-away path still exists for floors with nothing on them
ck("a floor with no boulder still walks on",
   "nowhere here: the nearest area over walked ground" in src)

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
