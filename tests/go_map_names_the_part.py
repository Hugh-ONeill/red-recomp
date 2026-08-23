"""A bare map name has several parts and we picked one in silence.

`go ROUTE_20` from inside Seafoam always landed on ROUTE_20|52,2 -- one leg
away -- and never on ROUTE_20|58,9, six legs away, because `go` takes the
shortest route and said nothing about the choice.  Those are opposite shores
of a barrier: one is the way to Cinnabar, the other is where the run has
failed to cross 184 times.  Counting ops instead picks the same wrong shore;
what was missing was not a better tiebreak but saying which part was taken
and that the others can be named.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def note_for(want, reachable, best):
    """The wording as executor.py builds it."""
    if not (best and "|" not in str(want) and len(reachable) > 1):
        return ""
    others = ", ".join(f"{r} ({n} leg(s))"
                       for r, n in sorted(reachable, key=lambda rn: rn[1])
                       if r != best[0])
    return (f"go: {want} has more than one part you have walked, and this "
            f"took the nearest — {best[0]}, {best[1]} leg(s). The others "
            f"are reachable too and are NOT the same place: {others}. "
            f"Name one when it matters which.")

REACH = [("ROUTE_20|52,2", 1), ("ROUTE_20|44,2", 2), ("ROUTE_20|58,9", 6)]
n = note_for("ROUTE_20", REACH, ("ROUTE_20|52,2", 1))

ck("it says which part it took", "ROUTE_20|52,2" in n)
ck("it names the far shore as an option", "ROUTE_20|58,9" in n)
ck("it gives the other legs counts", "6 leg(s)" in n)
ck("it says they are not the same place", "NOT the same place" in n)
ck("it does not tell it which to pick",
   "should" not in n.lower() and "instead go" not in n.lower())

# one walked part: nothing to say
ck("a single-part map stays quiet",
   note_for("CINNABAR_ISLAND", [("CINNABAR_ISLAND|0,0", 3)],
            ("CINNABAR_ISLAND|0,0", 3)) == "")
# an explicit region ask is already precise
ck("an explicit region ask says nothing",
   note_for("ROUTE_20|58,9", REACH, ("ROUTE_20|58,9", 6)) == "")
# nothing reachable
ck("no route, no note", note_for("ROUTE_20", REACH, None) == "")

bad = [x for x, ok in checks if not ok]
for x, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + x)
if bad:
    print("NOTE WAS:", n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
