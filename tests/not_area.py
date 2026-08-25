"""{"map": X, "not_area": "X|r"}: a part of a map other than a named one.
A split map's far side has no area code until someone stands on it, so a
plan could not say "the other side of Route 10" and {"map":"ROUTE_10"} was
satisfied by the half it started in (2026-08-25)."""
import sys
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E
P = {"map": "ROUTE_10", "not_area": "ROUTE_10|0,4"}
ck("the named part does not satisfy it", not E.pred_holds(P, {"map": {"id": "ROUTE_10", "region": "0,4"}}))
ck("another part of the same map does", E.pred_holds(P, {"map": {"id": "ROUTE_10", "region": "9,40"}}))
ck("another map does not", not E.pred_holds(P, {"map": {"id": "LAVENDER_TOWN", "region": "1,1"}}))
P2 = {"map": "ROUTE_10", "not_area": ["ROUTE_10|0,4", "ROUTE_10|9,40"]}
ck("a list excludes every named part", not E.pred_holds(P2, {"map": {"id": "ROUTE_10", "region": "9,40"}}))
ck("...and a third part passes", E.pred_holds(P2, {"map": {"id": "ROUTE_10", "region": "3,50"}}))
ck("it is positional for the resume logic", "not_area" in E.pred_keys(P))
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
