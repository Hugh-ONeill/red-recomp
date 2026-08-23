"""The statues you can press, and the holes that are only rubble.

The Mansion's doors open when you press a STATUE while facing UP
(data/scripts/story6.lua, one shared EVENT_MANSION_SWITCH_ON flipping wall
blocks on all four floors).  Statues are neither map objects nor signs -- the
two things the observation carried -- so the model was told by the Super Nerd
that switches exist and shown nothing to press, for a whole leg.

And the hole scan was mine and wrong: warpPadOrHoleAt is a LOOK-UP the engine
consults inside takeWarp, once you already stand on a warp entry, to choose
the falling animation.  Asked of every cell it answers "hole" for decorative
rubble -- 171 of them on Mansion 2F, 40 on 3F (user, looking at the screen:
"those arent holes btw theyre rubble").  A hole is a warp you fall down.
"""
import sys
sys.path.insert(0, "planner")

checks = []
def ck(name, cond): checks.append((name, bool(cond)))

# --- the hole rule ------------------------------------------------------
def holes(cells, warps):
    """The scan as the shim now applies it."""
    at = {f"{x},{y}" for x, y in warps}
    return [(x, y) for (x, y, kind) in cells
            if kind == "hole" and f"{x},{y}" in at]

RUBBLE = [(4, 4, "hole"), (5, 4, "hole"), (6, 4, "hole")]      # tile-alike
REAL = [(20, 17, "hole")]                                      # a warp entry
ck("rubble is not counted as holes", holes(RUBBLE, []) == [])
ck("a hole on a warp entry still counts",
   holes(REAL, [(20, 17)]) == [(20, 17)])
ck("mixed: only the warp entry survives",
   holes(RUBBLE + REAL, [(20, 17)]) == [(20, 17)])

# --- the ledger says the statues ---------------------------------------
import ledger

class _Ex:
    explored = {"POKEMON_MANSION_2F|6,1": {}}
    visits = {"POKEMON_MANSION_2F|6,1": 7}
    frontier = {}
    def _where(self, _o): return "POKEMON_MANSION_2F|6,1"
    def __getattr__(self, _n): return {}

def head_for(switches):
    obs = {"party": [], "map": {"id": "POKEMON_MANSION_2F", "region": "6,1",
                                "switch_statues": switches}}
    return ledger.render([], _Ex(), obs).splitlines()[0]

h = head_for([{"x": 2, "y": 11, "reachable": True}])
ck("the statue is named", "(2,11)" in h)
ck("it says it is a switch statue", "SWITCH STATUE" in h)
ck("it says press facing up", "FACING" in h and "UP" in h)
ck("it says walk below it", "BELOW" in h)
ck("it does not say which to press or when",
   "you should" not in h.lower())

h2 = head_for([{"x": 2, "y": 11, "reachable": False}])
ck("an unreachable statue says so", "none of these can be walked to" in h2)

ck("no statues, no line", "SWITCH STATUE" not in head_for([]))

bad = [n for n, ok in checks if not ok]
for n, ok in checks:
    print(("  ok   " if ok else "  FAIL ") + n)
if bad:
    print("HEAD:", h[:400])
print(("FAIL %d/%d" % (len(bad), len(checks))) if bad
      else "ok %d checks" % len(checks))
sys.exit(1 if bad else 0)
