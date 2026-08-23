"""A way out seen once is never unseen.

note_frontier REPLACED a region's exit list with whatever the current
instant could reach, so a single observation that said "no" deleted a real
exit for good. SEAFOAM_ISLANDS_B2F|23,2 ended up holding ONE exit -- the
ladder the party came in by -- while the engine's own Collision says that
room is 56 cells with THREE ladders in it. The missing one, (25,11), is the
only link to the west half of the island and to the Route 20 door on the far
side of the barrier; the run walked five cells of that room and was told it
was finished. A boulder shoved into the one-cell neck at (25,5) is enough to
produce such an instant (57 cells -> 12), and the party carries STRENGTH.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

def store(frontier, here, keys, union=True):
    """The rule note_frontier applies to one observation's reachable warps."""
    if not keys:
        return frontier
    fresh = sorted(set(frontier.get(here) or []) | set(keys)) if union \
        else sorted(set(keys))
    frontier[here] = fresh
    return frontier

HERE = "SEAFOAM_ISLANDS_B2F|23,2"
CLEAR = ["25,3", "25,11", "25,14"]     # neck open: the whole room
SEALED = ["25,3"]                      # boulder in the neck at (25,5)

# the old rule: one bad instant and the crossing is gone for ever
f = {}
store(f, HERE, CLEAR, union=False)
store(f, HERE, SEALED, union=False)
ck("replace loses the exit", f[HERE] == ["25,3"])

# the rule now
f = {}
store(f, HERE, CLEAR)
store(f, HERE, SEALED)
ck("union keeps 25,11 after a sealed instant", "25,11" in f[HERE])
ck("union keeps 25,14 after a sealed instant", "25,14" in f[HERE])

# and it heals the other way round: sealed first, seen later
f = {}
store(f, HERE, SEALED)
ck("sealed-first starts with one", f[HERE] == ["25,3"])
store(f, HERE, CLEAR)
ck("a later clear visit restores all three", f[HERE] == sorted(CLEAR))

# an exit is added, never duplicated, and the list stays sorted
f = {}
for _ in range(4):
    store(f, HERE, CLEAR)
ck("idempotent", f[HERE] == sorted(CLEAR))

# nothing is invented: a region never observed stays absent
f = {}
store(f, HERE, [])
ck("no keys, no entry", HERE not in f)

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
