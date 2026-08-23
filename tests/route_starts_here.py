"""\"FROM HERE\" is a claim about where you stand.

Routes come off the learned REGION graph, and one region name can cover two
walkable parts of a floor (POKEMON_MANSION_1F's halves are both `1,1`,
painted when a switch setting joined them). The page told the model "THE
KNOWN WAY TO POKEMON_MANSION_2F FROM HERE: take the door at (5,27)" while
it stood in the sealed half, which no walk connects to that door — and it
sent `go` into it round after round (2026-08-23).
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

checks = []


def ck(name, ok):
    checks.append((name, bool(ok)))
    print(("  ok   " if ok else "  FAIL ") + name)


def first_leg_blocked(key, warps):
    """The guard, exactly as executor.py applies it."""
    if not key or not key[0].isdigit():
        return False            # a map EDGE, not a warp on this floor
    for w in warps:
        if f"{w.get('x')},{w.get('y')}" == key:
            return not w.get("reachable")
    return False


shut = [{"x": 5, "y": 27, "reachable": False},
        {"x": 26, "y": 27, "reachable": True}]
open_ = [{"x": 5, "y": 27, "reachable": True}]

ck("first leg unreachable: the route does not start here",
   first_leg_blocked("5,27", shut))
ck("first leg reachable: the route does start here",
   not first_leg_blocked("5,27", open_))
ck("a map EDGE is never called blocked",
   not first_leg_blocked("north", shut))
ck("a door this floor does not list is not called blocked",
   not first_leg_blocked("99,99", shut))
ck("another door being open does not rescue the first leg",
   first_leg_blocked("5,27", shut))

bad = [n for n, ok in checks if not ok]
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
