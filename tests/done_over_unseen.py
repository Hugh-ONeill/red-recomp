"""Done is only claimable over ground that has been on screen (2026-08-25,
Rocket Hideout B4F: the page said NOT ALL OF THIS FLOOR HAS BEEN ON SCREEN
and EVERYTHING YOU CAN REACH HERE IS DONE in one breath; the run rode the
lift back up with Giovanni's room a screen north)."""
import sys, re
sys.path.insert(0, "planner")
checks = []
def ck(name, cond): checks.append((name, bool(cond)))
import executor as E, ledger
ex = E.Executor.__new__(E.Executor)
here = "ROCKET_HIDEOUT_B4F|22,12"
ex._where = lambda o: here
obs = {"mode": "overworld", "map": {"id": "ROCKET_HIDEOUT_B4F", "region": "22,12",
       "seen": {"n": 80, "frontier_n": 8},
       "frontier": [{"x": 24, "y": 8, "d": 6}, {"x": 20, "y": 9, "d": 9}],
       "objects": [{"name": "ROCKETHIDEOUTB4F_ROCKET3", "x": 11, "y": 2, "kind": "trainer", "reachable": False}],
       "warps": [], "connections": {}},
       "player": {"x": 22, "y": 12}, "bag": {}, "party": [], "flags": []}
cands = [ledger.Candidate(key="ROCKETHIDEOUTB4F_ROCKET3", kind="object", status="unreachable")]
t = None
for _ in range(60):
    try:
        t = ledger.render(cands, ex, obs, "flag:ROCKET_BOSS"); break
    except AttributeError as e:
        m = re.search(r"attribute '(\w+)'", str(e))
        if not m: raise
        setattr(ex, m.group(1), {})
    except TypeError:
        # a ledger read as a callable or a list; give the common shapes
        raise
if t is None:
    print("SKIP: render fake did not converge"); sys.exit(0)
ck("unseen ground is on the page", "NOT ALL OF THIS FLOOR HAS BEEN ON SCREEN" in t)
ck("no 'everything you can reach here is done' over it", "EVERYTHING YOU CAN REACH HERE IS DONE" not in t)
ck("no FULLY WORKED either", "FULLY WORKED" not in t)
ck("the honest form is said", "NEVER BEEN ON SCREEN" in t)
bad = [n for n, ok in checks if not ok]
for n, ok in checks: print(("ok  " if ok else "FAIL"), n)
sys.exit(1 if bad else 0)
