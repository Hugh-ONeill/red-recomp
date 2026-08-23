"""An exit never taken that no walk reaches is UNFINISHED, and a hole says so.

Both laws came from one live page (Seafoam B2F, 2026-08-23): the header
read "FULLY WORKED: nothing here is untried" with two never-taken exits
listed below it, and those exits were drawn as holes with nothing saying a
hole is one-way.
"""
import sys
sys.path.insert(0, "planner")
from ledger import Candidate, fully_worked, unreached_ways

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

taken = Candidate(key="25,3", kind="door", status="taken", dest="B3F|21,0")
taken.look = "stairs"
unreached = Candidate(key="25,11", kind="door", status="unreachable")
unreached.look = "hole"
walked_far = Candidate(key="19,15", kind="door", status="unreachable",
                       dest="B1F|11,0")          # taken before, just not now
walked_far.look = "stairs"

ck("an exit never taken and not reachable is an unreached way",
   [c.key for c in unreached_ways([taken, unreached])] == ["25,11"])
ck("...and it makes the area NOT fully worked",
   not fully_worked([taken, unreached]))
ck("an exit already walked through is not one, even when unreachable now",
   unreached_ways([taken, walked_far]) == [])
ck("...so an area whose only unreachable exit is one you have used "
   "is still fully worked", fully_worked([taken, walked_far]))
ck("a hole is labelled as a hole", unreached.label().startswith("hole ("))

bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("  ok    " if ok else "  FAIL  ") + n)
if bad:
    print(f"\nUNREACHED WAYS BROKEN: {len(bad)} check(s) failed"); sys.exit(1)
print("\nunreached ways: all checks passed")
